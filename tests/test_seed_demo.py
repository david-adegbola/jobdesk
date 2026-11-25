import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
from core import jobmeta

SPEC = importlib.util.spec_from_file_location("seed_demo", Path(__file__).resolve().parent.parent / "scripts" / "seed_demo.py")
seed_demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_demo)


class SeedDemoTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_dir = Path(temp_dir.name)
        for p in (patch.object(db, "DATA_DIR", data_dir), patch.object(db, "DB_FILE", data_dir / "jobdesk.db"),
                  patch("builtins.print")):
            p.start()
            self.addCleanup(p.stop)

    def test_demo_jobs_cover_eight_fields_every_level_and_every_type(self):
        self.assertEqual(seed_demo.main([]), 0)
        jobs = db.list_jobs()
        self.assertEqual(len(jobs), len(seed_demo.JOBS))
        fields = {f for j in jobs for f in (j["field_ids"] or "").split(",") if f}
        self.assertGreaterEqual(len(fields), 8, fields)
        tags = [db.tags_of(j) for j in jobs]
        self.assertEqual({lvl for t in tags for lvl in t["levels"]}, set(jobmeta.LEVELS))
        self.assertEqual({e for t in tags for e in t["employment_types"]}, set(jobmeta.EMPLOYMENT_TYPES))
        self.assertEqual({j["work_mode"] for j in jobs} - {""}, set(jobmeta.WORK_MODES))
        self.assertTrue(any(jobmeta.finnish_not_required(j) for j in jobs))
        self.assertGreaterEqual(len({j["region_code"] for j in jobs} - {""}), 8)
        # A second run refreshes instead of adding, and --remove deletes them
        self.assertEqual(seed_demo.main([]), 0)
        self.assertEqual(len(db.list_jobs()), len(seed_demo.JOBS))
        self.assertEqual(seed_demo.main(["--remove"]), 0)
        self.assertEqual(db.list_jobs(), [])

    def test_it_refuses_a_database_with_real_jobs(self):
        db.init()
        db.upsert_scraped({"source": "Valtiolle", "external_id": "x", "url": "", "title": "Kirjanpitäjä",
                           "company": "", "location": "", "posted": "", "category": ""}, db.start_check(1))
        self.assertEqual(seed_demo.main([]), 1)
        self.assertEqual(seed_demo.main(["--force"]), 0)


if __name__ == "__main__":
    unittest.main()
