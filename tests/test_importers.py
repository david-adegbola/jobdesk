import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import scraper
import server
from core import importers

ENV = {"JOBDESK_TMT_API_URL": "https://api.example.test/ads", "JOBDESK_TMT_API_KEY": "test-key"}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_for(pages, seen=None):
    def opener(request, timeout=0):
        if seen is not None:
            seen.append(request)
        page = int(request.full_url.split("page=")[1].split("&")[0])
        return FakeResponse(json.dumps(pages[page] if page < len(pages) else []).encode("utf-8"))
    return opener


class TyomarkkinatoriAdapterTests(unittest.TestCase):
    def test_it_is_off_without_credentials_or_https(self):
        self.assertFalse(importers.TyomarkkinatoriAdapter({}).enabled())
        self.assertFalse(importers.TyomarkkinatoriAdapter({**ENV, "JOBDESK_TMT_API_KEY": ""}).enabled())
        self.assertFalse(importers.TyomarkkinatoriAdapter({**ENV, "JOBDESK_TMT_API_URL": "http://api.example.test"}).enabled())
        self.assertTrue(importers.TyomarkkinatoriAdapter(ENV).enabled())
        self.assertEqual(importers.enabled_adapters({}), [])

    def test_records_are_mapped_whatever_the_language_of_the_keys(self):
        posting = importers.TyomarkkinatoriAdapter.map_posting({
            "ilmoitusnumero": 123, "tehtavanimi": {"fi": "Sairaanhoitaja", "sv": "Sjukskötare"},
            "tyonantajanNimi": "Hyvinvointialue", "kunta": ["Kuopio"], "hakuPaattyy": "2027-01-31T15:00:00",
            "kuvausteksti": "Hoitotyötä.", "linkki": "javascript:alert(1)"})
        self.assertEqual(posting, {"id": "123", "title": "Sairaanhoitaja", "company": "Hyvinvointialue",
                                   "location": "Kuopio", "posted": "", "deadline": "2027-01-31",
                                   "description": "Hoitotyötä.", "url": ""})
        self.assertIsNone(importers.TyomarkkinatoriAdapter.map_posting({"title": "No id"}))

    def test_pages_are_read_with_the_key_until_a_short_page(self):
        importers.TyomarkkinatoriAdapter.PAGE_SIZE, old = 2, importers.TyomarkkinatoriAdapter.PAGE_SIZE
        self.addCleanup(setattr, importers.TyomarkkinatoriAdapter, "PAGE_SIZE", old)
        seen = []
        pages = [{"results": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]}, {"results": [{"id": 3, "title": "C"}]}]
        adapter = importers.TyomarkkinatoriAdapter(ENV, opener_for(pages, seen))
        self.assertEqual([p["id"] for p in adapter.read()], ["1", "2", "3"])
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer test-key")

    def test_an_unexpected_answer_is_an_error(self):
        adapter = importers.TyomarkkinatoriAdapter(ENV, opener_for([{"message": "unauthorised"}]))
        with self.assertRaises(importers.ImporterError):
            list(adapter.read())


class AdapterImportTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        data_dir = Path(temp_dir.name)
        for p in (patch.object(db, "DATA_DIR", data_dir), patch.object(db, "DB_FILE", data_dir / "jobdesk.db"),
                  patch.object(scraper, "fetch", return_value=None),
                  patch.object(scraper, "fetch_workday_jobs", return_value=[]),
                  patch.object(scraper.time, "sleep")):
            p.start()
            self.addCleanup(p.stop)
        db.init()

    def run_with(self, pages):
        adapter = importers.TyomarkkinatoriAdapter(ENV, opener_for(pages))
        with patch.object(scraper.core_importers, "enabled_adapters", return_value=[adapter]):
            return scraper.run()

    def test_adapter_postings_are_stored_with_fields_details_and_the_credit_line(self):
        result = self.run_with([[{"id": "t1", "title": "Sairaanhoitaja", "kunta": "Kuopio",
                                  "hakuPaattyy": "2099-01-31", "kuvausteksti": "Työ on vakituinen."}]])
        self.assertEqual((result["found"], result["new"], result["error"]), (1, 1, None))
        job = db.list_jobs()[0]
        self.assertEqual((job["source"], job["field_ids"], job["municipality_code"]), ("Työmarkkinatori", "health", "297"))
        self.assertEqual(job["deadline"], "2099-01-31")
        details = server.job_details(job)
        self.assertEqual(details["attribution"], "(Lähde: Työmarkkinatorin asiakastietojärjestelmä)")
        self.assertEqual(details["employment_types"], ["permanent"])

    def test_ads_deleted_from_the_api_are_closed_within_a_day_but_not_when_the_api_fails(self):
        self.run_with([[{"id": "t1", "title": "Sairaanhoitaja"}, {"id": "t2", "title": "Lähihoitaja"}]])
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET last_seen='2000-01-01'")
        result = self.run_with([{"error": "down"}])
        self.assertTrue(result["error"])
        self.assertEqual({j["listing_status"] for j in db.list_jobs()}, {"active"})
        self.run_with([[{"id": "t1", "title": "Sairaanhoitaja"}]])
        status = {j["external_id"]: j["listing_status"] for j in db.list_jobs()}
        self.assertEqual(status, {"t1": "active", "t2": "expired"})


if __name__ == "__main__":
    unittest.main()
