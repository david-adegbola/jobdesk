import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import db
from core import taxonomy as core_taxonomy

TAXONOMY = core_taxonomy.load(config.TAXONOMY_DIR)


class TaxonomyDataTests(unittest.TestCase):
    def test_fields_cover_every_career_area_with_names_in_english_and_finnish(self):
        ids = TAXONOMY.field_ids()
        self.assertTrue(15 <= len(ids) <= 25, len(ids))
        for expected in ("it", "health", "education", "business", "construction", "hospitality", "forestry"):
            self.assertIn(expected, ids)
        for field in TAXONOMY.fields:
            self.assertTrue(field["en"].strip() and field["fi"].strip(), field["id"])
        self.assertEqual(TAXONOMY.name("health", "fi"), TAXONOMY.by_id["health"]["fi"])
        self.assertEqual(TAXONOMY.name("unknown"), "unknown")

    def test_every_field_has_roles_and_every_role_recognises_its_own_names(self):
        fields_with_roles = {role["field"] for role in TAXONOMY.roles}
        self.assertEqual(set(TAXONOMY.field_ids()) - fields_with_roles, set())
        for role in TAXONOMY.roles:
            for language in ("en", "fi"):
                self.assertIn(role["id"], TAXONOMY.roles_for_title(role[language]), (role["id"], role[language]))

    def test_jobs_are_classified_by_title_category_and_profile(self):
        self.assertEqual(TAXONOMY.classify({"title": "Software Developer"}), ["it"])
        self.assertEqual(TAXONOMY.classify({"title": "Sairaanhoitaja"}), ["health"])
        self.assertEqual(TAXONOMY.classify({"title": "Varastotyöntekijä"}), ["logistics"])
        self.assertEqual(TAXONOMY.classify({"title": "Untitled", "category": "Forestry"}), ["forestry"])
        self.assertEqual(TAXONOMY.classify({"title": "Untitled", "category": " warehouse "}), ["logistics"])
        self.assertEqual(TAXONOMY.classify({"title": "Untitled"}, ["business", "astronomy"]), ["business"])
        self.assertEqual(TAXONOMY.classify({"title": "Untitled"}), [])
        # Several signals give several fields, always in display order
        both = TAXONOMY.classify({"title": "Software Developer", "category": "Forestry"})
        self.assertEqual(both, [f for f in TAXONOMY.field_ids() if f in {"it", "forestry"}])


