import unittest
from datetime import date, timedelta
from unittest.mock import patch

import db
import server
import test_server     # the module, not the class: a test class imported here would run its tests twice


def ad(**changes):
    body = {
        "employer": "Esimerkki Oy", "contact_name": "Hiring Team", "contact_email": "jobs@example.test",
        "title": "Junior Data Analyst", "apply_url": "https://example.test/apply/1",
        "description": "Join our analytics team in Tampere. You will build dashboards and clean data with SQL. "
                       "Our working language is English.",
        "municipality_code": "837", "work_mode": "hybrid", "fields": ["it", "business"],
        "levels": ["entry"], "employment_types": ["full_time", "permanent"],
        "deadline": (date.today() + timedelta(days=30)).isoformat(), "start_date": "asap",
        "salary_min": 3000, "salary_max": 3600, "salary_period": "month", "lang_fi": "not_needed", "lang_en": "required",
        "consent": True,
    }
    body.update(changes)
    return body


class EmployerSubmissionTests(unittest.TestCase):
    setUp = test_server.JobApiTests.setUp
    stop_server = test_server.JobApiTests.stop_server
    request = test_server.JobApiTests.request
    last_link_token = test_server.JobApiTests.last_link_token
    sign_in_by_link = test_server.JobApiTests.sign_in_by_link
    member_cookie = test_server.JobApiTests.member_cookie
    choose_fields = test_server.JobApiTests.choose_fields

    def submit(self, body):
        return self.request("POST", "/api/employers/jobs", body, headers={"Cookie": ""})

    def test_employers_need_no_account_and_their_answers_are_checked(self):
        status, options = self.request("GET", "/api/employers/options", headers={"Cookie": ""})
        self.assertEqual(status, 200)
        self.assertEqual(len(options["municipalities"]), 308)
        self.assertIn("it", [f["id"] for f in options["fields"]])
        bad = [
            ({"employer": ""}, "employer"), ({"contact_email": "nope"}, "email"), ({"fields": []}, "career field"),
            ({"fields": ["astronomy"]}, "career fields"), ({"description": "Too short."}, "80 characters"),
            ({"apply_url": "call us"}, "web address"), ({"deadline": "2000-01-01"}, "12 months"),
            ({"municipality_code": "999"}, "town"), ({"salary_period": ""}, "per hour"),
            ({"salary_min": 4000, "salary_max": 3000}, "lower"), ({"consent": False}, "Confirm"),
            ({"levels": ["guru"]}, "levels"), ({"internship_credits": 99}, "Study credits"),
        ]
        for change, message in bad:
            status, error = self.submit(ad(**change))
            self.assertEqual(status, 400, change)
            self.assertIn(message, error["error"], change)
        self.assertEqual(db.list_submissions(), [])

    def test_an_approved_ad_is_listed_with_the_employers_answers_and_a_rejected_one_is_not(self):
        status, result = self.submit(ad())
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(self.submit(ad(title="Spam", website="http://spam.example"))[0], 200)   # honeypot: dropped
        self.submit(ad(title="Second ad"))
        pending = db.list_submissions("pending")
        self.assertEqual([s["data"]["title"] for s in pending], ["Second ad", "Junior Data Analyst"])

        member = self.member_cookie()
        self.choose_fields(member, ["it"])
        status, _ = self.request("GET", "/api/admin/submissions", headers=member)
        self.assertEqual(status, 403)
        status, _ = self.request("POST", f"/api/admin/submissions/{pending[1]['id']}", {"decision": "approve"},
                                 headers=member)
        self.assertEqual(status, 403)
        status, listing = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual(listing["jobs"], [])                         # nothing is listed before approval

        status, listed = self.request("GET", "/api/admin/submissions")
        self.assertEqual((status, len(listed["submissions"])), (200, 2))
        self.assertEqual(listed["submissions"][1]["data"]["municipality"], "Tampere")
        status, result = self.request("POST", f"/api/admin/submissions/{pending[1]['id']}", {"decision": "approve"})
        self.assertEqual(status, 200)
        status, _ = self.request("POST", f"/api/admin/submissions/{pending[0]['id']}",
                                 {"decision": "reject", "note": "Duplicate"})
        self.assertEqual(status, 200)
        status, _ = self.request("POST", f"/api/admin/submissions/{pending[1]['id']}", {"decision": "reject"})
        self.assertEqual(status, 409)

        status, listing = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual([j["title"] for j in listing["jobs"]], ["Junior Data Analyst"])
        job = listing["jobs"][0]
        self.assertEqual((job["source"], job["company"], job["location"]), ("Employer", "Esimerkki Oy", "Tampere"))
        self.assertEqual((job["municipality_code"], job["region_code"], job["work_mode"]), ("837", "06", "hybrid"))
        self.assertEqual((job["levels"], job["employment_types"]), (["entry"], ["full_time", "permanent"]))
        self.assertEqual((job["salary_min"], job["salary_max"], job["salary_period"]), (3000, 3600, "month"))
        self.assertEqual((job["start_date"], job["lang_fi"]), ("asap", "not_needed"))
        self.assertTrue(job["finnish_not_required"])
        self.assertEqual(job["url"], "https://example.test/apply/1")
        self.assertNotIn("contact_email", job)

    def test_ads_without_a_deadline_close_after_sixty_days_and_old_decisions_are_deleted(self):
        self.submit(ad(deadline="", apply_url="jobs@example.test"))
        submission = db.list_submissions("pending")[0]
        job_id = server.publish_submission(submission)
        job = db.get_job(job_id)
        self.assertEqual(job["deadline"], (date.today() + timedelta(days=server.EMPLOYER_LISTING_DAYS)).isoformat())
        self.assertIn("Apply by email: jobs@example.test", job["ad_text"])
        db.decide_submission(submission["id"], True, 1, job_id=job_id)
        later = (date.today() + timedelta(days=db.SUBMISSION_KEEP_DAYS + 1)).isoformat()
        self.assertEqual(db.purge_submissions(date.today().isoformat()), 0)
        self.assertEqual(db.purge_submissions(later), 1)
        self.assertEqual(db.list_submissions(), [])
        self.assertIsNotNone(db.get_job(job_id))                     # the listing itself stays

    def test_submissions_are_rate_limited(self):
        with patch.object(server, "SUBMIT_LIMIT_PER_IP", 2):
            self.assertEqual(self.submit(ad())[0], 200)
            self.assertEqual(self.submit(ad(contact_email="b@example.test"))[0], 200)
            self.assertEqual(self.submit(ad(contact_email="c@example.test"))[0], 429)


if __name__ == "__main__":
    unittest.main()
