import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import db
import scraper
import skills
from core import fields as core_fields

PROFILES = scraper.PROFILES


def fields_of(title, description="", source="Community"):
    return scraper.relevant_fields({"title": title, "description": description, "source": source})


class ProfileTests(unittest.TestCase):
    def test_every_profile_loads_in_order(self):
        self.assertEqual(list(PROFILES), ["forestry", "it", "engineering", "health", "business", "culture"])
        for profile in PROFILES.values():
            self.assertTrue(profile["skills"] and profile["role_types"] and profile["search_terms"], profile["id"])

    def test_bad_profiles_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps({"id": "bad"}), encoding="utf-8")
            with self.assertRaisesRegex(core_fields.FieldError, "missing"):
                core_fields.load_profile(path)
            good = json.loads((config.FIELDS_DIR / "it.json").read_text(encoding="utf-8"))
            good["skills"][0]["pattern"] = "(unclosed"
            path.write_text(json.dumps(good), encoding="utf-8")
            with self.assertRaisesRegex(core_fields.FieldError, "invalid pattern"):
                core_fields.load_profile(path)

    def test_each_field_recognises_its_own_titles_in_three_languages(self):
        cases = {
            "Ohjelmistokehittäjä": ["it"], "Software Developer": ["it"], "IT-tukihenkilö": ["it"],
            "Automaatioinsinööri": ["engineering"], "Mechanical Design Engineer": ["engineering"],
            "Sairaanhoitaja, sisätautiosasto": ["health"], "Sjuksköterska": ["health"], "Lähihoitaja": ["health"],
            "Kirjanpitäjä": ["business"], "Marketing Coordinator": ["business"],
            "Metsäasiantuntija": ["forestry"], "Forest Data Specialist": ["forestry"],
        }
        for title, expected in cases.items():
            self.assertEqual(fields_of(title), expected, title)

    def test_metropolia_programme_areas_are_recognised(self):
        cases = {
            "Game Designer": "culture", "3D Artist, mobile games": "culture", "Graafinen suunnittelija": "culture",
            "UX Designer": "culture", "Robotics Engineer": "engineering", "Elektroniikkasuunnittelija": "engineering",
            "Vastaava työnjohtaja": "engineering", "Bioanalyytikko": "health", "Physiotherapist": "health",
            "Sosionomi, lastensuojelu": "health", "Logistics Coordinator": "business", "Kirjanpitäjä": "business",
        }
        for title, field in cases.items():
            self.assertIn(field, fields_of(title), title)

    def test_culture_avoids_common_words(self):
        self.assertNotIn("culture", fields_of("Part-time cashier", "Start in May. We value our work culture."))
        self.assertNotIn("culture", fields_of("Myyjä", "Meillä on hyvä työkulttuuri ja sosiaalisen median näkyvyys."))

    def test_known_word_collisions_stay_apart(self):
        self.assertNotIn("health", fields_of("Metsänhoitaja"))           # "hoitaja" inside a forestry job
        self.assertNotIn("business", fields_of("Metsätalousinsinööri"))  # "talous" inside a forestry job
        self.assertNotIn("business", fields_of("Puunhankintaesimies"))   # "hankinta" inside a forestry job
        self.assertNotIn("forestry", fields_of("Logistiikkakoordinaattori"))   # "gis" inside "logistiikka"
        self.assertNotIn("it", fields_of("Kirjanpitäjä", "Let it be known that we use Excel."))

    def test_broad_portals_need_a_title_word_or_a_core_word_in_the_ad(self):
        police = {"source": "Valtiolle", "title": "Korkeakouluharjoittelija",
                  "description": "Tutkinnassa käytetään poliisin tietojärjestelmiä ja pilvipalveluita."}
        developer = {"source": "Valtiolle", "title": "Korkeakouluharjoittelija",
                     "description": "Harjoittelu sisältää ohjelmistokehitystä Pythonilla."}
        self.assertNotIn("it", scraper.relevant_fields(police))
        self.assertIn("it", scraper.relevant_fields(developer))


