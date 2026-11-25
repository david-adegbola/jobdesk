import http.client
import json
import re
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import db
import auth
import facts
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
        db.provision_admin("admin@example.test")
        for patcher in (patch.dict("os.environ", {"JOBDESK_EMAIL_BACKEND": "memory"}),
                        patch.dict(server.LINK_REQUESTS, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        server.mailer.OUTBOX.clear()
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

    def last_link_token(self):
        return re.search(r"token=([\w-]+)", server.mailer.OUTBOX[-1]["text"]).group(1)

    def sign_in_by_link(self, email, name="", invite=""):
        """The whole magic-link flow: ask for a link, read it from the (memory) outbox, open it."""
        status, _ = self.request("POST", "/api/auth/link", {"email": email, "name": name, "invite": invite},
                                 headers={"Cookie": ""})
        self.assertEqual(status, 200)
        status, _, headers = self.request("POST", "/api/auth/verify", {"token": self.last_link_token()},
                                          headers={"Cookie": ""}, include_headers=True)
        self.assertEqual(status, 200)
        return {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}

    def member_cookie(self):
        return self.sign_in_by_link("member@example.test", "Forest Student")

    def test_members_save_any_job_privately_but_share_only_their_fields(self):
        member = self.member_cookie()
        status, created = self.request("POST", "/api/jobs", {"title": "Warehouse worker", "company": "Example employer"},
                                       headers=member)
        self.assertEqual(status, 200)
        status, view = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual([(job["title"], job["private"]) for job in view["jobs"]], [("Warehouse worker", 1)])
        status, admin_view = self.request("GET", "/api/jobs")
        self.assertEqual(admin_view["jobs"], [])                                   # nobody else sees it
        self.choose_fields(member, ["forestry"])          # sharing is limited to the member's own fields
        status, error = self.request("POST", "/api/jobs", {"title": "Warehouse worker", "share": True}, headers=member)
        self.assertEqual(status, 400)
        self.assertIn("Only forestry", error["error"])

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
        self.assertEqual(personal, {"Asentaja": "Industrial"})
        self.assertTrue(next(j for j in admin_view["jobs"] if j["title"] == "Varastotyöntekijä")["private"])

        member = self.member_cookie()
        status, member_view = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual([job["title"] for job in member_view["jobs"]], ["Metsuri"])      # every field by default
        self.choose_fields(member, ["forestry"])
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

    def test_imported_cv_pairs_link_languages_and_drafts_use_the_chosen_one(self):
        en = db.import_cv_for_admin("roles/forestry-master/cv-en.tex", "Forestry Trainee", "en",
                                    {"target_role": "Forestry Trainee", "skills": "GIS: QGIS"})
        fi = db.import_cv_for_admin("roles/forestry-master/cv-fi.tex", "Metsäalan harjoittelija", "fi",
                                    {"target_role": "Metsäalan harjoittelija", "skills": "Paikkatieto: QGIS"})
        other = db.import_cv_for_admin("roles/warehouse-master/cv-en.tex", "Warehouse Worker", "en",
                                       {"target_role": "Warehouse Worker"})
        cvs = {cv["title"]: cv for cv in db.list_cvs(1)}
        en_id, fi_id = cvs["Forestry Trainee"]["id"], cvs["Metsäalan harjoittelija"]["id"]
        self.assertEqual(cvs["Forestry Trainee"]["versions"], {"en": en_id, "fi": fi_id})
        self.assertEqual(cvs["Warehouse Worker"]["versions"], {"en": cvs["Warehouse Worker"]["id"]})
        self.assertTrue(en and fi and other)

        db.upsert_scraped({"source": "Jobly", "external_id": "1", "url": "", "title": "Paikkatietoasiantuntija",
                           "company": "", "location": "", "posted": "", "category": "Forestry",
                           "description": "QGIS ja kaukokartoitus. Remote sensing."}, None)
        status, english = self.request("GET", "/api/skills/draft/gis_data/en")
        status, finnish = self.request("GET", "/api/skills/draft/gis_data/fi")
        self.assertEqual(english["cv"]["based_on"], "Forestry Trainee")
        self.assertTrue(english["cv"]["content"]["skills"].startswith("GIS: QGIS"))
        self.assertTrue(finnish["cv"]["content"]["skills"].startswith("Paikkatieto: QGIS"))
        self.assertEqual(finnish["cv"]["based_on"], "Metsäalan harjoittelija")
        self.assertEqual(finnish["cv"]["language"], "fi")
        self.assertEqual(finnish["cv"]["role_id"], "gis_data")

    def test_protected_api_requires_an_account_session(self):
        status, error = self.request("GET", "/api/jobs", headers={"Cookie": ""})
        self.assertEqual(status, 401)
        self.assertIn("Sign in", error["error"])

    def test_api_rejects_non_object_request_bodies(self):
        for path in ("/api/auth/link", "/api/cvs", "/api/account/fields"):
            status, error = self.request("POST", path, [])
            self.assertEqual(status, 400, path)
            self.assertIn("error", error, path)

    def test_magic_link_creates_an_account_and_signs_in_once(self):
        status, result = self.request("POST", "/api/auth/link", {"email": "Student@Example.test", "name": "Student"},
                                      headers={"Cookie": ""})
        self.assertEqual(status, 200)
        mail = server.mailer.OUTBOX[-1]
        self.assertEqual((mail["to"], mail["subject"]), ("student@example.test", "Create your JobDesk account"))
        self.assertIsNone(db.get_user_by_email("student@example.test"))      # nothing until the link is opened
        token = self.last_link_token()
        status, signed_in, headers = self.request("POST", "/api/auth/verify", {"token": token},
                                                  headers={"Cookie": ""}, include_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(signed_in["user"]["name"], "Student")
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        status, error = self.request("POST", "/api/auth/verify", {"token": token}, headers={"Cookie": ""})
        self.assertEqual(status, 400)                                         # a link works once
        self.assertIn("already used", error["error"])
        status, _ = self.request("POST", "/api/auth/link", {"email": "student@example.test"}, headers={"Cookie": ""})
        self.assertEqual(server.mailer.OUTBOX[-1]["subject"], "Your JobDesk sign-in link")

    def test_the_answer_does_not_reveal_whether_an_account_exists(self):
        _, unknown = self.request("POST", "/api/auth/link", {"email": "nobody@example.test"}, headers={"Cookie": ""})
        _, known = self.request("POST", "/api/auth/link", {"email": "admin@example.test"}, headers={"Cookie": ""})
        self.assertTrue(known["message"].startswith(server.SENT))
        self.assertTrue(unknown["message"].startswith(server.SENT))
        self.assertEqual([m["to"] for m in server.mailer.OUTBOX], ["admin@example.test"])   # only real accounts

    def test_expired_and_made_up_links_are_refused(self):
        db.create_login_link("an-expired-token-of-sufficient-length", "late@example.test", "Late", minutes=-1)
        for token in ("an-expired-token-of-sufficient-length", "x" * 40, 5, ""):
            status, _ = self.request("POST", "/api/auth/verify", {"token": token}, headers={"Cookie": ""})
            self.assertEqual(status, 400, token)

    def test_sign_in_emails_are_rate_limited(self):
        for _ in range(server.LINK_LIMIT_PER_EMAIL):
            self.request("POST", "/api/auth/link", {"email": "admin@example.test"}, headers={"Cookie": ""})
        status, error = self.request("POST", "/api/auth/link", {"email": "admin@example.test"}, headers={"Cookie": ""})
        self.assertEqual(status, 429)

    def test_rate_limits_use_the_address_caddy_adds_not_the_visitors_claim(self):
        class Fake:
            client_address = ("127.0.0.1", 1234)
            headers = {"X-Forwarded-For": "6.6.6.6, 203.0.113.9"}
        self.assertEqual(server.client_ip(Fake()), "203.0.113.9")
        Fake.client_address = ("198.51.100.4", 1234)                          # not behind Caddy: header ignored
        self.assertEqual(server.client_ip(Fake()), "198.51.100.4")

    def test_invitation_only_mode(self):
        codes, _ = server.create_invitations(1, 7)
        with patch.object(server.config, "OPEN_SIGNUP", False):
            _, result = self.request("POST", "/api/auth/link", {"email": "p1@example.test", "name": "P1"},
                                     headers={"Cookie": ""})
            self.assertEqual(server.mailer.OUTBOX, [])                         # no code, no link
            self.assertIn("invitation code", result["message"])
            member = self.sign_in_by_link("p1@example.test", "P1", invite=codes[0])
            status, _ = self.request("GET", "/api/state", headers=member)
            self.assertEqual(status, 200)
            self.request("POST", "/api/auth/link", {"email": "p2@example.test", "name": "P2", "invite": codes[0]},
                         headers={"Cookie": ""})
            status, error = self.request("POST", "/api/auth/verify", {"token": self.last_link_token()},
                                         headers={"Cookie": ""})
            self.assertEqual(status, 400)                                     # the code was used up
            self.assertIn("invitation", error["error"])

    def test_export_is_a_private_download_and_sign_out_ends_the_session(self):
        status, exported, export_headers = self.request("GET", "/api/account/export", include_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(exported["account"]["email"], "admin@example.test")
        self.assertIn("attachment;", export_headers["Content-Disposition"])
        self.request("POST", "/api/auth/logout", {})
        status, _ = self.request("GET", "/api/jobs")
        self.assertEqual(status, 401)

    def test_cvs_and_applications_are_private_while_jobs_are_shared(self):
        job_id = db.add_manual({
            "source": "Community", "external_id": "shared-forestry-job",
            "title": "Forest researcher", "company": "Luke", "category": "Forestry",
        }, user_id=1)
        db.set_status(job_id, "Applied", user_id=1)
        invite = "second-account-invitation"
        db.create_invitation(1, invite, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        second_user = db.create_user("Second User", "second@example.test")
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
        second_user = db.create_user("Second User", "second@example.test")
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
        with patch.object(server.cv_pdf, "compile_pdf", return_value=b"%PDF-built CV") as build:
            status, pdf, headers = self.request(
                "GET", f"/api/cvs/{cv_id}/formatted.pdf", include_headers=True,
            )
        self.assertEqual(status, 200)
        self.assertEqual(pdf, b"%PDF-built CV")
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="Admin_CV.pdf"')
        build.assert_called_once()

        invite = "formatted-cv-private-invitation"
        db.create_invitation(1, invite, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
        second_user = db.create_user("Second User", "second@example.test")
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

        with patch.object(server.cv_pdf, "compile_pdf", return_value=b"%PDF-example") as build:
            status, pdf, headers = self.request(
                "GET", "/api/cvs/example.pdf", include_headers=True,
            )
        self.assertEqual(status, 200)
        self.assertEqual(pdf, b"%PDF-example")
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(headers["Content-Disposition"], 'inline; filename="Example_CV.pdf"')
        build.assert_called_once_with(server.cv_pdf.render_tex(example))
        self.assertEqual(db.list_cvs(1), [])

        status, error = self.request("GET", "/api/cvs/example.pdf", headers={"Cookie": ""})
        self.assertEqual(status, 401)
        self.assertIn("Sign in", error["error"])

    def test_formatted_cv_route_reports_missing_latex_runtime(self):
        cv_id = db.save_cv(1, "Forestry CV", "en", {"full_name": "Admin"})
        with patch.object(server.cv_pdf, "compile_pdf", side_effect=FileNotFoundError):
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

    def test_news_desk_is_removed_but_saved_stories_stay_in_the_export(self):
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
        item_id = db.list_news(1)[0]["id"]
        db.update_news_state(item_id, {"is_saved": True}, 1)

        # The forestry News desk is gone; stories members saved earlier stay in their data export
        for method, path in (("GET", "/api/news"), ("POST", "/api/news/refresh"), ("GET", "/api/account/profile")):
            status, _ = self.request(method, path, {} if method == "POST" else None)
            self.assertEqual(status, 404, path)
        status, export = self.request("GET", "/api/account/export")
        self.assertEqual(status, 200)
        self.assertEqual([story["title"] for story in export["news_reading_list"]], [item["title"]])

    # ------------------------------------------------------------ Phase 1 fixes

    def test_prep_and_email_prompt_look_up_the_cv_by_slug_not_title(self):
        roles = [{"slug": "trainee-master", "title": "Trainee CV", "keywords": {"harjoi": "harjoittelija"},
                  "language": "fi-first", "langs": [], "footers": {}, "learn": set()}]
        db.upsert_scraped({"source": "Jobly", "external_id": "t1", "url": "", "title": "Harjoittelija",
                           "company": "", "location": "", "posted": "", "category": "Warehouse"}, None)
        job_id = db.list_jobs()[0]["id"]
        with patch.object(server, "context", return_value=({}, None, roles)):
            status, page = self.request("GET", f"/api/prep/{job_id}")
            self.assertEqual(status, 200)
            # With the title, prep.type_for missed and fell back to the Warehouse category
            self.assertEqual(page["type"], "trainee")
            status, analysis = self.request("POST", f"/api/email-prompt/{job_id}", {"analyse_only": True})
            self.assertEqual(status, 200)
            self.assertEqual(analysis["suggested_cv"], "trainee-master")

    def test_owner_routes_reject_bodies_that_are_not_objects(self):
        cases = [
            ("/api/email-prompt", []), ("/api/email-prompt/1", "text"), ("/api/email-prompt", {"job": "x"}),
            ("/api/prompt", []), ("/api/prompt", {"answers": ["yes"]}),
            ("/api/prep/answer", []), ("/api/prep/answer", {"type": ["trainee"], "id": "about"}),
        ]
        for path, body in cases:
            status, error = self.request("POST", path, body)
            self.assertEqual(status, 400, (path, body))
            self.assertIn("error", error, (path, body))

    def test_invalid_utf8_body_is_treated_as_empty_not_a_crash(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        # \x80 is not valid UTF-8: json.loads raises UnicodeDecodeError, which isn't a JSONDecodeError
        connection.request("POST", "/api/cvs", body=b'{"title": "\x80"}', headers={"Cookie": self.cookie})
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 400)

    def test_missing_facts_or_owner_profile_answer_503_instead_of_stopping(self):
        with patch.object(server, "context", side_effect=facts.FactsUnavailable("The CV facts file is missing.")):
            status, error = self.request("POST", "/api/prompt", {"job": {"title": "Metsuri"}, "analyse_only": True})
        self.assertEqual(status, 503)
        self.assertIn("facts", error["error"])

        missing = Path(self.temp_dir.name) / "no-profile.json"
        with patch.object(server.owner.config, "OWNER_PROFILE_FILE", missing):
            status, error = self.request("POST", "/api/prompt", {"job": {"title": "Metsuri"}, "answers": {}})
        self.assertEqual(status, 503)
        self.assertIn("owner", error["error"])

    # ------------------------------------------------------------ Phase 3: fields and Finnish level

    def choose_fields(self, headers, fields, level="none"):
        return self.request("POST", "/api/account/fields", {"fields": fields, "finnish_level": level}, headers=headers)

    def test_members_see_the_jobs_of_their_own_fields(self):
        db.add_manual({"source": "Community", "external_id": "c1", "title": "Ohjelmistokehittäjä",
                       "company": "Example", "category": "IT"}, user_id=1)
        db.add_manual({"source": "Community", "external_id": "c2", "title": "Metsäasiantuntija",
                       "company": "Example", "category": "Forestry"}, user_id=1)
        member = self.member_cookie()
        status, view = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual(sorted(job["title"] for job in view["jobs"]),                     # default: every field
                         ["Metsäasiantuntija", "Ohjelmistokehittäjä"])
        status, state = self.request("GET", "/api/state", headers=member)
        self.assertEqual(state["user_fields"], [f["id"] for f in state["fields"]])
        self.assertGreaterEqual(len(state["fields"]), 15)

        status, saved = self.choose_fields(member, ["it"], "basic")
        self.assertEqual(status, 200)
        self.assertEqual(saved, {"fields": ["it"], "finnish_level": "basic"})
        status, view = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual([(job["title"], job["category"]) for job in view["jobs"]], [("Ohjelmistokehittäjä", "IT")])
        status, state = self.request("GET", "/api/state", headers=member)
        self.assertEqual((state["user_fields"], state["job_types"], state["finnish_level"]), (["it"], ["IT"], "basic"))
        self.assertEqual(state["llm"]["mode"], "mock")
        self.assertIsNone(state["classify"])

    def test_personal_jobs_stay_private_even_when_they_match_a_members_field(self):
        db.upsert_scraped({"source": "Jobly", "external_id": "p1", "url": "", "title": "IT-tukihenkilö",
                           "company": "", "location": "", "posted": "", "category": "IT-Data centre"}, None)
        member = self.member_cookie()
        self.choose_fields(member, ["it"])
        status, view = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual(view["jobs"], [])
        status, admin_view = self.request("GET", "/api/jobs")
        self.assertTrue(admin_view["jobs"][0]["personal"])

    def test_sharing_a_job_needs_one_of_the_members_fields(self):
        member = self.member_cookie()
        self.choose_fields(member, ["forestry"])
        status, error = self.request("POST", "/api/jobs", {"title": "Kirjanpitäjä", "share": True}, headers=member)
        self.assertEqual(status, 400)
        self.assertIn("Only forestry", error["error"])
        self.choose_fields(member, ["forestry", "business"])
        status, created = self.request("POST", "/api/jobs", {"title": "Kirjanpitäjä", "share": True}, headers=member)
        self.assertEqual(status, 200)
        self.assertEqual(db.get_job(created["id"])["category"], "Business")

    def test_field_settings_are_validated(self):
        member = self.member_cookie()
        for body in ([], {"fields": [], "finnish_level": "none"}, {"fields": ["astronomy"], "finnish_level": "none"},
                     {"fields": ["it"], "finnish_level": "C1"}):
            status, _ = self.request("POST", "/api/account/fields", body, headers=member)
            self.assertEqual(status, 400, body)
        self.choose_fields(member, ["health"], "fluent")
        status, state = self.request("GET", "/api/state", headers=member)
        self.assertEqual((state["user_fields"], state["finnish_level"]), (["health"], "fluent"))

    def test_jobs_show_the_keyword_rule_until_an_llm_result_is_stored_for_the_same_text(self):
        job_id = db.add_manual({"source": "Community", "external_id": "f1", "title": "Metsäharjoittelija",
                                "ad_text": "Edellytämme sujuvaa suomen kielen taitoa.", "category": "Forestry"},
                               user_id=1)
        status, view = self.request("GET", "/api/jobs")
        self.assertEqual((view["jobs"][0]["finnish"]["level"], view["jobs"][0]["finnish"]["method"]),
                         ("required", "baseline_v1"))
        job = db.get_job(job_id)
        result = {"level": "preferred", "evidence": ["Edellytämme sujuvaa suomen kielen taitoa."],
                  "explanation_en": "x", "method": "llm", "model": "claude-opus-5-5",
                  "prompt_version": server.finnish.PROMPT_VERSION, "verified": True, "rejected_evidence": []}
        db.save_finnish_level(job_id, server._text_hash(server.finnish_text(job)), result)
        status, view = self.request("GET", "/api/jobs")
        self.assertEqual((view["jobs"][0]["finnish"]["level"], view["jobs"][0]["finnish"]["method"]), ("preferred", "llm"))
        db.update_job_ad_text(job_id, "Työkieli on englanti.")      # the ad changed: the stored result no longer applies
        status, view = self.request("GET", "/api/jobs")
        self.assertEqual(view["jobs"][0]["finnish"]["method"], "baseline_v1")

    def test_classification_is_admin_only_refused_in_mock_mode_and_stores_live_results(self):
        db.add_manual({"source": "Community", "external_id": "f2", "title": "Metsäharjoittelija",
                       "ad_text": "Työkieli on englanti.", "category": "Forestry"}, user_id=1)
        db.add_manual({"source": "Community", "external_id": "f3", "title": "Metsuri", "category": "Forestry"},
                      user_id=1)        # no ad text: not sent
        status, _ = self.request("POST", "/api/jobs/classify", {}, headers=self.member_cookie())
        self.assertEqual(status, 403)
        status, error = self.request("POST", "/api/jobs/classify", {})
        self.assertEqual(status, 400)
        self.assertIn("LLM is off", error["error"])

        sent = []

        def fake_classify(text, settings):
            sent.append(text)
            return {"level": "not_needed", "evidence": ["Työkieli on englanti."], "explanation_en": "x",
                    "method": "llm", "model": "claude-opus-5-5", "prompt_version": server.finnish.PROMPT_VERSION,
                    "verified": True, "rejected_evidence": []}
        live = server.llm.Settings(mode="live", api_key="test-key")
        with patch.object(server, "llm_settings", return_value=live), \
                patch.object(server.finnish, "classify", side_effect=fake_classify):
            status, started = self.request("POST", "/api/jobs/classify", {})
            self.assertEqual(status, 200)
            for _ in range(50):
                if not server.CLASSIFY["running"]:
                    break
                threading.Event().wait(0.05)
        self.assertEqual(sent, ["Metsäharjoittelija\nTyökieli on englanti."])
        self.assertEqual(server.CLASSIFY["result"], {"classified": 1, "failed": 0})
        status, view = self.request("GET", "/api/jobs")
        levels = {job["title"]: job["finnish"]["level"] for job in view["jobs"]}
        self.assertEqual(levels, {"Metsäharjoittelija": "not_needed", "Metsuri": "unclear"})

    # ------------------------------------------------------------ Phase 4: grounded drafting and opt-in

    def member_cv(self, headers):
        status, created = self.request("POST", "/api/cvs", {"title": "My CV", "language": "en", "content": {
            "full_name": "Forest Student", "email": "student@example.test",
            "experience": "May 2025--Aug 2025 — Field Assistant — Example Forest Research\nMeasured 40 sample plots.",
            "skills": "GIS: QGIS"}}, headers=headers)
        self.assertEqual(status, 200)
        return created["id"]

    def test_ai_opt_in_is_off_by_default_and_validated(self):
        member = self.member_cookie()
        status, state = self.request("GET", "/api/state", headers=member)
        self.assertFalse(state["llm_opt_in"])
        status, _ = self.request("POST", "/api/account/ai", {"llm_opt_in": "yes"}, headers=member)
        self.assertEqual(status, 400)
        status, saved = self.request("POST", "/api/account/ai", {"llm_opt_in": True}, headers=member)
        self.assertEqual(saved, {"llm_opt_in": True})
        status, state = self.request("GET", "/api/state", headers=member)
        self.assertTrue(state["llm_opt_in"])

    def test_mock_drafting_works_without_opt_in(self):
        member = self.member_cookie()
        cv_id = self.member_cv(member)
        status, result = self.request("POST", "/api/draft", {
            "cv_id": cv_id, "question": "Tell us about field work.", "ad_text": "Field trainee.",
            "word_limit": 80}, headers=member)
        self.assertEqual(status, 200)
        self.assertEqual(result["method"], "mock")
        self.assertTrue(result["sentences"])

    def test_live_drafting_needs_the_members_opt_in_and_sends_no_identity(self):
        member = self.member_cookie()
        cv_id = self.member_cv(member)
        sent = []

        def fake_call(system, user, schema, settings, max_tokens):
            sent.append(user)
            return {"data": {"sentences": [{"text": "I measured 40 sample plots.", "fact_ids": ["exp-1"]}]},
                    "model": "claude-opus-5-5", "usage": {}}
        live = server.llm.Settings(mode="live", api_key="test-key")
        body = {"cv_id": cv_id, "question": "Experience?", "ad_text": "Field trainee.", "word_limit": 80}
        with patch.object(server, "llm_settings", return_value=live), \
                patch.object(server.draft.llm, "call_json", side_effect=fake_call):
            status, error = self.request("POST", "/api/draft", body, headers=member)
            self.assertEqual(status, 403)
            self.assertIn("Account", error["error"])
            self.assertEqual(sent, [])
            self.request("POST", "/api/account/ai", {"llm_opt_in": True}, headers=member)
            status, result = self.request("POST", "/api/draft", body, headers=member)
        self.assertEqual(status, 200)
        self.assertEqual((result["method"], result["unsupported"]), ("llm", 0))
        self.assertEqual(len(sent), 1)
        self.assertNotIn("Forest Student", sent[0])
        self.assertNotIn("student@example.test", sent[0])

    def test_drafting_only_uses_the_members_own_cv_and_valid_input(self):
        member = self.member_cookie()
        cv_id = self.member_cv(member)
        status, _ = self.request("POST", "/api/draft", {"cv_id": cv_id, "question": "Q?", "word_limit": 80})
        self.assertEqual(status, 404)          # the administrator can't draft from a member's CV
        for body in ({"cv_id": True, "question": "Q?"}, {"cv_id": cv_id, "question": 5},
                     {"cv_id": cv_id, "question": "Q?", "word_limit": 3}, {"cv_id": cv_id, "question": "Q?", "job_id": "1"}):
            status, _ = self.request("POST", "/api/draft", body, headers=member)
            self.assertEqual(status, 400, body)

    # ------------------------------------------------------------ Pilot P2: shortlist

    ADS = ("Data intern\nWe use Python and SQL. Edellytämme sujuvaa suomen kielen taitoa.\n---\n"
           "Research assistant\nPython and statistics. Our working language is English.")

    def test_shortlist_ranks_pasted_ads_with_the_keyword_rule_in_mock_mode(self):
        status, result = self.request("POST", "/api/shortlist", {"ads_text": self.ADS, "skills": ["Python", "SQL"]})
        self.assertEqual(status, 200)
        self.assertEqual(result["method"], "baseline_v1")
        self.assertEqual([row["title"] for row in result["rows"]], ["Research assistant", "Data intern"])
        self.assertEqual(result["rows"][1]["finnish"]["level"], "required")
        self.assertIn("ad_text", result["rows"][0])

    def test_shortlist_validates_input_and_caps_the_batch(self):
        for body in ([], {"ads_text": 5}, {"ads_text": "x", "skills": "Python"}, {"ads_text": "x", "skills": ["a"] * 31}):
            status, _ = self.request("POST", "/api/shortlist", body)
            self.assertEqual(status, 400, body)
        many = "\n---\n".join(f"Ad {i}\nPython." for i in range(25))
        status, result = self.request("POST", "/api/shortlist", {"ads_text": many, "skills": []})
        self.assertEqual(len(result["rows"]), 20)
        self.assertIn("Only the first 20 ads", result["errors"][-1]["message"])
        status, result = self.request("POST", "/api/shortlist", {"ads_text": "  "})
        self.assertEqual((status, result["rows"]), (200, []))

    def test_shortlist_reads_links_through_the_safe_fetcher(self):
        with patch.object(server.scraper, "fetch_ad_text", side_effect=lambda url: "" if "blocked" in url else
                          "GIS intern\nWorking language is English.") as fetch:
            status, result = self.request("POST", "/api/shortlist", {
                "urls_text": "https://example.org/a\nhttps://blocked.example/b", "skills": ["GIS"]})
        self.assertEqual(status, 200)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([row["url"] for row in result["rows"]], ["https://example.org/a"])
        self.assertIn("Paste the ad text instead", result["errors"][0]["message"])

    JOB_PAGE = ('<html><head><title>x</title><script type="application/ld+json">{"@type": "JobPosting", '
                '"title": "GIS trainee", "hiringOrganization": {"name": "Example Oy"}, "validThrough": "2027-01-15", '
                '"jobLocation": {"address": {"addressLocality": "Tampere"}}, '
                '"description": "<p>Remote sensing and QGIS. English is the working language.</p>"}</script>'
                '</head><body>page</body></html>')

    def preview(self, url, page=None, robots=True, cookie=None):
        with patch.object(server.scraper, "is_public_http_url", return_value=True), \
                patch.object(server.scraper.ROBOTS, "allowed", return_value=robots), \
                patch.object(server.scraper, "fetch_page", return_value=self.JOB_PAGE if page is None else page) as fetch:
            result = self.request("POST", "/api/jobs/preview", {"url": url},
                                  headers=cookie)
        return (*result, fetch)

    def test_preview_reads_the_ads_structured_data_without_saving(self):
        status, found, fetch = self.preview("https://jobs.example.fi/gis")
        self.assertEqual(status, 200, found)
        self.assertTrue(found["readable"])
        self.assertEqual((found["title"], found["company"], found["location"], found["deadline"], found["method"]),
                         ("GIS trainee", "Example Oy", "Tampere", "2027-01-15", "jsonld"))
        self.assertIn("QGIS", found["ad_text"])
        fetch.assert_called_once_with("https://jobs.example.fi/gis")
        status, jobs = self.request("GET", "/api/jobs")
        self.assertEqual(jobs["jobs"], [])

    def test_preview_explains_when_a_page_cant_be_read(self):
        status, found, fetch = self.preview("https://jobs.example.fi/a", robots=False)
        self.assertEqual((status, found["readable"]), (200, False))
        self.assertIn("robots.txt", found["reason"])
        fetch.assert_not_called()
        status, found, _ = self.preview("https://jobs.example.fi/b", page="")
        self.assertFalse(found["readable"])
        self.assertIn("couldn't be read", found["reason"])
        status, found, _ = self.preview("https://jobs.example.fi/c", page="<html></html>")
        self.assertFalse(found["readable"])
        for bad in ("ftp://x.fi/a", "https://user:pw@x.fi/", "not a link", ""):
            self.assertEqual(self.preview(bad)[0], 400, bad)
        with patch.object(server.scraper, "is_public_http_url", return_value=False):
            status, error = self.request("POST", "/api/jobs/preview", {"url": "http://127.0.0.1/admin"})
        self.assertEqual(status, 400)

    def test_preview_is_rate_limited_per_member(self):
        with patch.object(server, "PREVIEW_LIMIT_PER_USER", 2):
            self.assertEqual(self.preview("https://jobs.example.fi/1")[0], 200)
            self.assertEqual(self.preview("https://jobs.example.fi/2")[0], 200)
            self.assertEqual(self.preview("https://jobs.example.fi/3")[0], 429)

    def test_the_same_link_written_differently_is_one_job(self):
        cookie = self.member_cookie()
        status, first = self.request("POST", "/api/jobs", {"url": "https://www.jobs.example.fi/gis/?utm_source=li",
                                                           "title": "GIS trainee"}, headers=cookie)
        self.assertEqual((status, first["existing"]), (200, False))
        status, found, fetch = self.preview("https://jobs.example.fi/gis#apply", cookie=cookie)
        self.assertFalse(found["readable"])
        self.assertEqual(found["duplicate"]["id"], first["id"])
        fetch.assert_not_called()
        status, again = self.request("POST", "/api/jobs", {"url": "http://jobs.example.fi/gis", "title": "GIS trainee",
                                                           "company": "Example Oy"}, headers=cookie)
        self.assertEqual((again["id"], again["existing"]), (first["id"], True))
        status, jobs = self.request("GET", "/api/jobs", headers=cookie)
        self.assertEqual([(j["id"], j["company"]) for j in jobs["jobs"]], [(first["id"], "Example Oy")])
        # Another member's copy is separate and private
        other = self.sign_in_by_link("other@example.test", "Other Student")
        status, theirs = self.request("POST", "/api/jobs", {"url": "https://jobs.example.fi/gis", "title": "GIS trainee"},
                                      headers=other)
        self.assertNotEqual(theirs["id"], first["id"])

    def test_adding_a_listed_job_saves_the_listing_instead_of_copying_it(self):
        cookie = self.member_cookie()
        db.upsert_scraped({"source": "Jobly", "external_id": "9", "url": "https://www.jobly.fi/tyopaikka/metsuri-9",
                           "title": "Metsuri", "company": "", "location": "", "posted": "", "category": "Forestry"}, None)
        status, jobs = self.request("GET", "/api/jobs", headers=cookie)
        listed = jobs["jobs"][0]
        self.assertFalse(listed["status"])
        status, found, _ = self.preview("https://jobly.fi/tyopaikka/metsuri-9?utm_campaign=x", cookie=cookie)
        self.assertIn("shared listings", found["reason"])
        status, added = self.request("POST", "/api/jobs", {"url": "https://jobly.fi/tyopaikka/metsuri-9",
                                                           "title": "Metsuri"}, headers=cookie)
        self.assertEqual((added["id"], added["existing"]), (listed["id"], True))
        status, jobs = self.request("GET", "/api/jobs", headers=cookie)
        self.assertEqual([(j["id"], j["status"]) for j in jobs["jobs"]], [(listed["id"], "Saved")])
        status, admin = self.request("GET", "/api/jobs")
        self.assertFalse(admin["jobs"][0]["status"])     # the status is the member's own

    FIT_AD = ("We are looking for a data analyst trainee. Experience with Python and SQL is required. "
              "Knowledge of Power BI is an advantage. English is the working language.")
    FIT_CV = {"full_name": "Forest Student", "email": "member@example.test", "skills": "Python, SQL, Excel",
              "experience": "2025: Research assistant — University; analysed survey data with Python"}

    def fit_setup(self, cv=True):
        """A member with a private job (and a CV); the queue runs only when the test says so."""
        for patcher in (patch.object(server.tasks, "start_worker"),):
            patcher.start()
            self.addCleanup(patcher.stop)
        cookie = self.member_cookie()
        member = db.get_user_by_email("member@example.test")
        cv_id = db.save_cv(member["id"], "My CV", "en", self.FIT_CV) if cv else None
        status, job = self.request("POST", "/api/jobs", {"title": "Data analyst trainee", "ad_text": self.FIT_AD,
                                                         "url": "https://jobs.example.fi/analyst"}, headers=cookie)
        return cookie, member, cv_id, job["id"]

    def test_shortlisting_queues_one_evaluation_and_then_reuses_it(self):
        cookie, member, cv_id, job_id = self.fit_setup()
        status, queued = self.request("POST", f"/api/jobs/{job_id}/evaluate", {"shortlist": True}, headers=cookie)
        self.assertEqual((status, queued["task"]["status"]), (200, "queued"))
        status, again = self.request("POST", f"/api/jobs/{job_id}/evaluate", {"shortlist": True}, headers=cookie)
        self.assertEqual(again["task"]["id"], queued["task"]["id"])          # the same task, not a second one
        status, waiting = self.request("GET", f"/api/jobs/{job_id}/fit", headers=cookie)
        self.assertEqual((waiting["evaluation"], waiting["task"]["status"]), (None, "queued"))
        server.tasks.run_pending()
        status, done = self.request("GET", f"/api/jobs/{job_id}/fit", headers=cookie)
        evaluation = done["evaluation"]
        self.assertIsNone(done["task"])
        self.assertEqual((evaluation["method"], evaluation["cv_id"], evaluation["stale"]), ("rules", cv_id, False))
        self.assertIn("Power BI", " ".join(g["requirement"] for g in evaluation["gaps"]))
        status, jobs = self.request("GET", "/api/jobs", headers=cookie)
        row = jobs["jobs"][0]
        self.assertEqual((row["status"], row["fit"]["suitability"], row["fit"]["stale"]),
                         ("Shortlisted", evaluation["suitability"], False))
        # Asking again: the stored evaluation comes back at once, nothing is queued
        status, cached = self.request("POST", f"/api/jobs/{job_id}/evaluate", {}, headers=cookie)
        self.assertEqual(cached["evaluation"]["created_at"], evaluation["created_at"])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 1)
        # Editing the CV makes the evaluation out of date; comparing again queues a new one
        db.save_cv(member["id"], "My CV", "en", {**self.FIT_CV, "skills": "Python, SQL, Power BI"}, cv_id)
        status, jobs = self.request("GET", "/api/jobs", headers=cookie)
        self.assertTrue(jobs["jobs"][0]["fit"]["stale"])
        status, requeued = self.request("POST", f"/api/jobs/{job_id}/evaluate", {}, headers=cookie)
        self.assertIn("task", requeued)
        server.tasks.run_pending()
        status, done = self.request("GET", f"/api/jobs/{job_id}/fit", headers=cookie)
        self.assertFalse(done["evaluation"]["stale"])
        self.assertNotIn("Power BI", " ".join(g["requirement"] for g in done["evaluation"]["gaps"]))
        # It is in the member's data export, and goes with the account
        status, export = self.request("GET", "/api/account/export", headers=cookie)
        self.assertEqual(len(export["fit_evaluations"]), 2)
        status, _ = self.request("POST", "/api/account/delete", {"confirm_email": "member@example.test"}, headers=cookie)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fit_evaluations").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_shortlist_without_a_cv_or_ad_text_explains_what_is_missing(self):
        cookie, member, _, job_id = self.fit_setup(cv=False)
        status, result = self.request("POST", f"/api/jobs/{job_id}/evaluate", {"shortlist": True}, headers=cookie)
        self.assertTrue(result["needs_cv"])
        status, jobs = self.request("GET", "/api/jobs", headers=cookie)
        self.assertEqual(jobs["jobs"][0]["status"], "Shortlisted")
        db.save_cv(member["id"], "My CV", "en", self.FIT_CV)
        status, bare = self.request("POST", "/api/jobs", {"title": "Mystery job"}, headers=cookie)
        status, result = self.request("POST", f"/api/jobs/{bare['id']}/evaluate", {}, headers=cookie)
        self.assertTrue(result["needs_text"])
        status, result = self.request("POST", f"/api/jobs/{job_id}/evaluate", {"cv_id": 9999}, headers=cookie)
        self.assertEqual(status, 404)
        status, result = self.request("POST", f"/api/jobs/{job_id}/evaluate", {"cv_id": True}, headers=cookie)
        self.assertEqual(status, 400)
        other = self.sign_in_by_link("other@example.test", "Other Student")
        status, _ = self.request("POST", f"/api/jobs/{job_id}/evaluate", {}, headers=other)
        self.assertEqual(status, 404)
        status, _ = self.request("GET", f"/api/jobs/{job_id}/fit", headers=other)
        self.assertEqual(status, 404)

    def test_a_later_status_is_kept_and_a_failed_task_says_why(self):
        cookie, member, cv_id, job_id = self.fit_setup()
        self.request("POST", f"/api/jobs/{job_id}/status", {"status": "Applied"}, headers=cookie)
        status, queued = self.request("POST", f"/api/jobs/{job_id}/evaluate", {"shortlist": True}, headers=cookie)
        status, jobs = self.request("GET", "/api/jobs", headers=cookie)
        self.assertEqual(jobs["jobs"][0]["status"], "Applied")
        db.delete_cv(cv_id, member["id"])
        server.tasks.run_pending()
        status, result = self.request("GET", f"/api/jobs/{job_id}/fit", headers=cookie)
        self.assertEqual(result["task"]["status"], "failed")
        self.assertIn("no longer exists", result["task"]["error"])

    def test_ai_comparison_needs_the_members_opt_in(self):
        cookie, member, cv_id, job_id = self.fit_setup()
        live = server.llm.Settings(mode="live", api_key="test-key")
        sent = []

        def fake(system, user, schema, settings, max_tokens=0):
            sent.append(user)
            return {"data": {"suitability": "possible", "summary": "s", "strengths": [], "gaps": [],
                             "recommendations": ["r"]}, "model": "m"}
        with patch.object(server, "llm_settings", return_value=live), patch.object(server.llm, "call_json", side_effect=fake), \
                patch.dict(server.SHORTLIST_USAGE, clear=True):
            self.request("POST", f"/api/jobs/{job_id}/evaluate", {}, headers=cookie)
            server.tasks.run_pending()
            status, result = self.request("GET", f"/api/jobs/{job_id}/fit", headers=cookie)
            self.assertEqual((result["evaluation"]["method"], sent), ("rules", []))
            status, _ = self.request("POST", "/api/account/ai", {"llm_opt_in": True}, headers=cookie)
            self.assertEqual(status, 200)
            self.request("POST", f"/api/jobs/{job_id}/evaluate", {}, headers=cookie)
            server.tasks.run_pending()
            status, result = self.request("GET", f"/api/jobs/{job_id}/fit", headers=cookie)
            self.assertEqual(result["evaluation"]["method"], "llm")
            self.assertEqual(len(sent), 1)
            self.assertNotIn("member@example.test", sent[0])
            self.assertNotIn("Forest Student", sent[0])
            self.assertEqual(sum(server.SHORTLIST_USAGE.values()), 1)

    def test_tasks_interrupted_by_a_restart_run_again(self):
        member = db.get_user(1)
        task_id, new = db.enqueue_task(1, "noop", "k", {})
        self.assertEqual(db.enqueue_task(1, "noop", "k", {}), (task_id, False))
        self.assertEqual(db.claim_task()["id"], task_id)
        self.assertIsNone(db.claim_task())
        self.assertEqual(db.requeue_interrupted_tasks(), 1)
        ran = []
        with patch.dict(server.tasks.HANDLERS, {"noop": lambda user_id, payload: ran.append(user_id)}):
            server.tasks.run_pending()
        self.assertEqual((ran, db.get_task(task_id, 1)["status"]), ([member["id"]], "done"))

    def prepare_setup(self):
        cookie, member, cv_id, job_id = self.fit_setup()
        db.save_cv(member["id"], "My CV", "en", {**self.FIT_CV, "phone": "+358 40 1"}, cv_id)
        return cookie, member, cv_id, job_id

    def test_master_profile_is_saved_and_checked(self):
        cookie, member, cv_id, job_id = self.prepare_setup()
        status, data = self.request("GET", "/api/prepare", headers=cookie)
        self.assertEqual((data["master_cv_id"], [j["id"] for j in data["jobs"]]), (cv_id, [job_id]))
        status, _ = self.request("POST", "/api/prepare/profile", {"master_cv_id": cv_id,
                                 "profile": {"available_from": " January  2027 ", "hours": ""}}, headers=cookie)
        self.assertEqual(status, 200)
        status, data = self.request("GET", "/api/prepare", headers=cookie)
        self.assertEqual((data["profile"]["available_from"], data["profile"]["hours"]), ("January 2027", ""))
        for bad in ({"profile": {"salary": "x"}}, {"profile": {"hours": "x" * 201}}, {"master_cv_id": 999},
                    {"profile": "x"}):
            status, _ = self.request("POST", "/api/prepare/profile", bad, headers=cookie)
            self.assertEqual(status, 400, bad)

    def test_preparing_writes_cv_letter_and_email_once_and_keeps_edits(self):
        cookie, member, cv_id, job_id = self.prepare_setup()
        body = {"languages": ["en", "fi"], "recipient": {"name": "Miisa Virtanen", "email": "jobs@example.fi"}}
        status, queued = self.request("POST", f"/api/prepare/{job_id}", body, headers=cookie)
        self.assertEqual((status, queued["task"]["status"]), (200, "queued"), queued)
        server.tasks.run_pending()
        status, data = self.request("GET", f"/api/prepare/{job_id}", headers=cookie)
        docs = {d["language"]: d for d in data["documents"]}
        self.assertEqual(sorted(docs), ["en", "fi"])
        en = docs["en"]
        self.assertEqual(en["letter"]["greeting"], "Hi Miisa,")
        self.assertEqual(en["email"]["to"], "jobs@example.fi")
        self.assertEqual(en["letter_file"], "Forest-Student-Cover-Letter-Data-analyst-trainee-EN.pdf")
        self.assertIsNotNone(en["tailored_cv"])
        self.assertIsNone(docs["fi"]["tailored_cv"])          # the CV is English: one tailored CV, in English
        status, cvs = self.request("GET", "/api/cvs", headers=cookie)
        self.assertEqual(len(cvs["cvs"]), 2)
        # The same request again: nothing to do, nothing queued
        status, again = self.request("POST", f"/api/prepare/{job_id}", body, headers=cookie)
        self.assertIn("documents", again)
        # Edits are saved and protected
        letter = {**en["letter"], "paragraphs": ["My own first paragraph."]}
        status, saved = self.request("POST", f"/api/documents/{en['id']}", {"letter": letter, "email": en["email"]},
                                     headers=cookie)
        self.assertEqual((status, saved["edited"], saved["letter"]["paragraphs"]), (200, True, ["My own first paragraph."]))
        status, text = self.request("GET", f"/api/documents/{en['id']}/letter.txt", headers=cookie)
        self.assertIn("My own first paragraph.", text.decode())
        self.assertTrue(text.decode().startswith("Forest Student\nData analyst trainee"))
        status, error = self.request("POST", f"/api/prepare/{job_id}", {**body, "recipient": {}}, headers=cookie)
        self.assertEqual(status, 409)
        status, queued = self.request("POST", f"/api/prepare/{job_id}", {**body, "recipient": {}, "replace_edited": True},
                                      headers=cookie)
        server.tasks.run_pending()
        status, data = self.request("GET", f"/api/prepare/{job_id}", headers=cookie)
        en = next(d for d in data["documents"] if d["language"] == "en")
        self.assertEqual((en["edited"], en["letter"]["greeting"]), (False, "Hello,"))
        status, cvs = self.request("GET", "/api/cvs", headers=cookie)
        self.assertEqual(len(cvs["cvs"]), 2)                  # the tailored CV was updated, not copied again
        # Export and account deletion cover the documents
        status, export = self.request("GET", "/api/account/export", headers=cookie)
        self.assertEqual(len(export["application_documents"]), 2)
        self.request("POST", "/api/account/delete", {"confirm_email": "member@example.test"}, headers=cookie)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 0)

    def test_prepare_validates_input_and_ownership(self):
        cookie, member, cv_id, job_id = self.prepare_setup()
        for bad in ({"languages": []}, {"languages": ["sv"]}, {"recipient": {"email": "not an address"}},
                    {"recipient": {"phone": "1"}}, {"cv_id": "1"}):
            status, _ = self.request("POST", f"/api/prepare/{job_id}", bad, headers=cookie)
            self.assertEqual(status, 400, bad)
        status, bare = self.request("POST", "/api/jobs", {"title": "Mystery job"}, headers=cookie)
        status, error = self.request("POST", f"/api/prepare/{bare['id']}", {}, headers=cookie)
        self.assertEqual(status, 400)
        self.request("POST", f"/api/prepare/{job_id}", {}, headers=cookie)
        server.tasks.run_pending()
        status, data = self.request("GET", f"/api/prepare/{job_id}", headers=cookie)
        doc_id = data["documents"][0]["id"]
        other = self.sign_in_by_link("other@example.test", "Other Student")
        for method, path in (("GET", f"/api/prepare/{job_id}"), ("GET", f"/api/documents/{doc_id}/letter.txt"),
                             ("POST", f"/api/documents/{doc_id}")):
            status, _ = self.request(method, path, {"letter": {}, "email": {}} if method == "POST" else None, headers=other)
            self.assertEqual(status, 404, path)
        status, _ = self.request("POST", f"/api/documents/{doc_id}",
                                 {"letter": {"paragraphs": ["x" * 7000]}, "email": {}}, headers=cookie)
        self.assertEqual(status, 400)
        with patch.object(server.cv_pdf, "build_letter", side_effect=FileNotFoundError):
            status, error = self.request("GET", f"/api/documents/{doc_id}/letter.pdf", headers=cookie)
        self.assertEqual(status, 503)

    def test_shortlist_live_mode_uses_the_ai_and_has_a_daily_limit(self):
        def fake(text, settings, call=None):
            return {"level": "not_needed", "evidence": [], "explanation_en": "x", "method": "llm", "model": "m",
                    "prompt_version": "v", "verified": True, "rejected_evidence": []}
        live = server.llm.Settings(mode="live", api_key="test-key")
        with patch.object(server, "llm_settings", return_value=live), \
                patch.object(server.finnish, "classify", side_effect=fake), \
                patch.object(server, "SHORTLIST_DAILY_LIMIT", 3), patch.dict(server.SHORTLIST_USAGE, clear=True):
            status, result = self.request("POST", "/api/shortlist", {"ads_text": self.ADS, "skills": []})
            self.assertEqual((status, result["method"]), (200, "llm"))
            status, error = self.request("POST", "/api/shortlist", {"ads_text": self.ADS, "skills": []})
            self.assertEqual(status, 429)
            self.assertIn("daily", error["error"])

    # ------------------------------------------------------------ Pilot P3: feedback and account deletion

    def test_finnish_feedback_is_validated_stored_and_summarised(self):
        member = self.member_cookie()
        good = {"level_shown": "required", "vote": "wrong", "correct_level": "preferred", "method": "llm",
                "evidence": "Suomen kielen taito katsotaan eduksi."}
        status, _ = self.request("POST", "/api/finnish/feedback", good, headers=member)
        self.assertEqual(status, 200)
        status, _ = self.request("POST", "/api/finnish/feedback",
                                 {"level_shown": "unclear", "vote": "right", "method": "baseline_v1"}, headers=member)
        self.assertEqual(status, 200)
        for bad in ([], {**good, "vote": "maybe"}, {**good, "level_shown": "x"}, {**good, "method": "guess"},
                    {**good, "correct_level": "fluent"}, {**good, "job_id": True}, {**good, "evidence": "x" * 2001}):
            status, _ = self.request("POST", "/api/finnish/feedback", bad, headers=member)
            self.assertEqual(status, 400, bad)
        status, _ = self.request("GET", "/api/finnish/feedback/summary", headers=member)
        self.assertEqual(status, 403)
        status, summary = self.request("GET", "/api/finnish/feedback/summary")
        self.assertEqual(summary["by_method"]["llm"], {"right": 0, "wrong": 1, "share_right": 0.0})
        self.assertEqual(summary["by_method"]["baseline_v1"]["share_right"], 1.0)

    def test_deleting_an_account_removes_personal_data_and_keeps_shared_ads(self):
        member = self.member_cookie()
        member_id = db.get_user_by_email("member@example.test")["id"]
        cv_id = self.member_cv(member)
        status, created = self.request("POST", "/api/jobs", {"title": "Metsäharjoittelija", "share": True},
                                       headers=member)
        db.set_status(created["id"], "Saved", user_id=member_id)
        status, mine = self.request("POST", "/api/jobs", {"title": "Kesätyö, oma"}, headers=member)
        self.request("POST", "/api/finnish/feedback", {"level_shown": "unclear", "vote": "right",
                                                       "method": "baseline_v1"}, headers=member)
        status, error = self.request("POST", "/api/account/delete", {"confirm_email": "someone@else.test"}, headers=member)
        self.assertEqual(status, 400)
        status, _, headers = self.request("POST", "/api/account/delete", {"confirm_email": "Member@Example.test"},
                                          headers=member, include_headers=True)
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertIsNone(db.get_user(member_id))
        self.assertIsNone(db.get_cv(cv_id, member_id))
        self.assertEqual(db.list_applications(member_id), [])
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM finnish_feedback").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (member_id,)).fetchone()[0], 0)
        self.assertEqual(db.get_job(created["id"])["user_id"], 1)       # the shared ad stays, owned by the admin
        self.assertIsNone(db.get_job(mine["id"]))                         # their private job is deleted
        status, _ = self.request("GET", "/api/jobs", headers=member)
        self.assertEqual(status, 401)

    def test_the_administrator_account_cannot_be_deleted(self):
        status, error = self.request("POST", "/api/account/delete", {"confirm_email": "admin@example.test"})
        self.assertEqual(status, 400)
        self.assertIn("administrator", error["error"])

    # ------------------------------------------------------------ Pilot P4: administration commands

    def test_bulk_invitations_respect_limits(self):
        codes, expires = server.create_invitations(3, 30)
        self.assertEqual(len(set(codes)), 3)
        self.assertGreater(expires, datetime.now(timezone.utc) + timedelta(days=29))
        for count, days in ((0, 7), (501, 7), (1, 0), (1, 121)):
            with self.assertRaises(ValueError):
                server.create_invitations(count, days)

    def test_end_of_pilot_deletion_has_a_dry_run_and_keeps_the_administrator(self):
        self.member_cookie()
        self.assertEqual(server.delete_member_accounts(), 1)              # dry run: nothing deleted
        self.assertIsNotNone(db.get_user_by_email("member@example.test"))
        self.assertEqual(server.delete_member_accounts(apply=True), 1)
        self.assertIsNone(db.get_user_by_email("member@example.test"))
        self.assertIsNotNone(db.get_user(1))

    def test_facts_load_raises_a_catchable_error(self):
        with patch.object(facts, "FACTS_FILE", Path(self.temp_dir.name) / "facts.json"), \
                patch("builtins.print"):
            with self.assertRaises(facts.FactsUnavailable) as caught:
                facts.load()
        self.assertNotIn(self.temp_dir.name, str(caught.exception))     # no server path in the message


if __name__ == "__main__":
    unittest.main()
