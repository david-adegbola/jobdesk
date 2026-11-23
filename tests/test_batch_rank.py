import unittest

from core import batch, finnish, rank


class BatchTests(unittest.TestCase):
    def test_pasted_ads_are_split_on_dash_lines(self):
        text = "Metsäharjoittelija\nEdellytämme suomen kieltä.\n---\nGIS intern\nWorking language English.\n\n-----\n"
        result = batch.parse_pasted(text)
        self.assertEqual([ad["title"] for ad in result["ads"]], ["Metsäharjoittelija", "GIS intern"])
        self.assertEqual(result["ads"][1]["ad_text"], "GIS intern\nWorking language English.")
        self.assertEqual(result["errors"], [])

    def test_oversized_ads_are_reported_not_dropped_silently(self):
        result = batch.parse_pasted("Short ad\n---\n" + "x" * (batch.MAX_AD_CHARS + 1))
        self.assertEqual(len(result["ads"]), 1)
        self.assertEqual(result["errors"][0]["item"], "ad-2")

    def test_csv_rows_need_text_or_a_link(self):
        text = "id,title,url,ad_text\nj1,GIS intern,,Uses QGIS.\nj2,No text,,\nj3,Linked,https://example.fi/j3,\n"
        result = batch.parse_csv(text)
        self.assertEqual([ad["id"] for ad in result["ads"]], ["j1", "j3"])
        self.assertEqual(result["errors"], [{"item": "row 2", "message": "No ad_text or url."}])
        filled = batch.fill_from_urls(result, lambda url: "Ad text from " + url)
        self.assertEqual(filled["ads"][1]["ad_text"], "Ad text from https://example.fi/j3")

    def test_csv_without_usable_columns(self):
        self.assertEqual(batch.parse_csv("name,phone\nA,1\n")["errors"][0]["item"], "csv")

    def test_urls_use_the_given_fetcher_and_report_failures(self):
        seen = []

        def fetch(url):
            seen.append(url)
            return "" if "blocked" in url else "Forest intern\nPython and QGIS."
        result = batch.fetch_urls(["https://example.fi/a", "ftp://example.fi/b", "https://blocked.fi/c", ""], fetch)
        self.assertEqual([ad["url"] for ad in result["ads"]], ["https://example.fi/a"])
        self.assertEqual(seen, ["https://example.fi/a", "https://blocked.fi/c"])
        self.assertEqual([e["item"] for e in result["errors"]], ["ftp://example.fi/b", "https://blocked.fi/c"])

    def test_url_list_is_capped(self):
        result = batch.fetch_urls([f"https://example.fi/{i}" for i in range(batch.MAX_URLS + 5)], lambda u: "Ad")
        self.assertEqual(len(result["ads"]), batch.MAX_URLS)
        self.assertEqual(result["errors"][0]["item"], "input")


def level(value, quote=""):
    return {"level": value, "evidence": [quote] if quote else [], "method": "llm"}


ADS = [
    {"id": "a", "title": "GIS-harjoittelija", "url": "", "ad_text": "Paikkatieto, QGIS ja Python. Suomi vaaditaan."},
    {"id": "b", "title": "Forest data intern", "url": "", "ad_text": "QGIS and remote sensing. English only."},
    {"id": "c", "title": "Field assistant", "url": "", "ad_text": "Field work. Finnish is a plus."},
    {"id": "d", "title": "Analyst", "url": "", "ad_text": "Python, R and QGIS."},
]
RESULTS = {"a": level("required", "Suomi vaaditaan."), "b": level("not_needed", "English only."),
           "c": level("preferred", "Finnish is a plus."), "d": level("unclear")}
SKILLS = ["QGIS", "Python", "remote sensing", "R"]


class RankTests(unittest.TestCase):
    def test_required_ads_go_last_and_skills_order_the_rest(self):
        rows = rank.rank(ADS, SKILLS, RESULTS)
        self.assertEqual([r["id"] for r in rows], ["b", "c", "d", "a"])
        self.assertEqual(rows[0]["matched_skills"], ["QGIS", "remote sensing"])
        self.assertEqual(rows[2]["matched_skills"], ["QGIS", "Python", "R"])
        self.assertIn('the ad says: "Suomi vaaditaan."', rows[-1]["reasons"][1])

    def test_fluent_students_are_ranked_on_skills_only(self):
        rows = rank.rank(ADS, SKILLS, RESULTS, student_finnish="fluent")
        self.assertEqual([r["id"] for r in rows], ["d", "a", "b", "c"])
        self.assertEqual(rows[1]["finnish"]["level"], "required")        # still shown
        self.assertTrue(any("fluent" in reason for reason in rows[1]["reasons"]))

    def test_short_skills_need_a_whole_word(self):
        self.assertEqual(rank.skill_matches("Rooli: tutkimusavustaja", ["R"]), [])
        self.assertEqual(rank.skill_matches("Tools: R and Python", ["R"]), ["R"])

    def test_finnish_case_endings_still_match(self):
        self.assertEqual(rank.skill_matches("Kokemusta paikkatietoaineistoista", ["paikkatieto"]), ["paikkatieto"])

    def test_missing_classification_counts_as_unclear(self):
        rows = rank.rank(ADS[:1], SKILLS, {})
        self.assertEqual(rows[0]["finnish"]["level"], "unclear")

    def test_rank_with_mock_or_fallback_results(self):
        results = {ad["id"]: finnish.fallback(ad["ad_text"]) for ad in ADS}
        rows = rank.rank(ADS, SKILLS, results)
        self.assertEqual(len(rows), 4)

    def test_bad_student_level(self):
        with self.assertRaises(ValueError):
            rank.rank(ADS, SKILLS, RESULTS, student_finnish="C1")


if __name__ == "__main__":
    unittest.main()
