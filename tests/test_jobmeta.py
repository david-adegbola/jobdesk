import unittest

from core import jobmeta
from core import places as core_places

PLACES = core_places.load()


def meta(title, text="", location="", company="", sector=""):
    return jobmeta.extract({"title": title, "ad_text": text, "location": location, "company": company}, sector)


class PlacesTests(unittest.TestCase):
    def test_the_official_list_is_complete(self):
        self.assertEqual(len(PLACES.municipalities), 308)
        self.assertEqual(len(PLACES.regions), 19)
        for m in PLACES.municipalities:
            self.assertIn(m["region"], PLACES.region_by_code, m)
        self.assertEqual(PLACES.name("091"), "Helsinki")
        self.assertEqual(PLACES.name("091", "sv"), "Helsingfors")
        self.assertEqual(PLACES.name("12", "en"), "North Karelia")

    def test_locations_are_matched_in_finnish_swedish_and_inflected_forms(self):
        cases = {
            "Helsinki": ("091", "01"), "00100 Helsinki": ("091", "01"), "Esbo": ("049", "01"),
            "Espoo / Vantaa": ("049", "01"), "Tampereella": ("837", "06"), "Helsingissä": ("091", "01"),
            "Oulussa ja Kempeleessä": ("564", "17"), "Turku, Kupittaa": ("853", "02"), "Lahdessa": ("398", "07"),
            "Maarianhamina": ("478", "21"), "Mariehamn": ("478", "21"), "Rovaniemellä": ("698", "19"),
            "Pohjois-Karjala": ("", "12"), "Uusimaa": ("", "01"), "Etätyö": ("", ""), "Finland": ("", ""), "": ("", ""),
        }
        for location, expected in cases.items():
            self.assertEqual(PLACES.match(location), expected, location)


class LevelAndTypeTests(unittest.TestCase):
    def test_levels(self):
        cases = [
            ("Opinnäytetyöntekijä, tekoäly", [], ["thesis"]),
            ("Master's thesis worker: battery materials", [], ["thesis"]),
            ("Diplomityöntekijä", [], ["thesis"]),
            ("Harjoittelija, viestintä", [], ["internship"]),
            ("Summer Trainee, Finance", [], ["internship"]),
            ("Kesäharjoittelija 2027", [], ["internship"]),
            ("Graduate Trainee Programme 2027", [], ["trainee"]),
            ("Trainee, myynti", [], ["trainee"]),
            ("Junior Data Analyst", [], ["entry"]),
            ("Myyjä", ["Tehtävä ei vaadi aiempaa työkokemusta."], ["entry"]),
            ("Software Engineer", ["We welcome recent graduates."], ["entry"]),
            ("Senior Backend Developer", [], ["experienced"]),
            ("Projektipäällikkö", ["Edellytämme vähintään 5 vuoden kokemusta."], ["experienced"]),
            ("Analyst", ["You have 3+ years of experience in SQL."], ["experienced"]),
            ("Sairaanhoitaja", [], []),
        ]
        for title, text, expected in cases:
            self.assertEqual(meta(title, " ".join(text))["levels"], expected, title)

    def test_employment_types_and_summer_jobs(self):
        cases = [
            ("Kesätyöntekijä, puisto", "", ["summer"]),
            ("Summer job in customer service", "", ["summer"]),
            ("Sommarjobb inom vården", "", ["summer"]),
            ("Myyjä", "Työ on osa-aikainen ja määräaikainen.", ["part_time", "fixed_term"]),
            ("Developer", "This is a permanent, full-time position.", ["full_time", "permanent"]),
            ("Lähihoitaja", "Toistaiseksi voimassa oleva työsuhde, kokoaikainen.", ["full_time", "permanent"]),
            ("Sähköasentaja", "Mahdollisuus oppisopimukseen.", ["apprenticeship"]),
            ("Tarjoilija", "Keikkatyötä viikonloppuisin.", ["gig"]),
            ("Opettaja", "Viransijaisuus 1.8.2027–31.7.2028.", ["fixed_term"]),
        ]
        for title, text, expected in cases:
            self.assertEqual(meta(title, text)["employment_types"], expected, title)

    def test_work_mode(self):
        self.assertEqual(meta("Developer", "Fully remote within Finland.")["work_mode"], "remote")
        self.assertEqual(meta("Kehittäjä", "Työ tehdään etätyönä.")["work_mode"], "remote")
        self.assertEqual(meta("Analyytikko", "Mahdollisuus osittaiseen etätyöhön.")["work_mode"], "hybrid")
        self.assertEqual(meta("Designer", "Hybrid: three days in the office.")["work_mode"], "hybrid")
        self.assertEqual(meta("Varastotyöntekijä", "Työ tehdään paikan päällä Vantaalla.")["work_mode"], "onsite")
        self.assertEqual(meta("Myyjä", "Tervetuloa!")["work_mode"], "")
        self.assertEqual(meta("Support agent", "", location="Etätyö")["work_mode"], "remote")


