"""Reading one job-ad page safely: public addresses only, robots.txt respected, honest User-Agent.

Moved here from scraper.py (which re-exports it) so the Flask app can fetch pasted ad URLs the same
way. Nothing here runs at import time.

  is_public_http_url(url)   True only for http(s) URLs whose host resolves to public IP addresses,
                            so a pasted URL can't make the server read its own network (SSRF).
  fetch_page(url, ...)      the HTML of one public page, or "" (same checks).
  fetch_ad_text(url, ...)   the visible text of one ad page, or "" when it can't or mustn't be read.
  fetch_status_text(url)    (status, text) for robots.txt files, used by core.robots.RobotsCache.
  user_agent()              the User-Agent JobDesk sends: it names JobDesk instead of a browser.
"""

import ipaddress
import os
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlsplit

PRODUCT = "JobDesk/1.0"
MAX_AD_CHARS = 20_000
MAX_BODY_BYTES = 2_000_000


def user_agent():
    """An honest User-Agent. JOBDESK_CONTACT_URL, when set, adds a page where site owners can reach
    whoever runs this copy of JobDesk."""
    contact = os.environ.get("JOBDESK_CONTACT_URL", "").strip()
    return f"{PRODUCT} (job-ad reader for students in Finland; low volume{'; +' + contact if contact else ''})"


class TextExtractor(HTMLParser):
    """Visible text of one ad page (for Match and Blockers), without scripts, styles and menus."""
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "svg", "form"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = " ".join(data.split())
            if t:
                self.parts.append(t)


def is_public_http_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = {ipaddress.ip_address(parsed.hostname)}
        except ValueError:
            addresses = {
                ipaddress.ip_address(result[4][0])
                for result in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
            }
        return bool(addresses) and all(address.is_global for address in addresses)
    except (OSError, ValueError, TypeError):
        return False


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to a public address that robots.txt also allows."""

    def __init__(self, allowed=None):
        super().__init__()
        self.allowed = allowed

    def redirect_request(self, request, response, code, message, headers, new_url):
        if not is_public_http_url(new_url):
            raise urllib.error.HTTPError(request.full_url, code, "Redirect to a non-public address refused.",
                                         headers, response)
        if self.allowed and not self.allowed(new_url):
            raise urllib.error.HTTPError(request.full_url, code, "Redirect target disallowed by robots.txt.",
                                         headers, response)
        return super().redirect_request(request, response, code, message, headers, new_url)


def _opener(context, allowed=None):
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                       PublicRedirectHandler(allowed))


def fetch_page(url, allowed, context=None, agent=None):
    """The HTML of a single public page, or '' if it can't or mustn't be read (same checks as below)."""
    if not is_public_http_url(url) or not allowed(url):
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": agent or user_agent(), "Accept-Language": "fi,en"})
    try:
        with _opener(context, allowed).open(req, timeout=15) as response:
            return response.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as error:
        print(f"  ! {url} -> {getattr(error, 'code', '')} {getattr(error, 'reason', error)}")
        return ""


def fetch_ad_text(url, allowed, context=None, agent=None, max_chars=MAX_AD_CHARS):
    """Visible text of a single ad page, or '' if it can't be read.

    allowed(url) -> bool is the robots.txt check (core.robots.RobotsCache.allowed); it is required,
    so no caller can forget it. context is an ssl.SSLContext (None = Python's default)."""
    body = fetch_page(url, allowed, context, agent)
    if not body:
        return ""
    parser = TextExtractor()
    parser.feed(body)
    return "\n".join(parser.parts)[:max_chars]


def fetch_status_text(url, context=None, agent=None):
    """(status, text) of a small text file such as robots.txt; status None when the site can't be reached."""
    if not is_public_http_url(url):
        return None, ""
    req = urllib.request.Request(url, headers={"User-Agent": agent or user_agent()})
    try:
        with _opener(context).open(req, timeout=15) as resp:
            return resp.status, resp.read(500_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError, ValueError):
        return None, ""
