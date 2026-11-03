import unittest

import language


class LanguageTests(unittest.TestCase):
    def test_titles(self):
        cases = {
            "Metsäasiantuntija": ["fi"], "Hitsaaja / HT Laser": ["fi"], "Kokoonpanijoita teollisuuteen": ["fi"],
            "Forest Data Specialist": ["en"], "Legal Counsel": ["en"],
            "Virkesköpare till Fryksdalen, Stora Enso Skog": ["sv"], "Gerente Projetos Complexos": [],
        }
        for title, expected in cases.items():
            self.assertEqual(language.detect(title), expected, title)

    def test_ad_text_decides_and_shared_words_do_not_make_finnish_ads_bilingual(self):
        finnish = "Haemme tehtävään kokenutta tekijää. Työ on määräaikainen ja hakemus on jätettävä mennessä."
        english = "We are looking for a researcher to join our team. Please apply with your application."
        self.assertEqual(language.detect("Tutkija", finnish), ["fi"])
        self.assertEqual(language.detect("Tutkija", english), ["en"])
        self.assertEqual(set(language.detect("Harjoittelija / Intern", finnish + " " + english)), {"fi", "en"})

    def test_news_headline_with_summary(self):
        self.assertEqual(language.detect("Forest bioeconomy outlook",
                                         "The report looks at the future of forests in Europe and what it means for you."),
                         ["en"])
