import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)
        for target, value in (
            (db, "DATA_DIR"),
            (db, "DB_FILE"),
        ):
            replacement = data_dir if value == "DATA_DIR" else data_dir / "jobdesk.db"
            patcher = patch.object(target, value, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        db.init()

    def add_job(self, user_id, external_id="shared-id"):
        return db.add_manual({
            "source": "Manual",
            "external_id": external_id,
            "title": f"Job for user {user_id}",
            "company": "Example employer",
            "location": "Finland",
        }, user_id=user_id)

    def test_shared_jobs_keep_application_data_isolated_for_100_users(self):
        with db.connect() as conn:
            conn.executemany(
                "INSERT INTO users (id, name) VALUES (?, ?)",
                [(user_id, f"Test user {user_id}") for user_id in range(2, 101)],
            )

        jobs = {}
        for user_id in range(1, 101):
            job_id = self.add_job(user_id, f"shared-id-{user_id}")
            jobs[user_id] = job_id
            db.set_status(
                job_id,
                "Applied",
                defaults={"cv_role": f"role-{user_id}"},
                user_id=user_id,
            )

        for user_id, job_id in jobs.items():
            other_user = user_id % 100 + 1
            own_jobs = db.list_jobs(user_id)
            self.assertEqual(len(own_jobs), 100)
            self.assertIn(job_id, [job["id"] for job in own_jobs])
            self.assertEqual(db.get_job(job_id, user_id)["title"], f"Job for user {user_id}")
            self.assertEqual(db.get_job(job_id, other_user)["title"], f"Job for user {user_id}")

            application = db.get_application(job_id, user_id)
            self.assertEqual(application["status"], "Applied")
            self.assertEqual(application["cv_role"], f"role-{user_id}")
            self.assertIsNone(db.get_application(job_id, other_user))
            self.assertEqual([item["job_id"] for item in db.list_applications(user_id)], [job_id])

    def test_rejection_preserves_the_furthest_application_stage(self):
        job_id = self.add_job(1, "stage-test")
        db.set_status(job_id, "Applied")
        db.set_status(job_id, "Interview")
        db.set_status(job_id, "Rejected")

        application = db.get_application(job_id)
        self.assertEqual(application["status"], "Rejected")
        self.assertEqual(application["max_stage"], 3)
        self.assertTrue(application["date_applied"])

        with self.assertRaises(ValueError):
            db.set_status(job_id, "Unknown")

    def test_application_updates_require_the_owning_user(self):
        job_id = self.add_job(1, "ownership-test")
        application_id = db.set_status(job_id, "Saved")
        with self.assertRaises(KeyError):
            db.update_application(application_id, {"notes": "wrong user"}, user_id=2)

    def test_cv_deletion_clears_only_the_owner_application_reference(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO users (id, name) VALUES (2, 'Second user')")
        cv_id = db.save_cv(1, "Forest CV", "en", {"full_name": "Owner"})
        first_job = self.add_job(1, "cv-ref-1")
        second_job = self.add_job(2, "cv-ref-2")
        db.set_status(first_job, "Applied", {"cv_role": f"cv-{cv_id}"}, user_id=1)
        db.set_status(second_job, "Saved", {"cv_role": f"cv-{cv_id}"}, user_id=2)

        db.delete_cv(cv_id, 1)

        self.assertEqual(db.get_application(first_job, 1)["cv_role"], "")
        self.assertEqual(db.get_application(second_job, 2)["cv_role"], f"cv-{cv_id}")
        self.assertIsNone(db.get_cv(cv_id, 1))

    def test_news_reading_state_defaults_private_for_new_accounts(self):
        db.upsert_news_item({
            "source_id": "test", "source": "Test", "external_id": "news-1",
            "url": "https://example.test/news", "title": "Forest research",
            "summary": "", "published_at": "", "category": "Research",
            "region": "Finland", "relevance": 1, "matched_topics": "",
        })
        item = db.list_news(1)[0]
        db.update_news_state(item["id"], {"is_saved": True}, 1)
        self.assertEqual(db.list_news(1)[0]["is_saved"], 1)
        self.assertEqual(db.list_news(2)[0]["is_saved"], 0)

    def test_init_migrates_legacy_owner_account(self):
        legacy_dir = Path(self.temp_dir.name) / "legacy"
        legacy_dir.mkdir()
        legacy_file = legacy_dir / "jobdesk.db"
        with sqlite3.connect(legacy_file) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            conn.execute("INSERT INTO users (id, name) VALUES (1, 'Existing owner')")

        with patch.object(db, "DATA_DIR", legacy_dir), patch.object(db, "DB_FILE", legacy_file):
            db.init()
            owner = db.get_user(1)

        self.assertEqual(owner["name"], "Existing owner")
        self.assertTrue(owner["is_admin"])
        self.assertEqual(owner["preferences_json"], "{}")


if __name__ == "__main__":
    unittest.main()