class DatesAndPayTests(unittest.TestCase):
    def test_deadline_and_start_date(self):
        m = meta("Harjoittelija", "Hakuaika päättyy 15.1.2027 klo 16. Työ alkaa 1.6.2027.")
        self.assertEqual((m["deadline"], m["start_date"]), ("2027-01-15", "2027-06-01"))
        m = meta("Intern", "Apply by 31 January 2027. Start date: June 2, 2027.")
        self.assertEqual((m["deadline"], m["start_date"]), ("2027-01-31", "2027-06-02"))
        self.assertEqual(meta("Myyjä", "Aloitus heti tai sopimuksen mukaan.")["start_date"], "asap")
        self.assertEqual(meta("Myyjä", "Hyvä työpaikka.")["deadline"], "")
        self.assertEqual(meta("Myyjä", "Hakuaika päättyy 31.2.2027.")["deadline"], "")    # no such day

    def test_salary(self):
        cases = [
            ("Palkka 2 800–3 200 €/kk.", (2800, 3200, "month")),
            ("Tuntipalkka 12,50 €.", (12.5, 12.5, "hour")),
            ("Palkkaus 3000 euroa kuukaudessa.", (3000, 3000, "month")),
            ("Salary €3,000 per month.", (3000, 3000, "month")),
            ("The salary is 45 000 € / year.", (45000, 45000, "year")),
            ("Harjoittelupalkka 1900 e/kk", (1900, 1900, "month")),
            ("Hourly wage 14.20 € plus evening supplements.", (14.2, 14.2, "hour")),
            ("Hinta 15 € / kpl", (None, None, "")),       # not pay
            ("Kahvi maksaa 2 €.", (None, None, "")),
        ]
        for text, expected in cases:
            self.assertEqual(jobmeta.salary(text), expected, text)

    def test_collective_agreement(self):
        self.assertEqual(meta("Lähihoitaja", "Palkkaus Sote-sopimuksen mukaan.")["tes"], "Sote-sopimus")
        self.assertEqual(meta("Opettaja", "Palkkaus OVTES:n mukaisesti.")["tes"], "OVTES")
        self.assertEqual(meta("Kirjastovirkailija", "Palkkaus määräytyy KVTES:n mukaan.")["tes"], "KVTES")
        self.assertEqual(meta("Myyjä", "Palkka kaupan alan työehtosopimuksen mukaan.")["tes"], "TES")
        self.assertEqual(meta("Myyjä", "Hyvä palkka.")["tes"], "")
        self.assertEqual(meta("Trainee", "A programme for recent graduates.")["tes"], "")    # not an agreement
        self.assertEqual(meta("Myyjä", "Palkkaus AVAINTES:n mukaan.")["tes"], "AVAINTES")