class SourceTests(unittest.TestCase):
    def test_sources_json_is_consistent(self):
        readers = {"jobly", "metsalehti", "rss", "portal_feeds", "keyword_feeds", "links", "workday"}
        for source in scraper.SOURCES.values():
            self.assertIn(source["reader"], readers, source["id"])
            self.assertIn(source["kind"], {"general", "field_board", "broad_portal", "employer"}, source["id"])
            if isinstance(source["fields"], list):
                self.assertTrue(set(source["fields"]) <= set(PROFILES), source["id"])
            else:
                self.assertIn(source["fields"], {"all", "per-profile"}, source["id"])
        self.assertFalse(scraper.SOURCES["duunitori"]["enabled"])
        self.assertTrue(scraper.SOURCE_CONFIG["not_added"])

    def test_only_sources_for_the_chosen_fields_are_read(self):
        it_sources = [name for name, _ in scraper.sources(["it"])]
        self.assertNotIn("Metsälehti", it_sources)
        self.assertNotIn("Metsäkeskus", it_sources)
        self.assertIn("Valtiolle", it_sources)
        self.assertIn("Kuntarekry", it_sources)
        self.assertIn("Metsälehti", [name for name, _ in scraper.sources(["forestry"])])

    def test_jobly_pages_per_field(self):
        pages = scraper.jobly_pages(["health"])
        self.assertEqual([slug for _, slug, _ in pages], ["sairaanhoitaja", "lahihoitaja"])
        self.assertEqual({category for category, _, _ in pages}, {"Health"})
        self.assertIn("asentaja", [slug for _, slug, _ in scraper.jobly_pages([], personal=True)])


class ScrapeByFieldTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        data_dir = Path(self.temp_dir.name)
        for patcher in (patch.object(db, "DATA_DIR", data_dir), patch.object(db, "DB_FILE", data_dir / "jobdesk.db"),
                        patch.object(scraper.ROBOTS, "allowed", return_value=True),
                        patch.object(scraper.ROBOTS, "crawl_delay", return_value=None),
                        patch.object(scraper.time, "sleep")):
            patcher.start()
            self.addCleanup(patcher.stop)
        db.init()

    def test_active_fields_come_from_members_preferences(self):
        self.assertEqual(db.active_field_ids(["forestry"]), ["forestry"])
        db.update_user_preferences(1, {"fields": ["health", "it"]})
        self.assertEqual(scraper.active_field_ids(), ["it", "health"])

    def test_valtiolle_jobs_are_kept_for_the_chosen_field_with_its_category(self):
        feed = """<rss version="2.0"><channel>
          <item><title>Ohjelmistokehittäjä</title><link>https://valtiolle.fi/fi/tyopaikat/kehittaja-31/</link>
            <description>Kehität verkkopalveluja.</description></item>
          <item><title>Metsäasiantuntija</title><link>https://valtiolle.fi/fi/tyopaikat/metsa-32/</link>
            <description>Metsien hoito.</description></item>
          <item><title>Ulosottomies</title><link>https://valtiolle.fi/fi/tyopaikat/ulosotto-33/</link>
            <description>Ulosotto.</description></item>
        </channel></rss>"""

        def fetch(url):
            return feed if url in scraper.VALTIOLLE_FEEDS else "<rss version='2.0'><channel/></rss>"
        with patch.object(scraper, "fetch", side_effect=fetch), \
                patch.object(scraper, "fetch_workday_jobs", return_value=[]):
            scraper.run(field_ids=["it"])
        self.assertEqual({(job["title"], job["category"]) for job in db.list_jobs()},
                         {("Ohjelmistokehittäjä", "IT")})


class SkillsByFieldTests(unittest.TestCase):
    def test_what_to_study_uses_the_members_fields(self):
        jobs = [{"id": 1, "title": "Software Developer", "ad_text": "Python, SQL and Git.", "url": ""},
                {"id": 2, "title": "Backend Developer", "ad_text": "Python and AWS.", "url": ""}]
        cv = {"id": 1, "title": "My CV", "language": "en", "content": {"skills": "SQL"}}
        result = skills.analyse(jobs, [cv], [PROFILES["it"]])
        role = result["role_types"][0]
        self.assertEqual(role["id"], "it_dev")
        self.assertEqual([s["id"] for s in role["study"]], ["python"])
        self.assertEqual([s["id"] for s in role["have"]], ["sql"])


if __name__ == "__main__":
    unittest.main()
