import unittest
from datetime import date, timedelta
from unittest.mock import patch

import db
import scraper
import server
import test_server     # the module, not the class: a test class imported here would run its tests twice

SOON = (date.today() + timedelta(days=5)).isoformat()
LATER = (date.today() + timedelta(days=40)).isoformat()
JOBS = [
    # source, id, title, company, location, text, posted
    ("Kuntarekry", "n1", "Sairaanhoitaja", "Pirkanmaan hyvinvointialue", "Tampere",
     f"Edellytämme sujuvaa suomen kielen taitoa. Hakuaika päättyy {SOON[8:10]}.{SOON[5:7]}.{SOON[:4]}.", "2026-11-01"),
    ("Valtiolle", "d1", "Junior Software Developer", "Digi- ja väestötietovirasto", "Helsinki",
     "We build public digital services. Finnish is not required; our working language is English. Hybrid work.",
     "2026-11-10"),
    ("Valtiolle", "s1", "Kesätyöntekijä, kirjasto", "Helsingin kaupunki", "Helsinki",
     f"Kesätyö kirjastossa. Hakuaika päättyy {LATER[8:10]}.{LATER[5:7]}.{LATER[:4]}.", "2026-11-05"),
    ("Valtiolle", "i1", "Harjoittelija, viestintä", "Ulkoministeriö", "Helsinki",
     "Palkallinen harjoittelu, 30 op. Opintojen ohessa mahdollista. Suomen kielen taito katsotaan eduksi.", "2026-11-03"),
    ("Kuntarekry", "t1", "Master’s Thesis Worker, AI", "Oulun kaupunki", "Oulu",
     "Master's thesis on machine learning. The work is done remotely.", "2026-11-08"),
]


class SearchTests(unittest.TestCase):
    setUp_server = test_server.JobApiTests.setUp
    stop_server = test_server.JobApiTests.stop_server
    request = test_server.JobApiTests.request

    def setUp(self):
        self.setUp_server()
        check = db.start_check(1)
        self.ids = {}
        for source, external_id, title, company, location, text, posted in JOBS:
            job = {"source": source, "external_id": external_id, "url": f"https://example.test/{external_id}",
                   "title": title, "company": company, "location": location, "posted": posted, "category": "",
                   "description": text}
            db.upsert_scraped(job, check, fields=scraper.classify_job(job) or ["business"], meta=scraper.job_meta(job))
        self.ids = {j["external_id"]: j["id"] for j in db.list_jobs()}

    def search(self, query=""):
        status, result = self.request("GET", "/api/search" + (f"?{query}" if query else ""))
        self.assertEqual(status, 200, result)
        return result

    def titles(self, query=""):
        return [j["title"] for j in self.search(query)["jobs"]]

    def test_all_open_jobs_newest_first_with_counts(self):
        result = self.search()
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["jobs"][0]["title"], "Junior Software Developer")
        self.assertEqual(result["facets"]["summer"], 1)
        self.assertEqual(result["facets"]["level"]["internship"], 1)
        self.assertEqual(result["facets"]["region"]["01"], 3)
        first = result["jobs"][0]
        self.assertEqual((first["municipality"], first["region"], first["work_mode"]), ("Helsinki", "Uusimaa", "hybrid"))
        self.assertNotIn("external_id", first)

    def test_keywords_match_word_starts_in_any_language(self):
        self.assertEqual(self.titles("q=sairaanhoit"), ["Sairaanhoitaja"])
        self.assertEqual(self.titles("q=nurse"), ["Sairaanhoitaja"])             # English name of the Finnish role
        self.assertEqual(self.titles("q=machine%20learning"), ["Master’s Thesis Worker, AI"])
        self.assertEqual(self.titles("q=kirjasto"), ["Kesätyöntekijä, kirjasto"])
        self.assertEqual(self.titles("q=helsingin"), ["Kesätyöntekijä, kirjasto"])
        self.assertEqual(self.titles("q=zzzz"), [])

    def test_finnish_not_required_and_summer_jobs(self):
        self.assertEqual(self.titles("no_finnish=1"), ["Junior Software Developer", "Master’s Thesis Worker, AI"])
        self.assertEqual(self.titles("type=summer"), ["Kesätyöntekijä, kirjasto"])

    def test_level_place_mode_and_student_filters(self):
        self.assertEqual(self.titles("level=internship,thesis"), ["Master’s Thesis Worker, AI", "Harjoittelija, viestintä"])
        self.assertEqual(self.titles("level=entry"), ["Junior Software Developer"])
        self.assertEqual(len(self.titles("region=01")), 3)
        self.assertEqual(self.titles("municipality=564"), ["Master’s Thesis Worker, AI"])
        self.assertEqual(self.titles("mode=remote"), ["Master’s Thesis Worker, AI"])
        self.assertEqual(self.titles("paid=1&with_studies=1"), ["Harjoittelija, viestintä"])
        self.assertEqual(self.titles("sector=public&level=thesis"), ["Master’s Thesis Worker, AI"])

    def test_sort_by_deadline_paging_and_unknown_values(self):
        titles = self.titles("sort=deadline")
        self.assertEqual(titles[:2], ["Sairaanhoitaja", "Kesätyöntekijä, kirjasto"])
        with patch.object(server, "SEARCH_PAGE_SIZE", 2):
            page2 = self.search("page=2")
            self.assertEqual((page2["page"], page2["pages"], len(page2["jobs"])), (2, 3, 2))
            self.assertEqual(self.search("page=99")["page"], 3)
        result = self.search("level=guru&region=99&sort=random&page=x&mode=")
        self.assertEqual((result["total"], result["filters"]["level"], result["filters"]["sort"]), (5, [], "newest"))

    def test_closed_and_private_jobs_are_not_listed(self):
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET listing_status='expired' WHERE external_id='n1'")
        db.add_manual({"source": "Saved", "external_id": "private-1-x", "title": "My own saved job", "private": True}, 1)
        self.assertNotIn("Sairaanhoitaja", self.titles())
        self.assertNotIn("My own saved job", self.titles())

    last_link_token = test_server.JobApiTests.last_link_token
    sign_in_by_link = test_server.JobApiTests.sign_in_by_link
    member_cookie = test_server.JobApiTests.member_cookie
    choose_fields = test_server.JobApiTests.choose_fields

    def test_a_members_fields_are_the_default_filter_but_every_field_can_be_searched(self):
        member = self.member_cookie()
        self.choose_fields(member, ["it"])
        status, mine = self.request("GET", "/api/search", headers=member)
        self.assertEqual(status, 200)
        self.assertTrue(mine["filters"]["field_default"])
        self.assertEqual(mine["filters"]["field"], ["it"])
        self.assertNotIn("Sairaanhoitaja", [j["title"] for j in mine["jobs"]])
        self.assertGreaterEqual(mine["facets"]["field"]["it"], 1)
        _, every = self.request("GET", "/api/search?field=all", headers=member)
        self.assertEqual((every["total"], every["filters"]["field_default"]), (5, False))
        _, health = self.request("GET", "/api/search?field=health", headers=member)
        self.assertEqual([j["title"] for j in health["jobs"]], ["Sairaanhoitaja"])


if __name__ == "__main__":
    unittest.main()
