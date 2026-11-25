import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import db
import scraper
from core import dedupe


class IsolatedDb(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_dir = Path(temp_dir.name)
        for p in (patch.object(db, "DATA_DIR", data_dir), patch.object(db, "DB_FILE", data_dir / "jobdesk.db")):
            p.start()
            self.addCleanup(p.stop)
        db.init()
        self.check = db.start_check(1)

    def add(self, source, external_id, title, company="", location="", url="", deadline=""):
        job = {"source": source, "external_id": external_id, "url": url, "title": title, "company": company,
               "location": location, "posted": "", "category": "", "description": ""}
        meta = scraper.job_meta(job)
        if deadline:
            meta["deadline"] = deadline
        return db.upsert_scraped(job, self.check, fields=["it"], meta=meta)

    def job(self, external_id):
        return next(j for j in db.list_jobs() if j["external_id"] == external_id)


class DedupeTests(IsolatedDb):
    def test_fingerprints_ignore_case_punctuation_gender_markers_and_company_forms(self):
        self.assertEqual(dedupe.fingerprint("Software Developer (m/f/d)", "Example Oy", "091"),
                         dedupe.fingerprint("software developer", "EXAMPLE", "091"))
        self.assertNotEqual(dedupe.fingerprint("Software Developer", "Example", "091"),
                            dedupe.fingerprint("Software Developer", "Example", "837"))
        self.assertEqual(dedupe.fingerprint("Developer"), "")          # too vague to merge anything

    def test_the_same_posting_from_a_second_source_is_not_listed_twice(self):
        self.assertTrue(self.add("Valtiolle", "v1", "Tietoasiantuntija", "Verohallinto", "Helsinki",
                                 "https://valtiolle.fi/fi/tyopaikat/123/?utm_source=rss"))
        # Same address written another way
        self.assertFalse(self.add("Kuntarekry", "k1", "Data specialist", "", "", "https://www.valtiolle.fi/fi/tyopaikat/123"))
        # Same title, employer and town, other address
        self.assertFalse(self.add("Metsähallitus", "m1", "Tietoasiantuntija", "Verohallinto Oy", "00100 Helsinki",
                                  "https://example.org/jobs/9"))
        # Same title elsewhere is another posting
        self.assertTrue(self.add("Metsähallitus", "m2", "Tietoasiantuntija", "Verohallinto", "Tampere",
                                 "https://example.org/jobs/10"))
        self.assertEqual(sorted(j["external_id"] for j in db.list_jobs()), ["m2", "v1"])


class ExpiryTests(IsolatedDb):
    def test_listings_close_after_their_deadline_or_when_gone_from_the_feed(self):
        today = date.today()
        self.add("Valtiolle", "past", "Kirjanpitäjä", deadline=(today - timedelta(days=1)).isoformat())
        self.add("Valtiolle", "open", "Sairaanhoitaja", deadline=(today + timedelta(days=5)).isoformat())
        self.add("Valtiolle", "gone", "Opettaja")
        self.add("Kuntarekry", "other", "Lähihoitaja")
        old = (today - timedelta(days=db.EXPIRE_AFTER_DAYS + 1)).isoformat()
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET last_seen=? WHERE external_id IN ('gone', 'other')", (old,))

        closed = db.expire_jobs(today.isoformat(), ["Valtiolle"])
        self.assertEqual(closed, 2)
        status = {j["external_id"]: j["listing_status"] for j in db.list_jobs()}
        self.assertEqual(status, {"past": "expired", "open": "active", "gone": "expired",
                                  "other": "active"})             # Kuntarekry wasn't read this time

        # Back in the feed: open again (unless the deadline has passed)
        self.add("Valtiolle", "gone", "Opettaja")
        self.add("Valtiolle", "past", "Kirjanpitäjä")
        self.assertEqual(self.job("gone")["listing_status"], "active")
        self.assertEqual(self.job("past")["listing_status"], "expired")

    def test_a_feed_that_returns_nothing_closes_nothing(self):
        self.add("Valtiolle", "v1", "Kirjanpitäjä")
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET last_seen='2000-01-01'")
        with patch.object(scraper, "fetch", return_value=None), patch.object(scraper.time, "sleep"), \
                patch.object(scraper, "fetch_workday_jobs", return_value=[]), patch("builtins.print"):
            scraper.run()
        self.assertEqual(self.job("v1")["listing_status"], "active")

    def test_listings_from_sources_no_longer_read_close_after_a_week(self):
        today = date.today()
        self.add("Jobly", "j-old", "Asentaja")
        self.add("Jobly", "j-new", "Metsuri")
        self.add("Valtiolle", "v1", "Kirjanpitäjä")
        old = (today - timedelta(days=db.EXPIRE_AFTER_DAYS + 1)).isoformat()
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET last_seen=? WHERE external_id IN ('j-old', 'v1')", (old,))
        app_job = self.job("j-old")["id"]
        db.set_status(app_job, "Applied", {}, 1)
        self.assertEqual(db.expire_jobs(today.isoformat(), read_now=["Valtiolle", "Kuntarekry"]), 1)
        status = {j["external_id"]: j["listing_status"] for j in db.list_jobs()}
        self.assertEqual(status, {"j-old": "expired", "j-new": "active", "v1": "active"})   # Valtiolle is read
        self.assertEqual(self.job("j-old")["status"], "Applied")                         # the tracker keeps it

    def test_members_own_saved_jobs_never_close(self):
        job_id = db.add_manual({"source": "Saved", "external_id": "private-1-x", "title": "Barista",
                                "deadline": "2000-01-01", "private": True}, 1)
        self.assertEqual(db.expire_jobs(date.today().isoformat(), ["Saved"]), 0)
        self.assertEqual(db.get_job(job_id)["listing_status"], "active")


if __name__ == "__main__":
    unittest.main()
