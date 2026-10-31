import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import db
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

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        connection.request(method, path, body=payload, headers=headers or {})
        response = connection.getresponse()
        result = response.read()
        status = response.status
        connection.close()
        return status, json.loads(result) if result else None

    def test_manual_job_creation_and_listing(self):
        status, created = self.request(
            "POST",
            "/api/jobs",
            {
                "title": "Warehouse worker",
                "company": "Example employer",
                "location": "Joensuu",
                "category": "Other",
            },
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertGreater(created["id"], 0)

        status, listing = self.request("GET", "/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["jobs"]), 1)
        self.assertEqual(listing["jobs"][0]["title"], "Warehouse worker")

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


if __name__ == "__main__":
    unittest.main()
