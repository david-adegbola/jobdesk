import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import db
import auth
import server


class JobApiTests(unittest.TestCase):
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
        db.provision_admin("admin@example.test", auth.hash_password("administrator-password"))
        token, _ = auth.new_session(1)
        self.cookie = f"jobdesk_session={token}"

        self.context_patch = patch.object(server, "context", return_value=({}, None, []))
        self.context_patch.start()
        self.addCleanup(self.context_patch.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None, include_headers=False):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = {"Cookie": self.cookie}
        request_headers.update(headers or {})
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        result = response.read()
        status = response.status
        response_headers = dict(response.getheaders())
        connection.close()
        result = json.loads(result) if result and "application/json" in response_headers.get("Content-Type", "") else result
        return (status, result, response_headers) if include_headers else (status, result)

    def test_manual_job_creation_and_listing(self):
        status, created = self.request(
            "POST",
            "/api/jobs",
            {
                "title": "Forest data analyst",
                "company": "Example forestry employer",
                "location": "Joensuu",
                "ad_text": "Remote sensing and forest bioeconomy experience.",
            },
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertGreater(created["id"], 0)

        status, listing = self.request("GET", "/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["jobs"]), 1)
        self.assertEqual(listing["jobs"][0]["title"], "Forest data analyst")
        self.assertNotIn("contact_phone", listing["jobs"][0])

    def member_cookie(self):
        invite = "member-invitation-code"
        db.create_invitation(1, invite, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        status, _, headers = self.request("POST", "/api/auth/register", {
            "name": "Forest Student", "email": "member@example.test",
            "password": "a-very-long-password", "invite": invite,
        }, headers={"Cookie": ""}, include_headers=True)
        self.assertEqual(status, 200)
        return {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}

    def test_members_cannot_add_non_forestry_jobs(self):
        status, error = self.request("POST", "/api/jobs", {
            "title": "Warehouse worker", "company": "Example employer",
        }, headers=self.member_cookie())
        self.assertEqual(status, 400)
        self.assertIn("Only forestry", error["error"])
        self.assertEqual(db.list_jobs(), [])

    def test_admin_personal_jobs_are_hidden_from_members(self):
        status, created = self.request("POST", "/api/jobs", {
            "title": "Varastotyöntekijä", "company": "Example employer",
        })
        self.assertEqual(status, 200)
        db.upsert_scraped({"source": "Jobly", "external_id": "1", "url": "", "title": "Asentaja",
                           "company": "", "location": "", "posted": "", "category": "Industrial"}, None)
        db.upsert_scraped({"source": "Jobly", "external_id": "2", "url": "", "title": "Metsuri",
                           "company": "", "location": "", "posted": "", "category": "Forestry"}, None)

        status, admin_view = self.request("GET", "/api/jobs")
        self.assertEqual(status, 200)
        personal = {job["title"]: job["category"] for job in admin_view["jobs"] if job["personal"]}
        self.assertEqual(personal, {"Varastotyöntekijä": "Warehouse", "Asentaja": "Industrial"})

        member = self.member_cookie()
        status, member_view = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual([job["title"] for job in member_view["jobs"]], ["Metsuri"])
        status, state = self.request("GET", "/api/state", headers=member)
        self.assertEqual(state["job_types"], ["Forestry"])
        status, _ = self.request("POST", f"/api/jobs/{created['id']}/status", {"status": "Saved"},
                                 headers=member)
        self.assertEqual(status, 404)

    def test_skills_page_uses_only_jobs_the_member_can_see(self):
        db.upsert_scraped({"source": "Jobly", "external_id": "1", "url": "", "title": "Asentaja",
                           "company": "", "location": "", "posted": "", "category": "Industrial",
                           "description": "Hitsaus"}, None)
        db.upsert_scraped({"source": "Jobly", "external_id": "2", "url": "", "title": "Metsäasiantuntija",
                           "company": "", "location": "", "posted": "", "category": "Forestry",
                           "description": "Puukauppa metsänomistajien kanssa"}, None)
        status, admin = self.request("GET", "/api/skills")
        self.assertEqual([r["id"] for r in admin["role_types"]], ["forest_specialist", "personal-industrial"])

        member = self.member_cookie()
        status, view = self.request("GET", "/api/skills", headers=member)
        self.assertEqual([r["id"] for r in view["role_types"]], ["forest_specialist"])
        status, _ = self.request("GET", "/api/skills/draft/personal-industrial", headers=member)
        self.assertEqual(status, 404)
        status, draft = self.request("GET", "/api/skills/draft/forest_specialist", headers=member)
        self.assertEqual(status, 200)
        self.assertEqual(draft["cv"]["content"]["target_role"], "Forest specialist")

    def test_protected_api_requires_an_account_session(self):
        status, error = self.request("GET", "/api/jobs", headers={"Cookie": ""})
        self.assertEqual(status, 401)
        self.assertIn("Sign in", error["error"])

    def test_api_rejects_non_object_request_bodies(self):
        for path in ("/api/auth/login", "/api/cvs", "/api/account/profile"):
            status, error = self.request("POST", path, [])
            self.assertEqual(status, 400, path)
            self.assertIn("error", error, path)

    def test_invitation_registration_and_password_login(self):
        invite = "single-use-invitation-code"
        db.create_invitation(1, invite, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        status, registered, headers = self.request("POST", "/api/auth/register", {
            "name": "Forest Student", "email": "student@example.test",
            "password": "a-very-long-password", "invite": invite,
        }, include_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(registered["user"]["email"], "student@example.test")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertTrue(db.get_user_by_email("student@example.test")["is_active"])

        status, logged_in, headers = self.request("POST", "/api/auth/login", {
            "email": "student@example.test", "password": "a-very-long-password",
        }, headers={"Cookie": ""}, include_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(logged_in["user"]["name"], "Forest Student")
        self.assertIn("jobdesk_session=", headers["Set-Cookie"])
        status, error = self.request("POST", "/api/auth/register", {
            "name": "Second Registration", "email": "second-student@example.test",
            "password": "a-very-long-password", "invite": invite,
        })
        self.assertEqual(status, 400)
        self.assertIn("invalid, expired or already used", error["error"])

    def test_password_change_revokes_old_sessions_and_export_is_private(self):
        status, exported, export_headers = self.request("GET", "/api/account/export", include_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(exported["account"]["email"], "admin@example.test")
        self.assertIn("attachment;", export_headers["Content-Disposition"])

        old_cookie = self.cookie
        status, result, headers = self.request("POST", "/api/account/password", {
            "current_password": "administrator-password",
            "new_password": "another-secure-password",
        }, include_headers=True)
        self.assertEqual(status, 200)
        new_cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(result["ok"], True)
        status, error = self.request("GET", "/api/jobs", headers={"Cookie": old_cookie})
        self.assertEqual(status, 401)
        status, result = self.request("GET", "/api/jobs", headers={"Cookie": new_cookie})
        self.assertEqual(status, 200)

    def test_cvs_and_applications_are_private_while_jobs_are_shared(self):
        job_id = db.add_manual({
            "source": "Community", "external_id": "shared-forestry-job",
            "title": "Forest researcher", "company": "Luke", "category": "Forestry",
        }, user_id=1)
        db.set_status(job_id, "Applied", user_id=1)
        invite = "second-account-invitation"
        db.create_invitation(1, invite, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        second_user = db.create_user("Second User", "second@example.test",
                                     auth.hash_password("second-user-password"), invite)
        token, _ = auth.new_session(second_user)
        headers = {"Cookie": f"jobdesk_session={token}"}

        status, shared = self.request("GET", "/api/jobs", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(shared["jobs"][0]["title"], "Forest researcher")
        self.assertEqual(shared["jobs"][0]["status"], "")
        status, applications = self.request("GET", "/api/applications", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(applications["applications"], [])

        cv = {"title": "Forestry CV", "language": "en", "content": {
            "full_name": "Second User", "skills": "Forest research",
            "hobbies": "Hiking",
        }}
        status, created = self.request("POST", "/api/cvs", cv, headers=headers)
        self.assertEqual(status, 200)
        status, matched = self.request("GET", "/api/jobs", headers=headers)
        self.assertEqual(status, 200)
        self.assertGreater(matched["jobs"][0]["match"]["score"], 0)
        self.assertEqual(matched["jobs"][0]["use_cv"], "Forestry CV")
        status, own_cvs = self.request("GET", "/api/cvs", headers=headers)
        self.assertEqual(len(own_cvs["cvs"]), 1)
        self.assertEqual(own_cvs["cvs"][0]["id"], created["id"])
        self.assertEqual(own_cvs["cvs"][0]["content"]["hobbies"], "Hiking")
        status, other_cvs = self.request("GET", "/api/cvs", headers={"Cookie": self.cookie})
        self.assertEqual(other_cvs["cvs"], [])

        status, error = self.request("POST", f"/api/cvs/{created['id']}", cv,
                                     headers={"Cookie": self.cookie})
        self.assertEqual(status, 404)
        self.assertEqual(db.get_cv(created["id"], second_user)["content"]["full_name"], "Second User")

    def test_imported_cv_view_uses_original_pdf_and_stays_owner_private(self):
        cv_repo = Path(self.temp_dir.name) / "cv-repo"
        role_dir = cv_repo / "roles" / "forest-role"
        role_dir.mkdir(parents=True)
        (role_dir / "cv-en.tex").write_text(r"\cvrole{Forest analyst}", encoding="utf-8")
        (role_dir / "cv-en.pdf").write_bytes(b"%PDF original formatted CV")
        db.import_cv_for_admin(
            "roles/forest-role/cv-en.tex", "Forest analyst (English)", "en",
            {"full_name": "Admin"},
        )
        patcher = patch.object(server.config, "CV_REPO", cv_repo)
        patcher.start()
        self.addCleanup(patcher.stop)

        status, original_pdf, headers = self.request(
            "GET", "/api/cvs/1/original.pdf", include_headers=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(original_pdf, b"%PDF original formatted CV")
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertIn("inline;", headers["Content-Disposition"])

        with patch.object(server.cv_latex, "build_pdf") as build:
            status, formatted_pdf, headers = self.request(
                "GET", "/api/cvs/1/formatted.pdf", include_headers=True,
            )
        self.assertEqual(status, 200)
        self.assertEqual(formatted_pdf, b"%PDF original formatted CV")
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(
            headers["Content-Disposition"],
            'inline; filename="Forest-analyst-English.pdf"',
        )
        build.assert_not_called()

        status, latex_source, headers = self.request(
            "GET", "/api/cvs/1/source.tex", include_headers=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(latex_source, b"\\cvrole{Forest analyst}")
        self.assertIn("attachment;", headers["Content-Disposition"])

        invite = "original-cv-access-invitation"
        db.create_invitation(1, invite, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        second_user = db.create_user(
            "Second User", "second@example.test",
            auth.hash_password("second-user-password"), invite,
        )
        token, _ = auth.new_session(second_user)
        status, error = self.request(
            "GET", "/api/cvs/1/original.pdf",
            headers={"Cookie": f"jobdesk_session={token}"},
        )
        self.assertEqual(status, 404)
        self.assertIn("not available", error["error"])
        status, error = self.request(
            "GET", "/api/cvs/1/formatted.pdf",
            headers={"Cookie": f"jobdesk_session={token}"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(error["error"], "CV not found.")

    def test_imported_cv_view_compiles_original_tex_when_pdf_is_missing(self):
        cv_repo = Path(self.temp_dir.name) / "cv-repo"
        role_dir = cv_repo / "roles" / "forest-role"
        role_dir.mkdir(parents=True)
        (role_dir / "cv-en.tex").write_text(r"\cvrole{Forest analyst}", encoding="utf-8")
        db.import_cv_for_admin(
            "roles/forest-role/cv-en.tex", "Forest analyst (English)", "en",
            {"full_name": "Admin"},
        )
        patcher = patch.object(server.config, "CV_REPO", cv_repo)
        patcher.start()
        self.addCleanup(patcher.stop)

        with patch.object(server.cv_latex, "build_original_pdf", return_value=b"%PDF compiled original") as build:
            with patch.object(server.cv_latex, "build_pdf") as generated:
                status, pdf = self.request("GET", "/api/cvs/1/formatted.pdf")
                original_status, original_pdf = self.request("GET", "/api/cvs/1/original.pdf")
        self.assertEqual(status, 200)
        self.assertEqual(pdf, b"%PDF compiled original")
        self.assertEqual(original_status, 200)
        self.assertEqual(original_pdf, b"%PDF compiled original")
        build.assert_has_calls([
            unittest.mock.call((role_dir / "cv-en.tex").resolve()),
            unittest.mock.call((role_dir / "cv-en.tex").resolve()),
        ])
        generated.assert_not_called()

    def test_formatted_cv_pdf_is_generated_from_private_saved_cv(self):
        cv_id = db.save_cv(1, "Forestry CV", "en", {"full_name": "Admin"})
        with patch.object(server.cv_latex, "build_pdf", return_value=b"%PDF-built CV") as build:
            status, pdf, headers = self.request(
                "GET", f"/api/cvs/{cv_id}/formatted.pdf", include_headers=True,
            )
        self.assertEqual(status, 200)
        self.assertEqual(pdf, b"%PDF-built CV")
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="Forestry-CV.pdf"')
        build.assert_called_once()

        invite = "formatted-cv-private-invitation"
        db.create_invitation(1, invite, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        second_user = db.create_user(
            "Second User", "second@example.test",
            auth.hash_password("second-user-password"), invite,
        )
        token, _ = auth.new_session(second_user)
        status, error = self.request(
            "GET", f"/api/cvs/{cv_id}/formatted.pdf",
            headers={"Cookie": f"jobdesk_session={token}"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(error["error"], "CV not found.")

    def test_example_cv_can_be_viewed_and_copied_without_saving_it(self):
        status, response = self.request("GET", "/api/cvs/example")
        self.assertEqual(status, 200)
        example = response["cv"]
        self.assertEqual(example["content"]["full_name"], "Alex Example")
        self.assertEqual(db.list_cvs(1), [])

        with patch.object(server.cv_latex, "build_pdf", return_value=b"%PDF-example") as build:
            status, pdf, headers = self.request(
                "GET", "/api/cvs/example.pdf", include_headers=True,
            )
        self.assertEqual(status, 200)
        self.assertEqual(pdf, b"%PDF-example")
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(
            headers["Content-Disposition"],
            'inline; filename="Woodesk-CV-example.pdf"',
        )
        build.assert_called_once_with(example)
        self.assertEqual(db.list_cvs(1), [])

        status, error = self.request("GET", "/api/cvs/example.pdf", headers={"Cookie": ""})
        self.assertEqual(status, 401)
        self.assertIn("Sign in", error["error"])

    def test_formatted_cv_route_reports_missing_latex_runtime(self):
        cv_id = db.save_cv(1, "Forestry CV", "en", {"full_name": "Admin"})
        with patch.object(server.cv_latex, "build_pdf", side_effect=FileNotFoundError):
            status, error = self.request("GET", f"/api/cvs/{cv_id}/formatted.pdf")
        self.assertEqual(status, 503)
        self.assertIn("LaTeX packages", error["error"])

    def test_cross_site_job_creation_is_rejected(self):
        status, error = self.request(
            "POST",
            "/api/jobs",
            {"title": "Should not be saved", "category": "Other"},
            {
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
            },
        )
        self.assertEqual(status, 403)
        self.assertIn("Cross-site request refused", error["error"])
        self.assertEqual(db.list_jobs(), [])

    def test_news_api_returns_sources_and_persists_reading_list_state(self):
        item = {
            "source_id": "luke",
            "source": "Luke",
            "external_id": "https://example.fi/news/forest",
            "url": "https://example.fi/news/forest",
            "title": "Forest bioeconomy research",
            "summary": "New forest data research in Finland.",
            "published_at": "2026-11-02T10:00:00+00:00",
            "category": "Biotalous ja materiaalit",
            "region": "Suomi",
            "relevance": 50,
            "matched_topics": "Biotalous ja materiaalit, Data ja teknologia",
        }
        db.upsert_news_item(item)

        status, listing = self.request("GET", "/api/news")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["sources"]), 8)
        self.assertEqual(listing["items"][0]["title"], item["title"])
        self.assertIn("Finnish employers", listing["items"][0]["why_it_matters"])
        self.assertIn("process skills", listing["items"][0]["career_angle"])

        item_id = listing["items"][0]["id"]
        status, result = self.request("POST", f"/api/news/{item_id}/state", {"is_saved": True})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        status, listing = self.request("GET", "/api/news")
        self.assertEqual(status, 200)
        self.assertEqual(listing["items"][0]["is_saved"], 1)

        status, error = self.request("POST", f"/api/news/{item_id}/state", {"is_read": "yes"})
        self.assertEqual(status, 400)
        self.assertIn("boolean", error["error"])


if __name__ == "__main__":
    unittest.main()
