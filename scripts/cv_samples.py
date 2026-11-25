#!/usr/bin/env python3
"""Build sample CVs in the default layout from fictional people, for checking the look and the text.

    python3 scripts/cv_samples.py OUTDIR        # PDFs, page images (pdftoppm) and extracted text (pdftotext)

Run it in a container with TeX Live (see AGENTS.md). Compare the page images with the CV repository's output
when the layout changes. All people and employers here are invented.
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv_pdf  # noqa: E402

EXPERIENCE = (
    "Jun 2025 — present — Junior Data Analyst — Esimerkki Analytics Oy\n"
    "Built weekly sales dashboards and cleaned customer data with Python and SQL.\n"
    "Automated a monthly report, saving the team about four hours a month.\n"
    "Tags: python, sql, power-bi, data-cleaning\n\n"
    "May 2024 — Aug 2024 — Summer Trainee — Kuvitteellinen Bank Oyj\n"
    "Checked payment data for errors and documented the fixes.\n\n"
    "2021 — 2023 — Sales Assistant — Demo Retail Oy\n"
    "Served customers, handled the till and kept the stock room in order."
)
SAMPLES = {
    "short": {"language": "en", "content": {
        "full_name": "Sam Example", "target_role": "Summer job in customer service",
        "email": "sam@example.test", "location": "Tampere, Finland",
        "summary": "First-year business student looking for a summer job.",
        "education": "2025–present: BBA, Example University of Applied Sciences",
        "languages": "English (fluent); Finnish (basic, A2)"}},
    "long": {"language": "en", "content": {
        "full_name": "Alex Example", "target_role": "Junior Data Analyst", "email": "alex@example.test",
        "phone": "+358 40 000 0000", "location": "Helsinki, Finland",
        "links": "GitHub: https://github.com/example\nPortfolio: https://example.test/portfolio",
        "summary": ("Data analytics student who likes turning messy spreadsheets into clear answers. "
                    "I have built dashboards for a real team and I write tidy, tested Python.\n\n"
                    "I am looking for a junior analyst role where I can keep learning SQL and statistics."),
        "education": "2023–present: BSc Information Technology, Example University\n2020–2023: Upper secondary school, Example Lukio",
        "skills": "Programming: Python, SQL, basic JavaScript\nData: pandas, Power BI, Excel, data cleaning\nTools: Git, Linux, Jupyter",
        "languages": "English: fluent (C1)\nFinnish: intermediate (B1)\nSwedish: basic (A2)",
        "experience": EXPERIENCE + "\n\n" + EXPERIENCE.replace("2025", "2023").replace("2024", "2022"),
        "projects": "2025 — Bus delay analysis — Course project\nAnalysed a year of open transport data and presented the findings.\nTags: python, open-data",
        "certifications": "2024: First aid (EA1); 2023: Hygiene passport",
        "hobbies": "Orienteering, board games and volunteering at a youth club."}},
    "finnish": {"language": "fi", "content": {
        "full_name": "Aino Mäkelä", "target_role": "Kesätyöntekijä, asiakaspalvelu", "email": "aino@example.test",
        "phone": "040 000 0000", "location": "Jyväskylä",
        "summary": "Olen liiketalouden opiskelija, joka nauttii asiakaspalvelusta ja tiimityöstä.",
        "education": "2024–: Tradenomi, Esimerkin ammattikorkeakoulu\n2021–2024: Ylioppilas, Esimerkin lukio",
        "skills": "Asiakaspalvelu: kassatyö, myynti, reklamaatiot\nTietotekniikka: Excel, Word",
        "languages": "Suomi (äidinkieli); Englanti (sujuva); Ruotsi (tyydyttävä)",
        "experience": "Kesä 2025 — Myyjä — Esimerkki Kauppa Oy\nPalvelin asiakkaita ja täytin hyllyjä.\nTagit: asiakaspalvelu, kassatyö",
        "certifications": "Hygieniapassi; Ensiapu EA1; Työturvallisuuskortti",
        "hobbies": "Lentopallo ja leipominen."}},
    "missing-sections": {"language": "en", "content": {
        "full_name": "Kim Example", "target_role": "", "email": "kim@example.test",
        "experience": "2024 — Volunteer — Example Food Bank\nSorted donations and packed food parcels."}},
    "special-characters": {"language": "en", "content": {
        "full_name": "Zoë Ångström-O'Neill", "target_role": "R&D intern (C/C++ & 50% #embedded)",
        "email": "zoe@example.test", "location": "Åbo / Turku",
        "summary": ('Costs $5 & 100% effort; uses ~/bin and a_b ^ c. Quotes: "hello" and ‘single’. '
                    "Dashes – and — and … ellipsis. Euro €20. Emoji 🚀 and Chinese 中文 are replaced. "
                    r"Braces {} and backslash \ and |pipes| and [brackets] stay literal."),
        "skills": r"Attempt: \input{/etc/passwd} \write18{touch pwned} \catcode`\@=11 \def\x{y}",
        "languages": "Français (courant); Deutsch: B2; Español (A2)"}},
}


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for name, sample in SAMPLES.items():
        cv = {"id": 1, "title": name, **sample}
        pdf = cv_pdf.compile_pdf(cv_pdf.render_tex(cv))
        target = out / f"{name}.pdf"
        target.write_bytes(pdf)
        if shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-r", "70", "-png", str(target), str(out / name)], check=True)
        if shutil.which("pdftotext"):
            subprocess.run(["pdftotext", "-layout", str(target), str(out / f"{name}.txt")], check=True)
        print(f"{name}: {len(pdf):,} bytes, file name {cv_pdf.download_name(cv)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cv-samples")