class TaxonomyValidationTests(unittest.TestCase):
    def load_with(self, change):
        fields = json.loads((config.TAXONOMY_DIR / "fields.json").read_text(encoding="utf-8"))
        roles = json.loads((config.TAXONOMY_DIR / "roles.json").read_text(encoding="utf-8"))
        change(fields, roles)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "fields.json").write_text(json.dumps(fields), encoding="utf-8")
            (Path(directory) / "roles.json").write_text(json.dumps(roles), encoding="utf-8")
            return core_taxonomy.load(directory)

    def test_the_shipped_files_load_unchanged(self):
        self.assertEqual(self.load_with(lambda f, r: None).field_ids(), TAXONOMY.field_ids())

    def test_mistakes_are_refused_with_the_place_of_the_problem(self):
        cases = [
            (lambda f, r: f["fields"].append(dict(f["fields"][0])), "unique id"),
            (lambda f, r: f["fields"][0].pop("fi"), "'fi' name"),
            (lambda f, r: f["fields"][0].update(isco=["12345"]), "ISCO-08 codes"),
            (lambda f, r: f["fields"][0].update(order="first"), "order"),
            (lambda f, r: r["roles"][0].update(field="astronomy"), "isn't in fields.json"),
            (lambda f, r: r["roles"][0].update(isco="25"), "unit group"),
            (lambda f, r: r["roles"][0].update(esco="not a uri"), "ESCO"),
            (lambda f, r: r["roles"][0].update(title="(unclosed"), "invalid title pattern"),
            (lambda f, r: f.update(fields=[]), "no fields"),
        ]
        for change, message in cases:
            with self.assertRaisesRegex(core_taxonomy.TaxonomyError, message):
                self.load_with(change)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(core_taxonomy.TaxonomyError, "can't read"):
                core_taxonomy.load(directory)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.data_dir = Path(temp_dir.name)
        patches = [patch.object(db, "DATA_DIR", self.data_dir),
                   patch.object(db, "DB_FILE", self.data_dir / "jobdesk.db")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def make_old_database(self):
        """A database as the forestry-only version left it: no job_fields table, user_version 0."""
        conn = sqlite3.connect(db.DB_FILE)
        conn.executescript(db.SCHEMA)
        conn.execute("INSERT INTO users (id, name, is_admin) VALUES (1, 'Administrator', 1)")
        rows = [
            ("Metsälehti", "a1", "Metsuri", "Forestry"),
            ("Kuntarekry", "a2", "Sairaanhoitaja", ""),
            ("Jobly", "a3", "Warehouse worker", "Warehouse"),
            ("Community", "a4", "Kanttori", ""),
        ]
        for source, external_id, title, category in rows:
            conn.execute("""INSERT INTO jobs (source, external_id, title, category, first_seen, last_seen)
                            VALUES (?, ?, ?, ?, '2026-01-01', '2026-01-01')""", (source, external_id, title, category))
        conn.execute("""INSERT INTO jobs (source, external_id, title, location, ad_text, first_seen, last_seen)
                        VALUES ('Kuntarekry', 'a5', 'Kesätyöntekijä, kirjasto', 'Helsinki',
                                'Hakuaika päättyy 31.1.2027. Työ alkaa 1.6.2027. Palkkaus KVTES:n mukaan.',
                                '2026-01-01', '2026-01-01')""")
        job_id = conn.execute("SELECT id FROM jobs WHERE external_id='a1'").fetchone()[0]
        conn.execute("""INSERT INTO applications (job_id, status, status_changed_at, created_at, updated_at)
                        VALUES (?, 'Applied', '2026-01-02', '2026-01-02', '2026-01-02')""", (job_id,))
        conn.commit()
        conn.close()

    def counts(self):
        with db.connect() as conn:
            return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("users", "jobs", "applications")}

    def test_an_old_database_keeps_its_data_gets_a_backup_and_fields_for_every_job(self):
        self.make_old_database()
        before = self.counts()
        db.init()
        self.assertEqual(self.counts(), before)
        self.assertEqual(db.schema_version(), len(db.MIGRATIONS))
        backups = list((self.data_dir / "backups").glob("jobdesk-before-migration-1-*.db"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as copy:
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], before["jobs"])
            self.assertEqual(copy.execute("PRAGMA user_version").fetchone()[0], 0)

        fields = {job["external_id"]: scraper_fields(job) for job in db.list_jobs(1)}
        self.assertIn("forestry", fields["a1"])
        self.assertIn("health", fields["a2"])
        self.assertIn("logistics", fields["a3"])
        self.assertEqual(fields["a4"], [])                    # no field recognises it; kept, not deleted

        # Migration 2 read the details from each stored ad
        summer = next(job for job in db.list_jobs(1) if job["external_id"] == "a5")
        self.assertEqual((summer["municipality_code"], summer["region_code"]), ("091", "01"))
        self.assertEqual((summer["deadline"], summer["start_date"], summer["tes"]), ("2027-01-31", "2027-06-01", "KVTES"))
        self.assertEqual(summer["employer_sector"], "public")          # Kuntarekry is a public-sector source
        self.assertEqual(summer["listing_status"], "active")
        self.assertEqual(db.tags_of(summer)["employment_types"], ["summer"])

        # Running again changes nothing and makes no second backup
        self.assertEqual(db.migrate(), [])
        db.init()
        self.assertEqual(len(list((self.data_dir / "backups").glob("*.db"))), 1)

    def test_a_new_empty_database_is_created_at_the_latest_version_without_a_backup(self):
        db.init()
        self.assertEqual(db.schema_version(), len(db.MIGRATIONS))
        self.assertFalse((self.data_dir / "backups").exists())


def scraper_fields(job):
    return [f for f in (job.get("field_ids") or "").split(",") if f]


if __name__ == "__main__":
    unittest.main()
