#!/usr/bin/env python3
"""Fictional applications for testing the Tracker with few or many cards (development databases only).

    JOBDESK_DATA=/tmp/jobdesk-demo python3 scripts/seed_tracker.py 150      # 150 in Saved, a few in other stages
    JOBDESK_DATA=/tmp/jobdesk-demo python3 scripts/seed_tracker.py 0        # remove them again

Jobs are stored with source "Demo-Tracker" for the administrator account (user 1): long and short titles,
deadlines passed, closing soon and later, and places in Finland and abroad.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db        # noqa: E402

SOURCE = "Demo-Tracker"
TITLES = ["Application Specialist, SAP Platform", "Head of Everyday AI Adoption", "Data Product Engineer",
          "Product Support Engineer - Mechanical, Grinding Mills and Crushing Equipment for Global Mining Customers",
          "Kesätyöntekijä, asiakaspalvelu", "Junior Software Developer", "Sairaanhoitaja, sisätautien osasto",
          "Research Assistant in Forest Ecology", "Varastotyöntekijä", "Graphic Designer (Junior)"]
EMPLOYERS = ["Metso", "Esimerkki Oy", "Kuvitteellinen hyvinvointialue", "Demo Software Oy", "Example University"]
PLACES = ["Espoo, Tampere", "West Perth WA 6005, Australia, Espoo", "Helsinki", "Oulu", "Espoo, Krakova, Puola, Lappeenranta",
          "Remote", "Turku"]
OTHER_STAGES = {"Shortlisted": 4, "Applied": 6, "Interview": 2, "Offer": 1, "Rejected": 3}


def remove():
    with db.connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE source=?", (SOURCE,))]
        conn.execute("DELETE FROM applications WHERE job_id IN (SELECT id FROM jobs WHERE source=?)", (SOURCE,))
        conn.execute("DELETE FROM jobs WHERE source=?", (SOURCE,))
    return len(ids)


def seed(saved):
    check = db.start_check(1)
    plan = [("Saved", saved)] + ([(s, n) for s, n in OTHER_STAGES.items()] if saved else [])
    n = 0
    for status, count in plan:
        for _ in range(count):
            n += 1
            offset = [-12, -1, 0, 2, 5, 14, 40, None][n % 8]
            job = {"source": SOURCE, "external_id": f"t{n}", "url": f"https://example.test/job/{n}",
                   "title": TITLES[n % len(TITLES)] + (f" ({n})" if n > len(TITLES) else ""),
                   "company": EMPLOYERS[n % len(EMPLOYERS)], "location": PLACES[n % len(PLACES)],
                   "posted": "2026-11-01", "category": "", "description": "Fictional ad for testing the Tracker."}
            deadline = (date.today() + timedelta(days=offset)).isoformat() if offset is not None else ""
            db.upsert_scraped(job, check, fields=["it"], meta={"deadline": deadline} if deadline else None)
            job_id = next(j["id"] for j in db.list_jobs() if j["external_id"] == f"t{n}" and j["source"] == SOURCE)
            db.set_status(job_id, status, {"next_action": "Call the recruiter" if n % 9 == 0 else ""}, 1)
    return n


def main(argv):
    db.init()
    saved = int(argv[0]) if argv else 30
    with db.connect() as conn:
        real = conn.execute("SELECT COUNT(*) FROM jobs WHERE source NOT IN (?, 'Demo', 'Saved', 'Community')", (SOURCE,)).fetchone()[0]
    if real and "--force" not in argv:
        print("This database has jobs from real sources; use a development database (or --force).")
        return 1
    removed = remove()
    added = seed(saved) if saved else 0
    print(f"Removed {removed}, added {added} tracker test applications ({saved} saved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
