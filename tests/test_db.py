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

    def test_job_and_application_data_is_isolated_for_100_users(self):
        with db.connect() as conn:
            conn.executemany(
                "INSERT INTO users (id, name) VALUES (?, ?)",
                [(user_id, f"Test user {user_id}") for user_id in range(2, 101)],
            )

        jobs = {}
        for user_id in range(1, 101):
            job_id = self.add_job(user_id)
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
            self.assertEqual([job["id"] for job in own_jobs], [job_id])
            self.assertEqual(db.get_job(job_id, user_id)["title"], f"Job for user {user_id}")
            self.assertIsNone(db.get_job(job_id, other_user))

            application = db.get_application(job_id, user_id)
            self.assertEqual(application["status"], "Applied")
            self.assertEqual(application["cv_role"], f"role-{user_id}")
            self.assertIsNone(db.get_application(job_id, other_user))

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


if __name__ == "__main__":
    unittest.main()
