import random
import time
import unittest

import db
import scraper
import server
import test_server     # the module, not the class: a test class imported here would run its tests twice
from core.text import KeywordIndex, WordIndex, word_matches


class MatcherEquivalenceTests(unittest.TestCase):
    """The indexed matchers must say exactly what word_matches says, word pair by word pair."""

    def test_indexes_agree_with_word_matches_on_random_finnish_like_words(self):
        rng = random.Random(7)
        letters = "aeiouyäöklmnprstvhj"
        stems = ["asenn", "sähkö", "asiakas", "palvelu", "kokoonpano", "hoitaja", "ohjelmisto", "kehittä",
                 "analyy", "datakeskus", "trukki", "myynti", "varasto", "python", "data"]

        def word():
            base = rng.choice(stems) if rng.random() < .7 else "".join(rng.choice(letters) for _ in range(rng.randint(3, 9)))
            pre = "".join(rng.choice(letters) for _ in range(rng.randint(0, 6))) if rng.random() < .3 else ""
            return pre + base + "".join(rng.choice(letters) for _ in range(rng.randint(0, 7)))

        for _ in range(300):
            words = {word() for _ in range(rng.randint(1, 40))}
            keywords = {word() for _ in range(rng.randint(1, 60))}
            expected = {kw: {w for w in words if word_matches(w, kw)} for kw in keywords}
            expected = {kw: found for kw, found in expected.items() if found}
            self.assertEqual(KeywordIndex(keywords).matched(words), expected)
            index = WordIndex(words)
            for kw in keywords:
                self.assertEqual(index.matches(kw), expected.get(kw, set()), kw)


class JobsEndpointTests(unittest.TestCase):
    setUp_server = test_server.JobApiTests.setUp
    stop_server = test_server.JobApiTests.stop_server
    request = test_server.JobApiTests.request

    def setUp(self):
        self.setUp_server()
        check = db.start_check(1)
        titles = ["Ohjelmistokehittäjä", "Sairaanhoitaja", "Varastotyöntekijä", "Myyjä", "Data Analyst",
                  "Sähköasentaja", "Kirjanpitäjä", "Opettaja", "Lähihoitaja", "Software Developer"]
        filler = ("asiakaspalvelu python sähköasennus hoitotyö kirjanpito varastonhallinta trukkikortti "
                  "ohjelmistokehitys tietokannat analytiikka myyntityö opetus ") * 3
        for n in range(1000):
            job = {"source": "Valtiolle", "external_id": f"p{n}", "url": f"https://example.test/{n}",
                   "title": f"{titles[n % 10]} {n}", "company": "Esimerkki", "location": "Helsinki",
                   "posted": "2026-11-20", "category": "", "description": filler}
            db.upsert_scraped(job, check, fields=scraper.classify_job(job) or ["business"])
        cv_text = ("Python, SQL, tietokannat, data-analytiikka, asiakaspalvelu, myynti, sähköasennukset, "
                   "trukkikortti, varastotyö, kirjanpito, opetus, hoitotyö. ") * 4
        for n in range(10):
            db.save_cv(1, f"CV {n}", "fi", {"summary": cv_text + f" erikoisala{n}", "skills": cv_text})

    def test_a_thousand_jobs_against_ten_cvs_stays_fast(self):
        # Before: about 8.6 s on a fast computer for this much (37 million word comparisons), minutes on the
        # smallest server. The budget leaves room for slow test machines.
        server.MATCH_CACHE.clear()
        started = time.time()
        status, result = self.request("GET", "/api/jobs")
        first = time.time() - started
        self.assertEqual((status, len(result["jobs"])), (200, 1000))
        self.assertLess(first, 4.0)
        started = time.time()
        self.request("GET", "/api/jobs")
        self.assertLess(time.time() - started, first)         # matches come from the cache the second time

    def test_scopes_send_only_what_the_page_shows(self):
        ids = [j["id"] for j in db.list_jobs()]
        db.set_status(ids[0], "Applied", {}, 1)
        db.set_status(ids[1], "Shortlisted", {}, 1)
        cv_id = db.list_cvs(1)[0]["id"]
        db.save_fit(1, ids[1], cv_id, "key", "ad", "cv", {"suitability": "weak", "method": "rules", "summary": "",
                                                         "strengths": [], "gaps": [], "recommendations": []})
        status, mine = self.request("GET", "/api/jobs?scope=mine")
        self.assertEqual((status, sorted(j["id"] for j in mine["jobs"])), (200, sorted(ids[:2])))
        self.assertNotIn("ad_text", mine["jobs"][0])
        status, home = self.request("GET", "/api/jobs?scope=home")    # a "weak" rating must not break the sorting
        self.assertEqual(status, 200)
        self.assertEqual(len(home["jobs"]), 2 + server.HOME_PICKS)
        self.assertEqual(home["open_total"], 1000)
        status, everything = self.request("GET", "/api/jobs")
        self.assertEqual(len(everything["jobs"]), 1000)

    def test_static_files_are_cached_and_revalidated(self):
        status, body, headers = self.request("GET", "/static/core.js", include_headers=True)
        self.assertEqual((status, headers["Cache-Control"]), (200, "no-cache"))
        connection = __import__("http.client").client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        connection.request("GET", "/static/core.js", headers={"If-None-Match": headers["ETag"]})
        response = connection.getresponse()
        self.assertEqual((response.status, response.read()), (304, b""))
        connection.close()


if __name__ == "__main__":
    unittest.main()
