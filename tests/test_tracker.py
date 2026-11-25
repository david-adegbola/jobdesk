import unittest
from datetime import date, timedelta

import db
import scraper
import server
import test_server     # the module, not the class: a test class imported here would run its tests twice


class TrackerTests(unittest.TestCase):
    setUp_server = test_server.JobApiTests.setUp
    stop_server = test_server.JobApiTests.stop_server
    request = test_server.JobApiTests.request

    def setUp(self):
        self.setUp_server()
        self.check = db.start_check(1)

    def tracked(self, external_id, title, location, deadline="", status="Saved"):
        job = {"source": "Valtiolle", "external_id": external_id, "url": f"https://example.test/{external_id}",
               "title": title, "company": "Metso", "location": location, "posted": "2026-11-01", "category": "",
               "description": "Long ad. " * 200}
        db.upsert_scraped(job, self.check, fields=["engineering"], meta={"deadline": deadline} if deadline else None)
        job_id = next(j["id"] for j in db.list_jobs() if j["external_id"] == external_id)
        db.set_status(job_id, status, {}, 1)
        return job_id

    def cards(self):
        status, data = self.request("GET", "/api/applications")
        self.assertEqual(status, 200)
        return {a["title"]: a for a in data["applications"]}, data

    def test_cards_show_town_deadline_state_and_only_real_ratings(self):
        past = (date.today() - timedelta(days=10)).isoformat()
        soon = (date.today() + timedelta(days=2)).isoformat()
        self.tracked("a", "Product Support Engineer", "West Perth WA 6005, Australia, Espoo")
        self.tracked("b", "Data Product Engineer", "Espoo, Krakova, Puola, Lappeenranta", deadline=past)
        self.tracked("c", "Application Specialist", "Espoo, Tampere", deadline=soon)
        db.save_cv(1, "CV", "en", {"full_name": "Admin", "skills": "engineer product support data application long ad"})
        cards, data = self.cards()
        a, b, c = cards["Product Support Engineer"], cards["Data Product Engineer"], cards["Application Specialist"]
        self.assertEqual((a["company"], a["town"], a["other_towns"], a["abroad"]), ("Metso", "Espoo", 0, True))
        self.assertEqual((b["town"], b["other_towns"], b["abroad"], b["closed"]), ("Espoo", 1, True, True))
        self.assertEqual((c["town"], c["other_towns"], c["abroad"], c["closing_soon"]), ("Espoo", 1, False, True))
        for card in cards.values():
            self.assertEqual(card["rating"], "")                 # no CV comparison yet: no badge, never a keyword 100
            self.assertNotIn("ad_text", card)
        self.assertEqual(data["preferences"], server.TRACKER_DEFAULTS)

    def test_view_settings_are_kept_per_member_and_checked(self):
        status, result = self.request("POST", "/api/account/tracker",
                                      {"collapsed": ["Offer"], "density": "compact", "sort": "added", "hide_closed": True})
        self.assertEqual(status, 200)
        _, data = self.cards()
        self.assertEqual(data["preferences"], {**server.TRACKER_DEFAULTS, "collapsed": ["Offer"], "density": "compact",
                                               "sort": "added", "hide_closed": True})
        for bad in ({"collapsed": ["Dreams"]}, {"density": "tiny"}, {"sort": "random"}, {"hide_closed": "yes"}, []):
            self.assertEqual(self.request("POST", "/api/account/tracker", bad)[0], 400, bad)
        # other preferences (fields) survive
        user = db.get_user(1)
        self.assertIn("tracker", server.user_preferences(user))


if __name__ == "__main__":
    unittest.main()
