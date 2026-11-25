import unittest
from unittest.mock import patch

import db
import scraper
import server
import test_server     # the module, not the class: a test class imported here would run its tests twice


class SavedSearchTests(unittest.TestCase):
    setUp_server = test_server.JobApiTests.setUp
    stop_server = test_server.JobApiTests.stop_server
    request = test_server.JobApiTests.request
    last_link_token = test_server.JobApiTests.last_link_token
    sign_in_by_link = test_server.JobApiTests.sign_in_by_link
    member_cookie = test_server.JobApiTests.member_cookie
    choose_fields = test_server.JobApiTests.choose_fields

    def setUp(self):
        self.setUp_server()
        self.check = db.start_check(1)
        self.add("old", "Sairaanhoitaja", "Kuopio", "Kesätyö sairaalassa.")     # before any search is saved
        self.member = self.member_cookie()
        server.mailer.OUTBOX.clear()

    def add(self, external_id, title, location, text, source="Kuntarekry"):
        job = {"source": source, "external_id": external_id, "url": f"https://example.test/{external_id}",
               "title": title, "company": "Esimerkin kaupunki", "location": location, "posted": "2026-11-20",
               "category": "", "description": text}
        db.upsert_scraped(job, self.check, fields=scraper.classify_job(job) or ["business"], meta=scraper.job_meta(job))

    def save(self, query, headers=None, **extra):
        return self.request("POST", "/api/searches", {"query": query, **extra}, headers=headers or self.member)

    def test_members_save_rename_switch_and_delete_their_own_searches(self):
        status, result = self.save("type=summer&q=hoitaja&page=3")
        self.assertEqual(status, 200)
        saved = result["searches"][0]
        self.assertEqual(saved["query"], "q=hoitaja&type=summer")                # page dropped, one order
        self.assertEqual(saved["name"], 'Summer jobs in Finland matching "hoitaja"')
        self.assertEqual(saved["alerts"], 1)
        self.assertEqual(self.save("q=hoitaja&type=summer")[0], 400)             # the same search twice
        status, result = self.request("POST", f"/api/searches/{saved['id']}", {"name": "Hoitajan kesätyöt", "alerts": False},
                                      headers=self.member)
        self.assertEqual((status, result["searches"][0]["name"], result["searches"][0]["alerts"]), (200, "Hoitajan kesätyöt", 0))
        # Another member can't see or change it
        other = self.sign_in_by_link("other@example.test", "Other Student")
        self.assertEqual(self.request("GET", "/api/searches", headers=other)[1]["searches"], [])
        self.assertEqual(self.request("POST", f"/api/searches/{saved['id']}/delete", {}, headers=other)[0], 404)
        self.assertEqual(self.request("POST", f"/api/searches/{saved['id']}", {"alerts": True}, headers=other)[0], 404)
        # Bad input and the limit
        self.assertEqual(self.request("POST", f"/api/searches/{saved['id']}", {"alerts": "yes"}, headers=self.member)[0], 400)
        for n in range(db.SAVED_SEARCH_LIMIT - 1):
            self.assertEqual(self.save(f"q=word{n}")[0], 200)
        status, error = self.save("q=onemore")
        self.assertEqual(status, 400)
        self.assertIn("up to", error["error"])
        status, result = self.request("POST", f"/api/searches/{saved['id']}/delete", {}, headers=self.member)
        self.assertEqual((status, len(result["searches"])), (200, db.SAVED_SEARCH_LIMIT - 1))

    def test_alerts_email_only_new_matching_jobs_once(self):
        self.save("type=summer")
        self.save("q=developer", alerts=False)
        self.assertEqual(server.send_search_alerts(), 0)                          # the old job isn't new
        self.add("new1", "Kesätyöntekijä, puisto", "Tampere", "Kesätyö puistossa.")
        self.add("new2", "Kirjanpitäjä", "Tampere", "Taloushallinto.")             # doesn't match
        self.add("new3", "Junior Developer", "Helsinki", "Python.")                 # matches the search without alerts
        self.assertEqual(server.send_search_alerts(), 1)
        mail = server.mailer.OUTBOX[-1]
        self.assertEqual((mail["to"], mail["subject"]), ("member@example.test", "1 new job for your saved searches"))
        self.assertIn("Kesätyöntekijä, puisto (Esimerkin kaupunki, Tampere)", mail["text"])
        new1 = next(j["id"] for j in db.list_jobs() if j["external_id"] == "new1")
        self.assertIn(f"/job/{new1}-kesatyontekija-puisto", mail["text"])          # the public job page
        self.assertIn("/#/jobs?type=summer", mail["text"])
        self.assertIn("Turn it off", mail["text"])
        for absent in ("Kirjanpitäjä", "Junior Developer", "Sairaanhoitaja"):
            self.assertNotIn(absent, mail["text"])
        self.assertEqual(server.send_search_alerts(), 0)                          # nothing new since
        self.assertEqual(len(server.mailer.OUTBOX), 1)

    def test_members_only_sources_link_to_the_original_and_failures_retry(self):
        self.save("field=health")
        self.add("tmt1", "Lähihoitaja", "Oulu", "Hoitotyö.", source="Työmarkkinatori")
        with patch.object(server.mailer, "send", side_effect=OSError("smtp down")), patch("builtins.print"):
            self.assertEqual(server.send_search_alerts(), 0)
        self.assertEqual(server.send_search_alerts(), 1)                          # tried again next time
        self.assertIn("https://example.test/tmt1", server.mailer.OUTBOX[-1]["text"])

    def test_the_job_check_sends_alerts_and_searches_go_with_the_account(self):
        self.save("type=summer")
        self.add("new1", "Kesätyöntekijä, puisto", "Tampere", "Kesätyö.")
        ok = {"found": 1, "new": 1, "error": None}
        with patch.object(server.scraper, "run_exclusive", return_value=ok), patch("builtins.print"):
            self.assertEqual(server.scheduled_job_check(), 0)
        self.assertEqual(len(server.mailer.OUTBOX), 1)
        status, export = self.request("GET", "/api/account/export", headers=self.member)
        self.assertEqual([s["query"] for s in export["saved_searches"]], ["type=summer"])
        member_id = db.get_user_by_email("member@example.test")["id"]
        db.delete_user(member_id)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
