import unittest

from core.robots import RobotsCache

ROBOTS = """User-agent: *
Disallow: /api/
Crawl-delay: 10

User-agent: JobDesk
Disallow: /private/
"""


class RobotsCacheTests(unittest.TestCase):
    def cache(self, status, text="", clock=lambda: 0.0):
        self.calls = []

        def fetch(url):
            self.calls.append(url)
            return status, text
        return RobotsCache(fetch, clock=clock)

    def test_rules_for_jobdesk_apply(self):
        robots = self.cache(200, ROBOTS)
        self.assertTrue(robots.allowed("https://example.fi/tyopaikat/"))
        self.assertFalse(robots.allowed("https://example.fi/private/page"))
        self.assertEqual(self.calls, ["https://example.fi/robots.txt"])

    def test_generic_group_applies_when_no_group_names_jobdesk(self):
        robots = self.cache(200, "User-agent: *\nDisallow: /api/\nCrawl-delay: 10\n")
        self.assertFalse(robots.allowed("https://tyomarkkinatori.fi/api/jobs"))
        self.assertTrue(robots.allowed("https://tyomarkkinatori.fi/henkiloasiakkaat"))
        self.assertEqual(robots.crawl_delay("https://tyomarkkinatori.fi/"), 10.0)

    def test_missing_robots_txt_allows_everything(self):
        robots = self.cache(404)
        self.assertTrue(robots.allowed("https://example.fi/anything"))
        self.assertIsNone(robots.crawl_delay("https://example.fi/anything"))

    def test_unreachable_server_error_or_forbidden_disallows_everything(self):
        for status in (None, 500, 503, 401, 403):
            self.assertFalse(self.cache(status).allowed("https://example.fi/jobs"), status)

    def test_a_fetcher_that_raises_counts_as_unreachable(self):
        def broken(url):
            raise OSError("network down")
        self.assertFalse(RobotsCache(broken).allowed("https://example.fi/jobs"))

    def test_non_http_urls_are_never_allowed(self):
        robots = self.cache(404)
        self.assertFalse(robots.allowed("file:///etc/passwd"))
        self.assertEqual(self.calls, [])

    def test_robots_txt_is_cached_per_site_until_it_expires(self):
        now = [0.0]
        robots = self.cache(200, ROBOTS, clock=lambda: now[0])
        robots.allowed("https://example.fi/a")
        robots.allowed("https://example.fi/b")
        robots.allowed("https://other.fi/a")
        self.assertEqual(len(self.calls), 2)
        now[0] = 7 * 60 * 60          # past the six-hour cache
        robots.allowed("https://example.fi/c")
        self.assertEqual(len(self.calls), 3)


if __name__ == "__main__":
    unittest.main()
