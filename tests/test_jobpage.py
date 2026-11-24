import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import jobpage  # noqa: E402


def page(*blocks, body="<p>Visible page text.</p>", head=""):
    scripts = "".join(f'<script type="application/ld+json">{b if isinstance(b, str) else json.dumps(b)}</script>'
                      for b in blocks)
    return f"<html><head><title>Page title | Site</title>{head}{scripts}</head><body>{body}</body></html>"


POSTING = {
    "@context": "https://schema.org", "@type": "JobPosting",
    "title": "Harjoittelija, paikkatieto",
    "hiringOrganization": {"@type": "Organization", "name": "Example Oy"},
    "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Helsinki", "addressCountry": "FI"}},
                    {"@type": "Place", "address": {"addressLocality": "Espoo"}}],
    "datePosted": "2026-11-02T08:00:00+02:00",
    "validThrough": "2026-12-01T23:59",
    "description": "<p>We need a GIS intern.</p><ul><li>Python</li><li>QGIS</li></ul>Suomen kielen taito on eduksi.",
}


class ExtractTests(unittest.TestCase):
    def test_reads_a_jobposting(self):
        found = jobpage.extract(page(POSTING))
        self.assertEqual(found["method"], "jsonld")
        self.assertEqual(found["title"], "Harjoittelija, paikkatieto")
        self.assertEqual(found["company"], "Example Oy")
        self.assertEqual(found["location"], "Helsinki, Espoo")
        self.assertEqual((found["posted"], found["deadline"]), ("2026-11-02", "2026-12-01"))
        self.assertIn("We need a GIS intern.", found["ad_text"])
        self.assertIn("QGIS", found["ad_text"])
        self.assertNotIn("<", found["ad_text"])

    def test_finds_the_posting_inside_a_graph_or_list_and_skips_bad_json(self):
        graph = {"@context": "https://schema.org",
                 "@graph": [{"@type": "WebPage", "name": "x"}, {**POSTING, "@type": ["JobPosting"]}]}
        for html in (page("{not json", graph), page([{"@type": "BreadcrumbList"}, POSTING])):
            self.assertEqual(jobpage.extract(html)["title"], "Harjoittelija, paikkatieto")

    def test_remote_jobs_and_string_organisations(self):
        found = jobpage.extract(page({"@type": "JobPosting", "title": "Developer", "hiringOrganization": "Firm",
                                      "jobLocationType": "TELECOMMUTE", "description": "Plain &amp; simple"}))
        self.assertEqual((found["company"], found["location"]), ("Firm", "Remote"))
        self.assertEqual(found["ad_text"], "Plain & simple")

    def test_without_structured_data_uses_the_page(self):
        found = jobpage.extract(page(head='<meta property="og:title" content="Summer trainee 2027">'
                                          '<meta property="og:site_name" content="Employer">',
                                     body="<nav>Menu</nav><h1>Other</h1><p>Apply by May.</p><script>x=1</script>"))
        self.assertEqual(found["method"], "page")
        self.assertEqual((found["title"], found["company"]), ("Summer trainee 2027", "Employer"))
        self.assertIn("Apply by May.", found["ad_text"])
        self.assertNotIn("Menu", found["ad_text"])
        self.assertNotIn("x=1", found["ad_text"])
        self.assertEqual(jobpage.extract(page(body="<h1>Heading <b>title</b></h1>"))["title"], "Heading title")
        self.assertEqual(jobpage.extract(page(body=""))["title"], "Page title | Site")

    def test_a_posting_without_a_title_falls_back_and_garbage_is_harmless(self):
        self.assertEqual(jobpage.extract(page({"@type": "JobPosting", "title": ""}))["method"], "page")
        self.assertEqual(jobpage.extract("")["title"], "")
        jobpage.extract("<<<>>><script type='application/ld+json'>")


class CanonicalUrlTests(unittest.TestCase):
    def test_the_same_job_written_differently_matches(self):
        same = ["https://www.Example.fi/jobs/123/?utm_source=x&gclid=1#apply",
                "http://example.fi/jobs/123",
                "https://example.fi/jobs/123?fbclid=abc"]
        self.assertEqual({jobpage.canonical_url(u) for u in same}, {"https://example.fi/jobs/123"})

    def test_meaningful_parameters_stay_and_are_ordered(self):
        self.assertEqual(jobpage.canonical_url("https://x.fi/job?b=2&id=7&utm_medium=m"), "https://x.fi/job?b=2&id=7")
        self.assertNotEqual(jobpage.canonical_url("https://x.fi/job?id=7"), jobpage.canonical_url("https://x.fi/job?id=8"))

    def test_non_web_addresses_give_nothing(self):
        for url in ("", "mailto:a@b.fi", "javascript:alert(1)", "not a url", "https://"):
            self.assertEqual(jobpage.canonical_url(url), "")


if __name__ == "__main__":
    unittest.main()
