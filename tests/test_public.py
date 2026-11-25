import json
import re
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import db
import public
import scraper
import test_server     # the module, not the class: a test class imported here would run its tests twice

LATER = (date.today() + timedelta(days=20)).isoformat()


class PublicPageTests(unittest.TestCase):
    setUp_server = test_server.JobApiTests.setUp
    stop_server = test_server.JobApiTests.stop_server
    request = test_server.JobApiTests.request

    def setUp(self):
        self.setUp_server()
        indexing = patch.object(public.config, "PUBLIC_INDEXING", True)      # the default is off
        indexing.start()
        self.addCleanup(indexing.stop)
        self.check = db.start_check(1)
        self.ids = {}
        long_text = "Hoitotyötä sisätautiosastolla. " * 60
        self.add("Kuntarekry", "nurse", "Sairaanhoitaja", "Kuopion kaupunki", "Kuopio",
                 long_text + "Edellytämme sujuvaa suomen kielen taitoa. Palkka 3 100 €/kk.")
        self.add("Valtiolle", "dev", "Junior Software Developer", "Esimerkkivirasto", "Helsinki",
                 "Finnish is not required. Hybrid work. Permanent, full-time.")
        self.add("Valtiolle", "summer", "Kesätyöntekijä, kirjasto", "Helsingin kaupunki", "Helsinki", "Kesätyö.")
        self.add("Valtiolle", "closed", "Kirjanpitäjä", "Verovirasto", "Helsinki", "Taloushallinto.")
        self.add("Työmarkkinatori", "tmt", "Lähihoitaja", "Hyvinvointialue", "Tampere", "Hoitotyö.")
        self.add("Stora Enso", "off", "Myyntiassistentti", "Stora Enso", "Helsinki", "Switched-off source.")
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET listing_status='expired' WHERE external_id='closed'")
            conn.execute("UPDATE jobs SET contact_name='Maija Rekrytoija', contact_phone='040 123 4567' WHERE external_id='nurse'")
        # Not public: a member's own saved job, a job a member shared, the administrator's own job type
        self.ids["private"] = db.add_manual({"source": "Saved", "external_id": "private-1-x", "title": "Oma tallennettu työ",
                                             "private": True}, 1, field_ids=["it"])
        self.ids["community"] = db.add_manual({"source": "Community", "external_id": "c1", "title": "Jaettu ilmoitus",
                                               "location": "Helsinki"}, 1, field_ids=["it"])
        self.ids["personal"] = db.add_manual({"source": "Personal", "external_id": "p1", "title": "Asentaja",
                                              "category": "Industrial"}, 1)
        self.ids["employer"] = db.add_manual({"source": "Employer", "external_id": "employer-1", "title": "Barista </script><b>x</b>",
                                              "company": "Esimerkki Café Oy", "location": "Turku", "deadline": LATER,
                                              "ad_text": "Full employer text. " * 80, "url": "https://example.test/apply"},
                                             1, field_ids=["hospitality"], meta={"municipality_code": "853", "region_code": "02",
                                                                                 "employment_types": ["part_time"]})

    def add(self, source, external_id, title, company, location, text):
        job = {"source": source, "external_id": external_id, "url": f"https://example.test/{external_id}", "title": title,
               "company": company, "location": location, "posted": "2026-11-20", "category": "", "description": text}
        db.upsert_scraped(job, self.check, fields=scraper.classify_job(job) or ["business"], meta=scraper.job_meta(job))
        self.ids[external_id] = next(j["id"] for j in db.list_jobs() if j["external_id"] == external_id)

    def get(self, path):
        status, body, headers = self.request("GET", path, headers={"Cookie": ""}, include_headers=True)
        return status, body.decode("utf-8") if isinstance(body, bytes) else body, headers

    def test_only_open_shared_feed_and_employer_ads_are_public(self):
        status, body, headers = self.get("/jobs")
        self.assertEqual((status, headers["X-Robots-Tag"]), (200, "index, follow"))
        for title in ("Sairaanhoitaja", "Junior Software Developer", "Kesätyöntekijä, kirjasto", "Barista"):
            self.assertIn(title, body)
        for title in ("Kirjanpitäjä", "Lähihoitaja", "Oma tallennettu työ", "Jaettu ilmoitus", "Asentaja", "Myyntiassistentti"):
            self.assertNotIn(title, body, title)
        for key in ("private", "community", "personal", "tmt", "off"):
            self.assertEqual(self.get(f"/job/{self.ids[key]}")[0], 404, key)
        sitemap = self.get("/sitemap.xml")[1]
        self.assertIn(f"/job/{self.ids['dev']}-junior-software-developer", sitemap)
        for key in ("private", "community", "personal", "tmt", "closed"):
            self.assertNotIn(f"/job/{self.ids[key]}-", sitemap, key)

    def test_no_contact_details_or_private_data_on_public_pages(self):
        for path in ("/jobs", "/jobs/town/kuopio", f"/job/{self.ids['nurse']}", "/sitemap.xml"):
            body = self.get(path)[1]
            for secret in ("Maija Rekrytoija", "040 123 4567", "admin@example.test", "private-1-x"):
                self.assertNotIn(secret, body, (path, secret))

    def test_job_pages_have_jobposting_data_and_link_to_the_original(self):
        status, body, headers = self.get(f"/job/{self.ids['nurse']}-sairaanhoitaja")
        self.assertEqual((status, headers["X-Robots-Tag"]), (200, "index, follow"))
        data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S).group(1))
        self.assertEqual((data["@type"], data["title"], data["hiringOrganization"]["name"]),
                         ("JobPosting", "Sairaanhoitaja", "Kuopion kaupunki"))
        self.assertEqual(data["jobLocation"]["address"]["addressLocality"], "Kuopio")
        self.assertEqual(data["baseSalary"]["value"], {"@type": "QuantitativeValue", "unitText": "MONTH", "value": 3100})
        self.assertIn('href="https://example.test/nurse"', body)
        self.assertIn("This is the start of the ad", body)          # feed ads are an excerpt
        self.assertLess(len(data["description"]), 800)
        # An employer's own ad is shown in full, and nothing in it can close the script element
        status, body, _ = self.get(f"/job/{self.ids['employer']}")
        script = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.S).group(1)
        self.assertEqual(body.replace(script, "").count("Full employer text."), 80)
        self.assertNotIn("</script><b>", script)
        self.assertEqual(json.loads(script)["title"], "Barista </script><b>x</b>")
        self.assertNotIn("<b>x</b>", body.replace(script, ""))

    def test_closed_jobs_say_so_and_are_not_indexed(self):
        status, body, headers = self.get(f"/job/{self.ids['closed']}")
        self.assertEqual((status, headers["X-Robots-Tag"]), (200, "noindex, follow"))
        self.assertIn("This ad has closed", body)
        self.assertNotIn("application/ld+json", body)

    def test_landing_pages_filters_and_robots_rules(self):
        cases = {
            "/jobs/summer": ("Summer jobs in Finland", ["Kesätyöntekijä, kirjasto"]),
            "/jobs/town/kuopio": ("Jobs in Kuopio", ["Sairaanhoitaja"]),
            "/jobs/field/health": ("Healthcare: jobs in Finland", ["Sairaanhoitaja"]),
            "/jobs/no-finnish": ("Jobs in Finland where Finnish isn&#x27;t required", ["Junior Software Developer"]),
            "/jobs/region/uusimaa": ("Jobs in Uusimaa", ["Junior Software Developer", "Kesätyöntekijä, kirjasto"]),
        }
        for path, (h1, titles) in cases.items():
            status, body, headers = self.get(path)
            self.assertEqual((status, headers["X-Robots-Tag"]), (200, "index, follow"), path)
            self.assertIn(f"<h1>{h1}</h1>", body)
            self.assertEqual(sorted(re.findall(r'<h3><a href="/job/[^"]+">([^<]+)</a>', body)), sorted(titles), path)
            self.assertIn(f'rel="canonical" href="http://localhost:8765{path}"', body)
        self.assertEqual(self.get("/jobs/town/nowhere")[0], 404)
        self.assertEqual(self.get("/jobs/colour/blue")[0], 404)
        status, _, headers = self.get("/jobs/field/law/town/utsjoki")      # exists, but nothing open: not indexed
        self.assertEqual((status, headers["X-Robots-Tag"]), (200, "noindex, follow"))
        status, body, headers = self.get("/jobs?q=nurse")                   # searches aren't indexed
        self.assertEqual(headers["X-Robots-Tag"], "noindex, follow")
        self.assertIn("Sairaanhoitaja", body)

    def test_paths_and_filters_round_trip(self):
        for path in ("/jobs", "/jobs/summer", "/jobs/field/it/level/internship/town/tampere/no-finnish",
                     "/jobs/field/social-care/region/north-karelia", "/jobs/type/part-time/remote"):
            self.assertEqual(public.path_for(public.filters_for_path(path)), path)

    def test_pages_load_nothing_from_other_sites(self):
        for path in ("/jobs", f"/job/{self.ids['dev']}", "/employers.html", "/"):
            body = self.get(path)[1]
            loads = re.findall(r'<link[^>]+rel="(?:stylesheet|preconnect|preload)"[^>]*href="(https?://[^"]+)"', body)
            loads += re.findall(r'<(?:script|img|iframe)[^>]+src="(https?://[^"]+)"', body)
            self.assertEqual(loads, [], path)
        status, font, headers = self.request("GET", "/static/fonts/instrument-sans-normal-400-latin.woff2",
                                             headers={"Cookie": ""}, include_headers=True)
        self.assertEqual((status, headers["Content-Type"]), (200, "font/woff2"))
        self.assertIn("immutable", headers["Cache-Control"])
        css = self.get("/static/fonts/fonts.css")[1]
        for name in re.findall(r"url\(([^)]+)\)", css):
            self.assertEqual(self.request("GET", f"/static/fonts/{name}", headers={"Cookie": ""})[0], 200, name)

    def test_until_indexing_is_switched_on_nothing_is_indexed(self):
        with patch.object(public.config, "PUBLIC_INDEXING", False):
            for path in ("/jobs", "/jobs/summer", f"/job/{self.ids['dev']}", "/employers.html"):
                status, body, headers = self.get(path)
                self.assertEqual((status, headers["X-Robots-Tag"]), (200, "noindex, nofollow"), path)
                if path != "/employers.html":
                    self.assertIn('<meta name="robots" content="noindex, nofollow">', body)
            self.assertEqual(self.get("/robots.txt")[1], "User-agent: *\nDisallow: /\n")

    def test_the_rest_of_the_site_stays_out_of_search_engines(self):
        _, _, headers = self.request("GET", "/api/state", include_headers=True)
        self.assertEqual(headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.get("/")[2]["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(self.get("/employers.html")[2]["X-Robots-Tag"], "index, follow")
        robots = self.get("/robots.txt")[1]
        self.assertIn("Disallow: /api/", robots)
        self.assertIn("Sitemap: http://localhost:8765/sitemap.xml", robots)


if __name__ == "__main__":
    unittest.main()