class LanguageAndPermitTests(unittest.TestCase):
    def test_finnish_requirement(self):
        cases = [
            ("Developer", "Finnish is not required; our working language is English.", "not_needed"),
            ("Developer", "No Finnish needed.", "not_needed"),
            ("Kehittäjä", "Suomen kielen taitoa ei vaadita.", "not_needed"),
            ("Analyst", "Fluent Finnish and English are required.", "required"),
            ("Myyjä", "Edellytämme sujuvaa suomen kielen taitoa.", "required"),
            ("Engineer", "Finnish language skills are considered an advantage.", "preferred"),
            ("Insinööri", "Suomen kielen taito katsotaan eduksi.", "preferred"),
            ("Tarjoilija", "Englannin kielen taito vaaditaan, suomen kieli eduksi.", "preferred"),
            ("Juristi", "Erinomainen suomen ja ruotsin kielen taito edellytetään.", "required"),
            ("Myyjä", "Sujuva suomen kielen taito vaaditaan, ruotsin kielen taito eduksi.", "required"),
            ("Engineer", "Great team.", "unclear"),
        ]
        for title, text, expected in cases:
            self.assertEqual(meta(title, text)["lang_fi"], expected, text)

    def test_swedish_and_english(self):
        m = meta("Sairaanhoitaja", "Ruotsin kielen taito katsotaan eduksi. Hyvä englannin kielen taito vaaditaan.")
        self.assertEqual((m["lang_sv"], m["lang_en"]), ("preferred", "required"))
        self.assertEqual(meta("Sjuksköterska", "Goda kunskaper i svenska krävs.")["lang_sv"], "required")

    def test_finnish_not_required_counts_english_ads_that_dont_ask_for_finnish(self):
        english = meta("Data Engineer", "We are looking for a data engineer to join our team in Helsinki. "
                                        "You will build pipelines and work with the analysts.")
        self.assertEqual(english["ad_language"], "en")
        self.assertTrue(jobmeta.finnish_not_required(english))
        finnish = meta("Myyjä", "Haemme myyjää myymäläämme. Työ sisältää asiakaspalvelua ja kassatyötä.")
        self.assertFalse(jobmeta.finnish_not_required(finnish))
        asks = meta("Data Engineer", "We are looking for a data engineer. Fluent Finnish is required.")
        self.assertFalse(jobmeta.finnish_not_required(asks))

    def test_work_permit_notes(self):
        self.assertEqual(meta("Poliisi", "Edellytämme Suomen kansalaisuutta.")["permits"], ["citizenship"])
        self.assertEqual(meta("Analyst", "A security clearance will be carried out.")["permits"], ["security_clearance"])
        self.assertEqual(meta("Developer", "You need a valid work permit for Finland.")["permits"], ["right_to_work"])
        self.assertEqual(meta("Engineer", "We offer visa sponsorship and relocation support.")["permits"], ["sponsorship"])
        self.assertEqual(meta("Engineer", "Open to EU/EEA citizens.")["permits"], ["eu_eea"])


class StudentAndEmployerTests(unittest.TestCase):
    def test_student_fields(self):
        m = meta("Harjoittelija", "Harjoittelusta voi saada 15 op. Harjoittelu on palkallinen.")
        self.assertEqual((m["internship_credits"], m["paid"]), (15, 1))
        m = meta("Intern", "Unpaid internship worth 30 ECTS credits.")
        self.assertEqual((m["internship_credits"], m["paid"]), (30, 0))
        self.assertEqual(meta("Myyjä", "Työ sopii opintojen ohessa tehtäväksi.")["combinable_with_studies"], 1)
        self.assertEqual(meta("Barista", "Perfect to combine with your studies.")["combinable_with_studies"], 1)
        self.assertIsNone(meta("Myyjä", "Kokoaikainen työ.")["combinable_with_studies"])
        self.assertIsNone(meta("Myyjä", "Hae 3 kk harjoitteluun.")["internship_credits"])

    def test_employer_sector(self):
        self.assertEqual(meta("x", company="Tampereen kaupunki")["employer_sector"], "public")
        self.assertEqual(meta("x", company="Pirkanmaan hyvinvointialue")["employer_sector"], "public")
        self.assertEqual(meta("x", company="Helsingin yliopisto")["employer_sector"], "public")
        self.assertEqual(meta("x", company="Suomen Punainen Risti ry")["employer_sector"], "third")
        self.assertEqual(meta("x", company="Esimerkki Oy")["employer_sector"], "private")
        self.assertEqual(meta("x", company="Example Ltd")["employer_sector"], "private")
        self.assertEqual(meta("x", company="Some employer")["employer_sector"], "")
        self.assertEqual(meta("x", company="Some employer", sector="public")["employer_sector"], "public")


if __name__ == "__main__":
    unittest.main()
