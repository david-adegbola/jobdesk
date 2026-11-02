import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import scraper


FEED = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Metsäasiantuntija</title>
      <link>/tyopaikat/metsaasiantuntija/</link>
      <guid>metsalehti-job-1</guid>
      <pubDate>Mon, 02 Nov 2026 10:00:00 +0000</pubDate>
      <description>Metsäalan rekrytointi</description>
    </item>
  </channel>
</rss>
"""


class MetsalehtiFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir_patch = patch.object(db, "DATA_DIR", data_dir)
        self.db_file_patch = patch.object(db, "DB_FILE", data_dir / "jobdesk.db")
        self.data_dir_patch.start()
        self.db_file_patch.start()
        self.addCleanup(self.data_dir_patch.stop)
        self.addCleanup(self.db_file_patch.stop)
        db.init()

    def test_parser_reads_feed_job_fields(self):
        self.assertEqual(scraper.parse_metsalehti_feed(FEED), [{
            "id": "metsalehti-job-1",
            "title": "Metsäasiantuntija",
            "url": "https://www.metsalehti.fi/tyopaikat/metsaasiantuntija/",
            "company": "",
            "location": "",
            "posted": "2026-11-02",
            "description": "Metsäalan rekrytointi",
        }])

    def test_parser_skips_entries_without_a_job_link(self):
        body = FEED.replace(
            "<link>/tyopaikat/metsaasiantuntija/</link>",
            "",
        )
        self.assertEqual(scraper.parse_metsalehti_feed(body), [])

    def test_run_imports_feed_jobs_as_forestry(self):
        def fetch(url):
            return FEED if url == scraper.METSALEHTI_FEED else "<html></html>"

        with patch.object(scraper, "fetch", side_effect=fetch), \
                patch.object(scraper, "fetch_workday_jobs", return_value=[]), \
                patch.object(scraper.time, "sleep"):
            result = scraper.run()

        self.assertEqual(result, {"found": 1, "new": 1, "error": None})
        jobs = db.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], "Metsälehti")
        self.assertEqual(jobs[0]["category"], "Forestry")
        self.assertEqual(jobs[0]["title"], "Metsäasiantuntija")
        self.assertIn("Metsäalan rekrytointi", jobs[0]["ad_text"])

    def test_job_link_parser_reads_metsakeskus_and_mml_links(self):
        body = """
          <article><h3><a href="https://ats.talentadore.com/apply/metsavarat/abc123">
            Harjoittelija, metsävaratiedon ylläpito
          </a></h3></article>
          <h2>Avoimet työpaikat</h2>
          <p><a href="https://valtiolle.fi/fi/tyopaikat/paikkatietoasiantuntija-1234/">
            Paikkatietoasiantuntija
          </a></p>
        """
        metsakeskus = scraper.parse_job_links(
            body, scraper.METSAKESKUS_JOBS, r"ats\.talentadore\.com/apply/"
        )
        mml = scraper.parse_job_links(
            body, scraper.MML_JOBS, r"valtiolle\.fi/fi/tyopaikat/"
        )

        self.assertEqual(metsakeskus[0]["title"], "Harjoittelija, metsävaratiedon ylläpito")
        self.assertEqual(mml[0]["title"], "Paikkatietoasiantuntija")
        self.assertEqual(len(metsakeskus), 1)
        self.assertEqual(len(mml), 1)

    def test_job_link_parser_reads_uef_varbi_links(self):
        body = """
          <a aria-label="Professori, metsätuotteet ja -palvelut"
             href="https://uef.varbi.com/fi/what:job/jobID:984735/type:job/where:4/apply:1">
            Professori, metsätuotteet ja -palvelut
          </a>
        """
        jobs = scraper.parse_job_links(
            body, scraper.UEF_JOBS, r"uef\.varbi\.com/fi/what:job/jobID:"
        )

        self.assertEqual(len(jobs), 1)
        self.assertTrue(scraper.is_forestry_related(jobs[0]))

    def test_workday_parser_builds_finnish_job_links(self):
        jobs = scraper.parse_workday_jobs({
            "jobPostings": [{
                "title": "Forest Data Specialist",
                "externalPath": "/job/Helsinki/Forest-Data-Specialist_R123",
                "locationsText": "Helsinki",
                "bulletFields": ["R123"],
            }],
        }, "https://example.wd.jobs/fi-FI/Careers")

        self.assertEqual(jobs, [{
            "id": "R123",
            "title": "Forest Data Specialist",
            "url": "https://example.wd.jobs/fi-FI/Careers/job/Helsinki/Forest-Data-Specialist_R123",
            "company": "",
            "location": "Helsinki",
            "posted": "",
            "description": "",
        }])

    def test_forestry_filter_includes_related_studies_and_avoids_brand_only_matches(self):
        self.assertTrue(scraper.is_forestry_related({"title": "Forest Bioeconomy Specialist"}))
        self.assertTrue(scraper.is_forestry_related({"title": "Paikkatietoasiantuntija"}))
        self.assertTrue(scraper.is_forestry_related({"title": "Marknadsområdeschef, Stora Enso Skog"}))
        self.assertTrue(scraper.is_forestry_related({
            "title": "Tutkija", "description": "Metsäekologinen tutkimus",
        }))
        self.assertFalse(scraper.is_forestry_related({"title": "Intresseanmälan - Metsä Tissue Sverige"}))

    def test_ad_fetch_refuses_non_public_destinations(self):
        self.assertFalse(scraper.is_public_http_url("http://127.0.0.1/"))
        self.assertFalse(scraper.is_public_http_url("file:///etc/passwd"))
        self.assertTrue(scraper.is_public_http_url("https://8.8.8.8/"))
        with patch.object(scraper.socket, "getaddrinfo", return_value=[
            (None, None, None, None, ("10.0.0.5", 443)),
        ]):
            self.assertFalse(scraper.is_public_http_url("https://job.example.test/"))

    def test_run_imports_only_forestry_related_jobs_from_added_sources(self):
        jobs_feed = """<rss version="2.0"><channel>
          <item><title>Luonnonhoidon asiantuntija</title>
            <link>https://metsa.rekrytointi.com/paikat/?jid=7</link>
            <guid>metsa-7</guid><description>Työ liittyy luonnon monimuotoisuuteen.</description>
          </item>
          <item><title>Kirjanpitäjä</title><link>https://metsa.rekrytointi.com/paikat/?jid=8</link>
            <guid>metsa-8</guid><description>Taloushallinto.</description>
          </item>
        </channel></rss>"""
        luke_feed = """<rss version="2.0"><channel>
          <item><title>Tutkija</title>
            <link>https://valtiolle.fi/fi/tyopaikat/tutkija-123/</link>
            <guid>luke-1</guid><description>Metsäekologinen tutkimus.</description>
          </item>
          <item><title>Kirjanpitäjä</title>
            <link>https://valtiolle.fi/fi/tyopaikat/kirjanpitaja-456/</link>
            <guid>luke-2</guid><description>Taloushallinto.</description>
          </item>
        </channel></rss>"""
        metsakeskus_html = """
          <a href="https://ats.talentadore.com/apply/metsavarat/abc123">
            Harjoittelija, metsävaratiedon ylläpito
          </a>
        """
        mml_html = """
          <a href="https://valtiolle.fi/fi/tyopaikat/paikkatietoasiantuntija-1234/">
            Paikkatietoasiantuntija
          </a>
          <a href="https://valtiolle.fi/fi/tyopaikat/viestinta-9999/">Viestintäasiantuntija</a>
        """
        duunitori_html = """
          <a href="/tyopaikat/tyo/metsaalan-ammatillinen-ohjaaja-20690011">
            Metsäalan ammatillinen ohjaaja
          </a>
        """
        uef_html = """
          <a href="https://uef.varbi.com/fi/what:job/jobID:984735/type:job/where:4/apply:1">
            Professori, metsätuotteet ja -palvelut
          </a>
          <a href="https://uef.varbi.com/fi/what:job/jobID:123456/type:job/where:4/apply:1">
            Viestintäasiantuntija
          </a>
        """

        def fetch(url):
            if url == scraper.METSALEHTI_FEED:
                return "<rss version='2.0'><channel/></rss>"
            if url == scraper.METSAHALLITUS_FEED:
                return jobs_feed
            if url == scraper.LUKE_FEED:
                return luke_feed
            if url == scraper.METSAKESKUS_JOBS:
                return metsakeskus_html
            if url == scraper.MML_JOBS:
                return mml_html
            if url in {scraper.DUUNITORI_JOBS, scraper.DUUNITORI_JOENSUU_JOBS}:
                return duunitori_html
            if url == scraper.UEF_JOBS:
                return uef_html
            return "<html></html>"

        def workday_jobs(endpoint, job_base):
            source = next(name for name, api, _ in scraper.WORKDAY_SOURCES if api == endpoint)
            title = {
                "Metsä Group": "Metsäasiantuntija",
                "UPM": "Forest Specialist",
                "Stora Enso": "Accountant",
            }[source]
            return [{
                "id": f"{source}-1",
                "title": title,
                "url": f"{job_base}/job/Helsinki/{source}-1",
                "company": "",
                "location": "Helsinki",
                "posted": "",
                "description": "",
            }]

        with patch.object(scraper, "fetch", side_effect=fetch), \
                patch.object(scraper, "fetch_workday_jobs", side_effect=workday_jobs), \
                patch.object(scraper.time, "sleep"):
            result = scraper.run()

        self.assertEqual(result, {"found": 8, "new": 8, "error": None})
        jobs = db.list_jobs()
        self.assertEqual({job["source"] for job in jobs}, {
            "Metsähallitus", "Metsäkeskus", "Maanmittauslaitos", "Duunitori", "Metsä Group", "UPM",
            "Luke", "UEF",
        })
        self.assertTrue(all(job["category"] == "Forestry" for job in jobs))
