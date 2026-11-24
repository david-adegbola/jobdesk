"""Reading the details of one job ad from its web page. Python standard library only.

Most job sites (and Google for Jobs) describe an ad with schema.org JobPosting data in a
<script type="application/ld+json"> block, so that is read first. When a page has none, the title
comes from og:title / <h1> / <title> and the description from the visible text.

  extract(html, url)   {"title", "company", "location", "deadline", "posted", "ad_text", "method"}
                       method is "jsonld" or "page" (no structured data: check the fields).
  canonical_url(url)   the same job's address written one way, for spotting duplicates: lower-case
                       host, no "www.", no #fragment, no tracking parameters, no trailing slash.
"""

import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from core.fetch import MAX_AD_CHARS, TextExtractor

TRACKING = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|mc_cid|mc_eid|_hs\w+|referrer|trk\w*|igshid|yclid)$", re.I)


def canonical_url(url):
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    host = host[4:] if host.startswith("www.") else host
    if parts.port and parts.port not in {80, 443}:
        host = f"{host}:{parts.port}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not TRACKING.match(k)))
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, query, ""))


class _PageParser(HTMLParser):
    """Collects JSON-LD blocks, meta tags, <title> and the first <h1>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jsonld, self.meta, self.title, self.h1 = [], {}, "", ""
        self._in = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and "ld+json" in a.get("type", "").lower():
            self._in, self._buf = "jsonld", []
        elif tag == "title" and not self.title:
            self._in, self._buf = "title", []
        elif tag == "h1" and not self.h1:
            self._in, self._buf = "h1", []
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and "content" in a:
                self.meta.setdefault(key, a["content"].strip())

    def handle_endtag(self, tag):
        if self._in and tag == {"jsonld": "script"}.get(self._in, self._in):
            text = "".join(self._buf).strip()
            if self._in == "jsonld":
                self.jsonld.append(text)
            elif self._in == "title":
                self.title = " ".join(text.split())
            else:
                self.h1 = " ".join(text.split())
            self._in = None

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)


def _walk(node):
    """Every dict inside a JSON-LD value (lists, @graph and nesting included)."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                yield from _walk(node[key])


def _is_posting(node):
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(isinstance(k, str) and k.split("/")[-1] == "JobPosting" for k in kinds)


def _text(value):
    """Plain text from a JSON-LD string that may hold HTML."""
    if isinstance(value, list):
        value = " ".join(str(v) for v in value if isinstance(v, (str, int, float)))
    if not isinstance(value, (str, int, float)):
        return ""
    value = str(value)
    if "<" in value:
        value = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", value)
        parser = TextExtractor()
        parser.feed(value)
        return "\n".join(parser.parts)
    return "\n".join(" ".join(line.split()) for line in unescape(value).splitlines() if line.strip())


def _name(value):
    if isinstance(value, list):
        return next((n for n in (_name(v) for v in value) if n), "")
    if isinstance(value, dict):
        return _text(value.get("name", ""))
    return _text(value)


def _place(value):
    places = value if isinstance(value, list) else [value]
    out = []
    for place in places:
        if not isinstance(place, dict):
            text = _text(place)
        else:
            address = place.get("address", place)
            if isinstance(address, dict):
                country = _name(address.get("addressCountry", ""))
                bits = [_text(address.get("addressLocality", "")), _text(address.get("addressRegion", ""))]
                bits = [b for b in bits if b] or ([country] if country else [])
                text = ", ".join(dict.fromkeys(bits))
            else:
                text = _text(address) or _name(place)
        if text and text not in out:
            out.append(text)
    return ", ".join(out)


def _date(value):
    match = re.match(r"\s*(\d{4}-\d{2}-\d{2})", value if isinstance(value, str) else "")
    return match.group(1) if match else ""


def _from_posting(node):
    location = _place(node.get("jobLocation", ""))
    if "TELECOMMUTE" in json.dumps(node.get("jobLocationType", "")).upper():
        location = ", ".join(x for x in (location, "Remote") if x)
    return {
        "title": _text(node.get("title") or node.get("name", ""))[:200],
        "company": _name(node.get("hiringOrganization", ""))[:200],
        "location": location[:200],
        "deadline": _date(node.get("validThrough", "")),
        "posted": _date(node.get("datePosted", "")),
        "ad_text": _text(node.get("description", ""))[:MAX_AD_CHARS],
    }


def extract(html, url=""):
    parser = _PageParser()
    try:
        parser.feed(html or "")
    except (AssertionError, ValueError):     # malformed markup: use what was read
        pass
    for block in parser.jsonld:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        posting = next((n for n in _walk(data) if _is_posting(n)), None)
        if posting:
            found = _from_posting(posting)
            if found["title"]:
                if not found["ad_text"]:
                    found["ad_text"] = _visible(html)
                return {**found, "method": "jsonld"}
    meta = parser.meta
    title = meta.get("og:title") or parser.h1 or parser.title
    return {"title": " ".join(title.split())[:200],
            "company": meta.get("og:site_name", "")[:200],
            "location": "", "deadline": "", "posted": "",
            "ad_text": _visible(html), "method": "page"}


def _visible(html):
    parser = TextExtractor()
    try:
        parser.feed(html or "")
    except (AssertionError, ValueError):
        pass
    return "\n".join(parser.parts)[:MAX_AD_CHARS]
