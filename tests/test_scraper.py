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
            body, "https://www.maanmittauslaitos.fi/", r"valtiolle\.fi/fi/tyopaikat/"
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
        jobs = scraper.parse_job_links(body, scraper.UEF_JOBS, scraper.VARBI_JOB_LINK)

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
        kuntarekry_feed = """<rss version="2.0"><channel>
          <item><title>Metsävastaava</title>
            <link>https://kuntarekry.fi/fi/tyopaikat/metsavastaava-748001/</link>
            <guid>https://kuntarekry.fi/fi/tyopaikat/metsavastaava-748001/</guid>
            <description>Kaupungin metsien hoito.</description>
          </item>
          <item><title>Varhaiskasvatuksen opettaja</title>
            <link>https://kuntarekry.fi/fi/tyopaikat/opettaja-748002/</link>
            <guid>https://kuntarekry.fi/fi/tyopaikat/opettaja-748002/</guid>
            <description>Päiväkoti.</description>
          </item>
        </channel></rss>"""
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
            if url in scraper.VALTIOLLE_FEEDS:
                return luke_feed
            if url.startswith("https://kuntarekry.fi/"):
                return kuntarekry_feed
            if url == scraper.METSAKESKUS_JOBS:
                return metsakeskus_html
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
            "Metsähallitus", "Metsäkeskus", "Kuntarekry", "Duunitori", "Metsä Group", "UPM",
            "Valtiolle", "UEF",
        })
        self.assertTrue(all(job["category"] == "Forestry" for job in jobs))

    def test_portal_feeds_merge_finnish_and_english_postings(self):
        fi_feed = """<rss version="2.0"><channel>
          <item><title>Harjoittelija, metsien monimuotoisuus</title>
            <link>https://valtiolle.fi/fi/tyopaikat/harjoittelija-metsien-monimuotoisuus-26001/</link>
            <guid>https://valtiolle.fi/fi/tyopaikat/harjoittelija-metsien-monimuotoisuus-26001/</guid>
          </item>
        </channel></rss>"""
        en_feed = """<rss version="2.0"><channel>
          <item><title>Harjoittelija, metsien monimuotoisuus</title>
            <link>https://valtiolle.fi/en/jobs/harjoittelija-metsien-monimuotoisuus-26001/</link>
            <guid>https://valtiolle.fi/en/jobs/harjoittelija-metsien-monimuotoisuus-26001/</guid>
          </item>
          <item><title>Research Assistant, Remote Sensing of Forests and Peatlands</title>
            <link>https://valtiolle.fi/en/jobs/research-assistant-remote-sensing-26002/</link>
            <guid>https://valtiolle.fi/en/jobs/research-assistant-remote-sensing-26002/</guid>
          </item>
        </channel></rss>"""
        feeds = dict(zip(scraper.VALTIOLLE_FEEDS, [fi_feed, en_feed]))
        with patch.object(scraper, "fetch", side_effect=feeds.get):
            jobs = scraper.read_portal_feeds(scraper.VALTIOLLE_FEEDS)

        self.assertEqual([job["id"] for job in jobs], ["26001", "26002"])
        self.assertIn("/fi/tyopaikat/", jobs[0]["url"])

    def test_uef_finnish_and_english_links_are_one_job(self):
        pages = {
            scraper.UEF_JOBS: '<a href="https://uef.varbi.com/fi/what:job/jobID:984735/">'
                              'Professori, metsätuotteet</a>',
            scraper.UEF_JOBS_EN: '<a href="https://uef.varbi.com/en/what:job/jobID:984735/">'
                                 'Professor, Forest Products</a>'
                                 '<a href="https://uef.varbi.com/en/what:job/jobID:990001/">'
                                 'Doctoral Researcher, Forest Ecology</a>',
        }
        with patch.object(scraper, "fetch", side_effect=pages.get):
            jobs = scraper.read_links([scraper.UEF_JOBS, scraper.UEF_JOBS_EN], "https://www.uef.fi/",
                                      scraper.VARBI_JOB_LINK, scraper.VARBI_JOB_LINK)

        self.assertEqual([job["id"] for job in jobs], ["984735", "990001"])

    def test_metsalehti_page_is_read_when_feed_is_empty(self):
        page = """
          <a href="https://www.metsalehti.fi/tyopaikat/feed/">RSS</a>
          <a href="https://www.metsalehti.fi/tyopaikat/operaatioasiantuntija-tuotanto/">
            Operaatioasiantuntija, tuotanto</a>
          <a href="https://www.metsalehti.fi/laheta-tyopaikkailmoitus">Lähetä ilmoitus</a>
        """
        responses = {scraper.METSALEHTI_FEED: "<rss version='2.0'><channel/></rss>",
                     scraper.METSALEHTI_JOBS: page}
        with patch.object(scraper, "fetch", side_effect=responses.get), \
                patch.object(scraper.time, "sleep"):
            jobs = scraper.read_metsalehti()

        self.assertEqual([job["title"] for job in jobs], ["Operaatioasiantuntija, tuotanto"])
        self.assertTrue(scraper.is_forestry_related({**jobs[0], "source": "Metsälehti"}))
        self.assertFalse(scraper.is_forestry_related(jobs[0]))

    def test_filter_matches_internship_titles_in_finnish_and_english(self):
        for title in ["Summer Job, Wood Procurement", "Kesätyöt metsäpalveluissa",
                      "Summer Job in Forest Services – Timber Trade", "Kesätyö, puukauppa",
                      "Nature Surveyor Intern", "Luontoselvittäjä, kesätyö",
                      "Research Assistant, Forest Breeding", "Harjoittelija, taimitarha",
                      "Seasonal Worker for Timber Transport Operations"]:
            self.assertTrue(scraper.is_forestry_related({"title": title}), title)
        self.assertFalse(scraper.is_forestry_related({"title": "Korkeakouluharjoittelija, kyberrikos"}))

    def test_workday_reads_every_page_when_later_pages_report_zero_total(self):
        pages = [
            {"total": 3, "jobPostings": [{"title": "A", "externalPath": "/job/x/A_1"},
                                         {"title": "B", "externalPath": "/job/x/B_2"}]},
            {"total": 0, "jobPostings": [{"title": "C", "externalPath": "/job/x/C_3"}]},
        ]

        class Response:
            def __init__(self, payload):
                self.payload = payload
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def read(self):
                import json
                return json.dumps(self.payload).encode()

        with patch.object(scraper.urllib.request, "urlopen",
                          side_effect=[Response(page) for page in pages]):
            jobs = scraper.fetch_workday_jobs("https://example.wd.jobs/api", "https://example.wd.jobs")

        self.assertEqual([job["title"] for job in jobs], ["A", "B", "C"])

    def test_broad_portal_ads_need_a_forestry_title_or_core_word(self):
        police = {"source": "Valtiolle", "title": "Korkeakouluharjoittelija",
                  "description": "Hyvä työilmasto, kestävyys ja monimuotoisuus. Paikkatieto."}
        ministry = {"source": "Valtiolle", "title": "Hankintapäällikkö",
                    "description": "Maa- ja metsätalousministeriössä on haettavana..."}
        kindergarten = {"source": "Kuntarekry", "title": "Lärare, Västerskog daghem"}
        intern = {"source": "Valtiolle", "title": "Korkeakouluharjoittelija",
                  "description": "Tehtävässä mitataan metsien hiilivarastoja."}
        self.assertFalse(scraper.is_forestry_related(police))
        self.assertFalse(scraper.is_forestry_related(ministry))
        self.assertFalse(scraper.is_forestry_related(kindergarten))
        self.assertTrue(scraper.is_forestry_related(intern))
        self.assertTrue(scraper.is_forestry_related({"source": "Kuntarekry", "title": "Paikkatietosuunnittelija"}))

    def test_prune_removes_unrelated_jobs_after_a_backup(self):
        import contextlib
        import io
        import server

        def add(title, manual=0):
            db.upsert_scraped({"source": "Jobly", "external_id": title, "url": "", "title": title,
                               "company": "", "location": "", "posted": "", "category": ""}, None)
            with db.connect() as conn:
                conn.execute("UPDATE jobs SET manual=? WHERE title=?", (manual, title))
                return conn.execute("SELECT id FROM jobs WHERE title=?", (title,)).fetchone()["id"]

        keep = add("Metsäasiantuntija")
        hand_added = add("Asentaja", manual=1)
        add("Varastotyöntekijä")
        with db.connect() as conn:
            conn.execute("""INSERT INTO applications (user_id, job_id, status, status_changed_at,
                            created_at, updated_at) VALUES (1, ?, 'Applied', '', '', '')""", (hand_added,))

        with contextlib.redirect_stdout(io.StringIO()) as out:
            server.prune_unrelated_jobs()
        self.assertIn("2 unrelated jobs: 1 added by hand, 1 with tracker entries", out.getvalue())
        self.assertEqual(len(db.list_jobs()), 3)

        with contextlib.redirect_stdout(io.StringIO()):
            server.prune_unrelated_jobs(apply=True)
        self.assertEqual([job["id"] for job in db.list_jobs()], [keep])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0], 0)
        backups = list((db.DATA_DIR / "backups").glob("jobdesk-before-prune-*.db"))
        self.assertEqual(len(backups), 1)

    def test_personal_categories_are_read_only_when_asked(self):
        def jobly_page(slug):
            return f'<article about="/tyopaikka/{slug}-job-{len(slug)}"><h2 class="node__title">' \
                   f'{"Metsuri" if slug == "metsuri" else "Asentaja"}</h2></article>'

        def fetch(url):
            if url.startswith(scraper.BASE + "/tyopaikat/"):
                return jobly_page(url.rsplit("/", 1)[-1].split("?")[0])
            return "<rss version='2.0'><channel/></rss>"

        with patch.object(scraper, "fetch", side_effect=fetch), \
                patch.object(scraper, "fetch_workday_jobs", return_value=[]), \
                patch.object(scraper.time, "sleep"):
            scraper.run()
            self.assertEqual({job["category"] for job in db.list_jobs()}, {"Forestry"})
            scraper.run(personal=True)
        self.assertIn("Industrial", {job["category"] for job in db.list_jobs()})
