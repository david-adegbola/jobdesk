"""Many ads at once: from pasted text, a CSV file or a list of URLs.

Every reader returns {"ads": [...], "errors": [...]}. An ad is
    {"id": str, "title": str, "url": str, "ad_text": str}
and an error is {"item": str, "message": str} for something that was skipped. Readers never stop
at the first problem: a student pasting 20 ads should get 19 results and one clear message.

  parse_pasted(text)       ads separated by a line containing only --- ; the first line is the title.
  parse_csv(text)          columns id, title, url, ad_text (ad_text or url needed on each row).
  fetch_urls(urls, fetch)  reads each URL with fetch(url) -> text; give it core.fetch.fetch_ad_text
                           bound to a robots.txt check, so the SSRF guard and robots.txt both apply.
  fill_from_urls(ads, fetch)  for CSV rows with a URL but no ad text.
"""

import csv
import io
import re

MAX_ADS = 50
MAX_URLS = 25
MAX_AD_CHARS = 20_000
SEPARATOR = re.compile(r"^\s*-{3,}\s*$", re.M)
URL = re.compile(r"^https?://\S+$", re.I)


def _ad(index, title, url, text):
    return {"id": f"ad-{index}", "title": title.strip()[:200], "url": url.strip(), "ad_text": text.strip()}


def _check_size(ad, errors):
    if len(ad["ad_text"]) > MAX_AD_CHARS:
        errors.append({"item": ad["id"], "message": f"Longer than {MAX_AD_CHARS:,} characters; paste only the ad."})
        return False
    return True


def parse_pasted(text):
    ads, errors = [], []
    blocks = [block.strip() for block in SEPARATOR.split(text or "") if block.strip()]
    if len(blocks) > MAX_ADS:
        errors.append({"item": "input", "message": f"Only the first {MAX_ADS} ads are read."})
        blocks = blocks[:MAX_ADS]
    for index, block in enumerate(blocks, start=1):
        title = block.splitlines()[0]
        ad = _ad(index, title, "", block)
        if _check_size(ad, errors):
            ads.append(ad)
    return {"ads": ads, "errors": errors}


def parse_csv(text):
    ads, errors = [], []
    try:
        reader = csv.DictReader(io.StringIO(text or ""))
        fields = {name.strip().lower() for name in (reader.fieldnames or [])}
    except csv.Error as error:
        return {"ads": [], "errors": [{"item": "csv", "message": f"Could not read the CSV: {error}."}]}
    if not fields & {"ad_text", "url"}:
        return {"ads": [], "errors": [{"item": "csv", "message": "The CSV needs an ad_text or url column."}]}
    try:
        for index, row in enumerate(reader, start=1):
            if index > MAX_ADS:
                errors.append({"item": "csv", "message": f"Only the first {MAX_ADS} rows are read."})
                break
            row = {(k or "").strip().lower(): (v or "") for k, v in row.items() if isinstance(v, str)}
            if not row.get("ad_text", "").strip() and not row.get("url", "").strip():
                errors.append({"item": f"row {index}", "message": "No ad_text or url."})
                continue
            ad = _ad(index, row.get("title") or row.get("ad_text", "").strip().split("\n")[0], row.get("url", ""),
                     row.get("ad_text", ""))
            if row.get("id", "").strip():
                ad["id"] = row["id"].strip()[:100]
            if _check_size(ad, errors):
                ads.append(ad)
    except csv.Error as error:
        errors.append({"item": "csv", "message": f"Stopped reading the CSV: {error}."})
    return {"ads": ads, "errors": errors}


def fetch_urls(urls, fetch):
    """One ad per URL. fetch(url) returns the ad text, or '' when it can't or mustn't be read."""
    ads, errors = [], []
    cleaned = [u.strip() for u in urls if u and u.strip()]
    if len(cleaned) > MAX_URLS:
        errors.append({"item": "input", "message": f"Only the first {MAX_URLS} links are read."})
        cleaned = cleaned[:MAX_URLS]
    for index, url in enumerate(cleaned, start=1):
        if not URL.match(url):
            errors.append({"item": url, "message": "Not an http(s) link."})
            continue
        text = fetch(url)
        if not text:
            errors.append({"item": url, "message": "Couldn't read this page (or its robots.txt doesn't allow it). "
                                                   "Paste the ad text instead."})
            continue
        ad = _ad(index, text.strip().split("\n")[0], url, text)
        if _check_size(ad, errors):
            ads.append(ad)
    return {"ads": ads, "errors": errors}


def fill_from_urls(batch, fetch):
    """Fetch the text for CSV rows that have a URL but no ad text (at most MAX_URLS fetches)."""
    ads, errors = [], list(batch["errors"])
    fetched = 0
    for ad in batch["ads"]:
        if ad["ad_text"] or not ad["url"]:
            ads.append(ad)
            continue
        if fetched >= MAX_URLS:
            errors.append({"item": ad["id"], "message": f"Only {MAX_URLS} links are read per batch."})
            continue
        fetched += 1
        text = fetch(ad["url"])
        if not text:
            errors.append({"item": ad["id"], "message": "Couldn't read this page (or its robots.txt doesn't "
                                                        "allow it). Paste the ad text instead."})
            continue
        ads.append({**ad, "ad_text": text.strip()[:MAX_AD_CHARS]})
    return {"ads": ads, "errors": errors}


def split_urls(text):
    """Links from a pasted list, one per line (blank lines ignored)."""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]
