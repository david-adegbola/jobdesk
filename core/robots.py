"""robots.txt checks for every page JobDesk reads automatically.

A site's robots.txt says which paths automated clients may read. RobotsCache downloads it once per
site (scheme + host), keeps it for CACHE_SECONDS and answers allowed(url) and crawl_delay(url).

What happens when robots.txt can't be read follows RFC 9309, with one conservative change:
  * 2xx          the rules in the file apply.
  * 401 or 403   everything is disallowed (the site restricts access; Python's own
                 urllib.robotparser does the same).
  * other 4xx    no robots.txt, so everything is allowed (e.g. 404).
  * 5xx, network error or no answer   everything is disallowed: a site that is down or
                 unreachable is not read until robots.txt can be checked again.

The download itself is done by a function passed in (fetch_text), so this module has no network
code of its own and tests can give it any answer.
"""

import threading
import time
from urllib import robotparser
from urllib.parse import urlsplit

USER_AGENT_TOKEN = "JobDesk"     # matched against the User-agent lines of robots.txt
CACHE_SECONDS = 6 * 60 * 60


class RobotsCache:
    def __init__(self, fetch_text, user_agent=USER_AGENT_TOKEN, ttl=CACHE_SECONDS, clock=time.time):
        """fetch_text(url) -> (status, text): status is the HTTP status code, or None when the
        site could not be reached at all."""
        self._fetch_text = fetch_text
        self.user_agent = user_agent
        self._ttl = ttl
        self._clock = clock
        self._cache = {}          # (scheme, host) -> (time read, RobotFileParser)
        self._lock = threading.Lock()

    def _parser(self, url):
        parts = urlsplit(url)
        key = (parts.scheme.lower(), parts.netloc.lower())
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._ttl:
                return cached[1]
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = robotparser.RobotFileParser(robots_url)
        try:
            status, text = self._fetch_text(robots_url)
        except Exception:         # the fetcher should not raise, but an unreachable site is never read
            status, text = None, ""
        if status is None or status >= 500 or status in (401, 403):
            parser.disallow_all = True
        elif status >= 400:
            parser.allow_all = True
        else:
            parser.parse((text or "").splitlines())
        with self._lock:
            self._cache[key] = (now, parser)
        return parser

    def allowed(self, url):
        """May JobDesk read this URL? Non-HTTP(S) URLs are never allowed."""
        if urlsplit(url).scheme.lower() not in {"http", "https"}:
            return False
        return self._parser(url).can_fetch(self.user_agent, url)

    def crawl_delay(self, url):
        """Seconds to wait between requests to this site, when robots.txt sets Crawl-delay; else None."""
        delay = self._parser(url).crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None
