#!/usr/bin/env python3
"""Fictional demo jobs for development and screenshots: every career level, every type of employment and
more than ten career fields, in Finnish and English, across Finland. All employers are invented.

    JOBDESK_DATA=/tmp/jobdesk-demo python3 scripts/seed_demo.py           # add (or refresh) the demo jobs
    JOBDESK_DATA=/tmp/jobdesk-demo python3 scripts/seed_demo.py --remove  # delete them again

The jobs are stored with source "Demo" and go through the same classification and ad reading as imported
jobs (career fields, level, place, pay, languages ...), so they also show what the rules make of real ads.
Run it against a development database only: it refuses a database that has jobs from real sources unless
--force is given.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db        # noqa: E402
import scraper   # noqa: E402

SOURCE = "Demo"


def _day(days):
    d = date.today() + timedelta(days=days)
    return f"{d.day}.{d.month}.{d.year}"


# (id, title, employer, location, ad text)
JOBS = [
    ("it-1", "Junior Software Developer", "Esimerkki Software Oy", "Helsinki",
     "Join our product team building web services with Python and TypeScript. Recent graduates welcome. "
     f"Finnish is not required; our working language is English. Hybrid work. Apply by {_day(21)}. "
     "Salary 3 200–3 800 €/month. Permanent, full-time position."),
    ("it-2", "Master's Thesis Worker, Machine Learning", "Kuvitteellinen Tech Oy", "Espoo",
     "Master's thesis on anomaly detection in sensor data, 6 months from 1.2.2027. Paid thesis position, "
     f"30 ECTS. The work can be done remotely. Fluent English required. Apply by {_day(30)}."),
    ("it-3", "IT-tukihenkilö (osa-aikainen)", "Demokaupungin kaupunki", "Tampere",
     "Haemme osa-aikaista IT-tukihenkilöä opintojen ohessa. Sujuva suomen kielen taito edellytetään. "
     f"Tuntipalkka 14,50 €. Hakuaika päättyy {_day(10)}."),
    ("eng-1", "Summer Trainee, Mechanical Engineering", "Esimerkki Machines Oy", "Vaasa",
     "Summer trainee position for engineering students in our design team, summer 2027. Paid internship. "
     f"Finnish skills are considered an advantage. Applications by {_day(45)}."),
    ("eng-2", "Senior Electrical Design Engineer", "Kuvitteellinen Energia Oy", "Oulu",
     "We need an experienced designer with at least 5 years of experience in power distribution. "
     "Excellent Finnish required. Permanent position. A security clearance will be carried out."),
    ("health-1", "Sairaanhoitaja, sisätautiosasto", "Kuvitteellinen hyvinvointialue", "Kuopio",
     "Vakituinen sairaanhoitajan toimi. Palkkaus Sote-sopimuksen mukaan. Edellytämme sujuvaa suomen kielen "
     f"taitoa. Työ alkaa 1.3.2027. Hakuaika päättyy {_day(14)}."),
    ("health-2", "Kesätyöntekijä, lähihoitaja", "Esimerkin vanhuspalvelut", "Turku",
     "Kesätyöntekijöitä vanhuspalveluihin kesäksi 2027. Määräaikainen, kokoaikainen työ. Ruotsin kielen "
     f"taito katsotaan eduksi. Hakuaika päättyy {_day(60)}."),
    ("social-1", "Sosiaaliohjaaja, nuorisotyö", "Demokunta", "Joensuu",
     "Määräaikainen sosiaaliohjaajan sijaisuus 1.1.–30.6.2027. Palkkaus KVTES:n mukaan. "
     "Hyvä suomen kielen taito vaaditaan."),
    ("edu-1", "English-speaking Early Childhood Teacher", "Esimerkki International Daycare Oy", "Espoo",
     "Early childhood teacher for our English-speaking group. Finnish is not required. Fixed-term position "
     "for one year, full-time. You need the right to work in Finland."),
    ("edu-2", "Luokanopettajan sijaisuus", "Demokaupungin kaupunki", "Jyväskylä",
     "Luokanopettajan viransijaisuus lukuvuodeksi 2027–2028. Palkkaus OVTES:n mukaan. "
     f"Hakuaika päättyy {_day(25)}."),
    ("business-1", "Graduate Trainee Programme, Finance", "Kuvitteellinen Pankki Oyj", "Helsinki",
     "Our 12-month graduate trainee programme for recent graduates in economics. Salary €3,100 per month. "
     "Fluent Finnish and English are required."),
    ("business-2", "Markkinointiharjoittelija", "Esimerkki Kauppa Oy", "Tampere",
     "Palkallinen markkinointiharjoittelu, 15 op. Harjoittelu sopii opiskelijalle opintojen ohessa. "
     f"Suomen kielen taito katsotaan eduksi. Hae viimeistään {_day(18)}."),
    ("sales-1", "Myyjä, kesätyö", "Demo Urheilu Oy", "Lahti",
     "Kesätyö myymälässä, osa-aikainen. Ei vaadi aiempaa työkokemusta. Palkka kaupan alan "
     f"työehtosopimuksen mukaan. Hakuaika päättyy {_day(40)}."),
    ("hosp-1", "Barista, part-time", "Esimerkki Café Oy", "Helsinki",
     "Part-time barista for weekends, perfect to combine with your studies. No Finnish needed. "
     "Hourly wage 12.80 € plus evening supplements."),
    ("hosp-2", "Tarjoilija, keikkatyö", "Kuvitteellinen Ravintola Oy", "Rovaniemi",
     "Keikkatyötä talvikaudelle tarjoilijoille. Englannin kielen taito vaaditaan, suomen kieli eduksi."),
    ("log-1", "Varastotyöntekijä", "Demo Logistiikka Oy", "Vantaa",
     "Varastotyöntekijä kolmivuorotyöhön, vakituinen ja kokoaikainen. Trukkikortti eduksi. "
     "Työ tehdään paikan päällä. Palkka 2 400–2 700 €/kk."),
    ("cons-1", "Sähköasentaja, oppisopimus", "Esimerkki Sähkö Oy", "Seinäjoki",
     "Sähköasentajan oppisopimuskoulutus. Etsimme motivoitunutta aloittelevaa tekijää. "
     f"Aloitus heti. Hakuaika päättyy {_day(12)}."),
    ("research-1", "Doctoral Researcher in Forest Ecology", "Kuvitteellinen yliopisto", "Joensuu",
     "Fully funded doctoral researcher position, 4 years, in forest ecology. English is the working "
     "language. Visa sponsorship and relocation support are available."),
    ("forest-1", "Metsuri, kesätyö", "Demo Metsäpalvelut Oy", "Kajaani",
     "Kesätyö metsurina taimikonhoidossa kesäksi 2027. Metsäalan opiskelijoille. Palkallinen. "
     f"Hakuaika päättyy {_day(50)}."),
    ("culture-1", "Graphic Designer (Junior)", "Esimerkki Studio Oy", "Turku",
     "Junior graphic designer for our brand team. Our working language is English. Hybrid. "
     "Permanent position."),
    ("law-1", "Lakimiesharjoittelija", "Kuvitteellinen Asianajotoimisto Oy", "Helsinki",
     "Palkallinen harjoittelu oikeustieteen opiskelijalle kesällä 2027. Erinomainen suomen ja ruotsin kielen "
     f"taito edellytetään. Hakuaika päättyy {_day(35)}."),
    ("clean-1", "Siivooja, osa-aikainen", "Demo Kiinteistöpalvelut Oy", "Pori",
     "Osa-aikainen siivoustyö iltaisin, sopii opintojen ohessa tehtäväksi. Suomen kielen taitoa ei vaadita."),
]


def seed():
    check = db.start_check(1)
    for external_id, title, company, location, text in JOBS:
        job = {"source": SOURCE, "external_id": external_id, "url": "", "title": title, "company": company,
               "location": location, "posted": date.today().isoformat(), "category": "", "description": text}
        fields = scraper.classify_job(job, "general", ()) or ["business"]
        job["category"] = scraper.category_for(fields)
        db.upsert_scraped(job, check, fields=fields, meta=scraper.job_meta(job))
    db.finish_check(check, len(JOBS), len(JOBS), None)
    return len(JOBS)


def remove():
    with db.connect() as conn:
        return conn.execute("DELETE FROM jobs WHERE source=?", (SOURCE,)).rowcount


def main(argv):
    db.init()
    if "--remove" in argv:
        print(f"Removed {remove()} demo jobs from {db.DB_FILE}")
        return 0
    with db.connect() as conn:
        real = conn.execute("SELECT COUNT(*) FROM jobs WHERE source NOT IN (?, 'Saved', 'Community')", (SOURCE,)).fetchone()[0]
    if real and "--force" not in argv:
        print(f"{db.DB_FILE} has {real} jobs from real sources; use a development database (or --force).")
        return 1
    print(f"Added or refreshed {seed()} demo jobs in {db.DB_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
