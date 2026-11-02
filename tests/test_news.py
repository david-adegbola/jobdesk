import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import news


class NewsTests(unittest.TestCase):
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

    def test_rss_parser_extracts_article_and_filters_unrelated_items(self):
        feed = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>New forest bioeconomy research in Joensuu</title>
            <link>https://example.fi/news/forest?utm_source=feed</link>
            <pubDate>Mon, 02 Nov 2026 10:00:00 +0000</pubDate>
            <description>&lt;p&gt;A new &lt;strong&gt;forest data&lt;/strong&gt; project.&lt;/p&gt;</description>
          </item>
          <item>
            <title>City opens a new swimming pool</title>
            <link>https://example.fi/news/pool</link>
            <description>Tickets are available today.</description>
          </item>
        </channel></rss>"""
        articles = news.parse_feed(feed, news.SOURCES[0])

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["title"], "New forest bioeconomy research in Joensuu")
        self.assertEqual(article["url"], "https://example.fi/news/forest")
        self.assertIn("forest data project", article["summary"])
        self.assertEqual(article["category"], "Biotalous ja materiaalit")
        self.assertIn("Data ja teknologia", article["matched_topics"])
        self.assertTrue(article["published_at"].startswith("2026-11-02T"))
        regional_source = {**news.SOURCES[0], "region": "Pohjois-Karjala"}
        regional = news.parse_feed(feed, regional_source)[0]
        self.assertGreater(regional["relevance"], article["relevance"])

    def test_atom_parser_supports_alternate_links_and_html_content(self):
        source = news.SOURCES[0]
        feed = """<feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Forest restoration project advances biodiversity</title>
            <link rel="alternate" href="https://example.org/story/1"/>
            <updated>2026-11-01T09:30:00Z</updated>
            <content type="html">&lt;p&gt;New forest restoration work.&lt;/p&gt;</content>
          </entry>
        </feed>"""

        articles = news.parse_feed(feed, source)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["url"], "https://example.org/story/1")
        self.assertIn("forest restoration work", articles[0]["summary"])
        self.assertEqual(articles[0]["category"], "Luonto ja ilmasto")

    def test_news_state_survives_refresh_and_is_scoped_to_user(self):
        item = {
            "source_id": "luke",
            "source": "Luke",
            "external_id": "https://example.fi/story",
            "url": "https://example.fi/story",
            "title": "Forest story",
            "summary": "Sustainable forest management.",
            "published_at": "2026-11-02T10:00:00+00:00",
            "category": "Metsätalous",
            "region": "Suomi",
            "relevance": 50,
            "matched_topics": "Metsätalous",
        }
        self.assertTrue(db.upsert_news_item(item))
        item_id = db.list_news()[0]["id"]
        db.update_news_state(item_id, {"is_read": True, "is_saved": True})

        item["title"] = "Updated forest story"
        self.assertFalse(db.upsert_news_item(item))
        coverage = {**item,
                    "source_id": "industry",
                    "source": "Metsäteollisuus ry",
                    "external_id": "https://example.fi/another-report",
                    "url": "https://example.fi/another-report"}
        self.assertFalse(db.upsert_news_item(coverage))
        self.assertFalse(db.upsert_news_item(coverage))
        stored = db.list_news()[0]
        self.assertEqual(len(db.list_news()), 1)
        self.assertEqual(stored["title"], "Updated forest story")
        self.assertEqual(stored["is_read"], 1)
        self.assertEqual(stored["is_saved"], 1)
        self.assertEqual(len(stored["coverage"]), 1)
        self.assertEqual(stored["coverage"][0]["source"], "Metsäteollisuus ry")
        other_user_items = db.list_news(user_id=2)
        self.assertEqual(len(other_user_items), 1)
        self.assertFalse(other_user_items[0]["is_read"])
        self.assertFalse(other_user_items[0]["is_saved"])

    def test_refresh_reports_source_errors_without_discarding_successful_feeds(self):
        source = news.SOURCES[0]
        article = {
            "source_id": source["id"],
            "source": source["name"],
            "external_id": "https://example.fi/story",
            "url": "https://example.fi/story",
            "title": "Forest story",
            "summary": "",
            "published_at": "",
            "category": "Metsätalous",
            "region": "Suomi",
            "relevance": 20,
            "matched_topics": "Metsätalous",
        }
        sources = [source, {**source, "id": "unavailable", "name": "Unavailable"}]
        with patch.object(news, "SOURCES", sources), \
                patch.object(news, "fetch_source", side_effect=[([article], ""), ([], "503: unavailable")]):
            result = news.refresh()

        self.assertEqual(result, {
            "found": 1,
            "new": 1,
            "errors": ["Unavailable: 503: unavailable"],
            "checked": 2,
            "skipped": 0,
        })
        self.assertEqual(len(db.list_news()), 1)
        states = {state["source_id"]: state for state in db.list_news_source_state()}
        self.assertEqual(states["unavailable"]["error"], "503: unavailable")
        self.assertEqual(states[source["id"]]["new"], 1)

    def test_refresh_skips_feeds_within_their_refresh_interval(self):
        source = {**news.SOURCES[0], "interval_minutes": 60}
        with patch.object(news, "SOURCES", [source]), \
                patch.object(news, "fetch_source", return_value=([], "")) as fetch:
            news.refresh()
            result = news.refresh()

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["skipped"], 1)
        fetch.assert_called_once_with(source)

    def test_canonical_url_keeps_content_query_and_removes_tracking(self):
        self.assertEqual(
            news.canonical_url("https://example.fi/story?id=12&utm_source=rss#comments"),
            "https://example.fi/story?id=12",
        )
        self.assertEqual(news.canonical_url("javascript:alert(1)"), "")


if __name__ == "__main__":
    unittest.main()
