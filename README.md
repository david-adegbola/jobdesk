# JobDesk

Jobs, internships, summer jobs and thesis positions anywhere in Finland, in every career field, for students,
graduates and early-career people, including international students. It is built around one question international
students keep asking: **can I apply to this ad without fluent Finnish?** Members search the open ads by keyword
(English or Finnish), field, level, type, work mode, region and town, with "Finnish not required" and "Summer jobs"
one click away. For each ad they see whether Finnish is required, an advantage or not needed, with the sentence
that says so. They can rank ads against their CV, draft application answers grounded in it, and track applications.

Ads come from feeds published for reuse (the state and municipal job portals and a few sector feeds), from
employers through the **Post a job** form (approved by an administrator), and later from Työmarkkinatori's search
API (`core/importers.py`, off until credentials are granted). No job board is scraped.

**Career fields** are data: `taxonomy/fields.json` (18 fields on ISCO-08, the base of Statistics Finland's
Ammattiluokitus) and `taxonomy/roles.json` (about 90 occupations with ISCO-08 unit groups, ESCO URIs to be filled in,
and Finnish/English title patterns), loaded by `core/taxonomy.py`. Towns and regions are Statistics Finland's
Kunnat/Maakunnat 2026 list (`taxonomy/places.json`, CC BY 4.0). Members see every field until they choose theirs.

It started as a forestry careers portal. A small standalone version of the Finnish checker, written for a
Metropolia job application, lives in its own repository (finnish-check) and shares this repository's `core/` code.

Python 3 standard library, SQLite and plain HTML/CSS/JS: nothing to install. The AI features run in **mock mode**
without an API key.

**Pilot:** `docs/PILOT-DEPLOYMENT.md` (running a pilot), `docs/pilot/` (proposal, privacy notice and accessibility
statement drafts for Metropolia). `docs/CHANGES-EXPLAINED.md` explains every change in plain English.

## Tests

Run `python3 -m unittest discover -s tests -v` (in a container, not on a personal computer: see `AGENTS.md`).
Tests use temporary SQLite files and a local HTTP server; they cover authentication, ownership boundaries, the
taxonomy and migrations, reading job details from ads, dedupe and expiry, the employer form, search and the API.

**Demo data:** `JOBDESK_DATA=/tmp/jobdesk-demo python3 scripts/seed_demo.py` adds 22 fictional jobs (every level
and type of employment, 14 fields, all over Finland) to a development database; `--remove` deletes them.

## Accessibility requirements

Digital accessibility is a key product requirement. JobDesk targets **WCAG 2.1 Level AA** for
all user-facing flows. Changes should preserve keyboard operation and visible focus, accessible
names and form labels, sufficient text and control contrast, and content reflow at 320 CSS pixels
and 200% zoom. Do not rely on color alone to convey meaning. Verify the affected flow with keyboard
navigation and the available automated and manual accessibility checks; document any known gaps.
This is a development target, not a conformance claim: the complete app has not been independently
evaluated or certified against WCAG 2.1 Level AA.

## Pages

- **Shortlist:** paste up to 20 ads (or a CSV, or up to 10 links). For each ad you get the Finnish level, the exact
  quoted sentence it rests on, and the skills from your CV it mentions; ads you can realistically apply to come first.
  Each result has "Was this right?" for measuring accuracy. AI in live mode, a keyword rule in mock mode.
- **Draft an answer** (Applications): the question on the left; on the right the draft on lilac, the share of
  sentences from your CV, a word counter, a "make it yours" tip and Copy. An answer to an application question, built only from facts in your CV. Every sentence is
  checked against the facts it cites; unsupported sentences are marked and kept out of the answer box. The AI is used
  only if you turn on "AI drafting" under Account.
- **Fields and Finnish level** (Account): choose your fields (all of them until you do); Discover, Match and What
  to study follow them. The Finnish level orders the Shortlist (fluent speakers aren't affected). The fields are in
  `taxonomy/`; the older keyword profiles in `fields/` still help classify ads for the six fields that have one.
- **Home** (everyone): a short brief written from your own data (nearest deadline, overdue next steps, jobs not yet
  checked against your CV, your closest match), colour blocks for deadlines this week, applications in progress,
  preparing documents and what to study, a bar to paste a job link (it opens the Jobs page's add form), the jobs that fit
  your CV best, and the dates coming up. No AI and nothing stored: it reads the Jobs, CVs and Tracker data.
- **Menu:** Home, Discover, My jobs (Shortlist), Applications (Tracker, Prepare, Draft an answer), My CV; Profile
  (Account, What to study) opens from the avatar. On a phone the menu is a bottom tab bar.
- **Discover** (`static/pages/discover.js`, `GET /api/search`): every open shared ad you can see, searched on the
  server. Keywords match word starts in the title, employer, place and ad text (SQLite FTS5, diacritics folded; LIKE
  where FTS5 is missing) and also find roles named in the other language ("nurse" finds *Sairaanhoitaja*). Quick
  toggles: **Finnish not required** (the ad says so, or it is written in English or Swedish and doesn't ask for
  Finnish), **Summer jobs**, Internships, Thesis, Entry level, Remote, each with its count. "More filters": field,
  level, type, work mode, employer type, paid, alongside studies, and sort (newest or deadline). The filters are in
  the address (`#/jobs?q=nurse&level=internship&no_finnish=1&page=2`), so a search can be bookmarked or shared;
  25 a page. Each card shows the employer, town, deadline, level, type, work mode, Finnish, pay, study credits, work
  permit notes, the source (with any credit line its terms require) and a link to the original ad. **Save** moves
  one to My jobs. Old `#/jobs?add=` links forward to `#/myjobs?add=`.
- **Saved searches** (Discover): "Save this search" keeps the current filters (up to 10 per member, named from the
  filters, e.g. "Summer jobs in Tampere"). With "Email me new jobs" on (the default), every job check (timer or
  administrator) emails one message per member listing the jobs added since the last alert, at most 10 per search,
  each linked to its public page (or the original ad for members-only sources), with a link to turn alerts off.
  A failed email is retried after the next check. Saved searches are in the data download and go with the account.
- **My jobs → Saved jobs** holds the ads you saved or added, with a count per status, a status menu, **Shortlist**
  (the fit check, shown under the job) and **Prepare**. Each job is a row with a ring (your AI fit score when there's
  a current one, otherwise the keyword match with your CV), the employer, place and deadline, and tags for the type,
  the matching CV words and the Finnish requirement; "Why …?" opens the sentence the Finnish tag is based on.
  Filters, "Sort by" chips (Shift-click adds a level) and the type order work as before.
- **Public pages** (`public.py`, no account, plain HTML from the server): `/jobs` lists every open public ad
  (`?q=` searches, 20 a page), with landing pages such as `/jobs/summer`, `/jobs/no-finnish`, `/jobs/remote`,
  `/jobs/field/it`, `/jobs/level/internship`, `/jobs/town/tampere`, `/jobs/region/north-karelia` and combinations
  (`/jobs/field/health/town/kuopio/summer`). Each page has its own heading, a short summary in our own words (how many
  ads, where, how many without Finnish) and links to nearby pages. `/job/<id>-<title>` shows one job with schema.org
  `JobPosting` data and a link to the original; ads from feeds are shown as an excerpt, employers' own ads in full.
  Public means open listings from `sources.json` sources (unless `"public_pages": false`, as for Työmarkkinatori
  until its terms are confirmed) and approved employer ads; never members' saved or shared jobs, the administrator's
  own job types, closed ads or contact details. `/sitemap.xml` lists the job pages and landing pages with ads (a
  combination needs 3); `/robots.txt` allows only the public pages. The app sends `X-Robots-Tag` itself: public
  pages with ads are `index, follow`, empty pages, searches and closed jobs `noindex, follow`, everything else
  `noindex, nofollow` (Caddy no longer sets it). **Indexing is off until `JOBDESK_PUBLIC_INDEXING=1`**: before
  that every public page says `noindex, nofollow` and `robots.txt` disallows everything; turn it on once the public
  privacy notice is published. `JOBDESK_AD_SLOTS=1` shows the reserved advert spaces (empty: no ad
  code is loaded until a certified consent tool is chosen). The privacy notice draft for the public site is
  `docs/PRIVACY-NOTICE-PUBLIC-DRAFT.md`.
- **Post a job** (`/employers.html`, public, no account): employers send an ad with its fields, town, level, type,
  dates, pay, TES, languages, permit notes and student details. Answers are checked on the server, the form has a
  honeypot and is limited to 5 ads an hour per address and per email, and nothing is listed until an administrator
  approves it under **Account → Employer ads to review**. Approved ads are listed as source "Employer" until their
  deadline (60 days without one). The employer's contact details are never shown and are deleted 90 days after the
  decision.
  **Add a job** (Saved jobs): paste a link and click **Read this link**. JobDesk reads the ad's schema.org
  `JobPosting` data (title, employer, place, posting and closing dates, description), which most job
  sites publish for search engines; without it, only the page title and text are read. You check
  the details before saving. If the page can't be read (robots.txt disallows it, it needs a sign-in,
  or it didn't answer), the same form opens for you to fill in. Links are compared in a normalised
  form (no `www.`, tracking parameters, `#fragment` or trailing slash), so the same ad isn't saved
  twice, and adding a link that is already a shared listing saves that listing instead of copying
  it. The **Save to JobDesk** bookmarklet opens this form from any job page, with the text you
  selected copied into the description. Jobs you add are private unless you share them.
  `core/jobpage.py` does the reading; reading links is limited to 60 per member per hour.
- **Shortlist a job** (My jobs): moves it to *Shortlisted* and compares it with your CV in the
  background. The result shows a rating (strong fit, possible fit, a stretch, weak fit), strengths
  (each with the ad's sentence and the CV fact behind it), gaps, and recommendations. Requirements
  the CV doesn't show (licences, cards, fluent Finnish, years of experience) are always gaps.
  With "AI with your CV" on (Account) and live mode, Claude does the comparison; otherwise it is a
  word comparison on the server, which never rates a job "strong". Results are stored per ad, CV
  and method, so the same comparison never runs twice; editing the CV or the ad marks it out of
  date. *Not a fit* is a status, so you can set it aside. Statuses: Saved, Shortlisted, Applied,
  Interview, Offer, Rejected, Not a fit.
- **Prepare** (Applications): a workspace with the three documents on the left (with the sentence checks), the
  letter edited as a page in the middle (paragraphs the AI wrote are shaded lilac, paragraphs with a sentence your CV
  doesn't support are shaded coral with a note), and a live A4 preview on the right that follows your typing. With
  both languages written, a switch shows one at a time. For one of your jobs, a tailored CV, a cover letter and an application email,
  in English, Finnish or both. Set your **master profile** once: the main CV, and practical details
  (start date, hours, places, work permit, licences) that the letter may use. The tailored CV is a
  copy of the main CV with a summary written for the job and the ad's skills first. The letter
  follows the CV repository's rules (CV-RULES.md sections 4-6 and 9): header, date, recipient,
  subject "Application: <job>, <company> <city>", greeting by first name, five short paragraphs
  ending with an honest Finnish line, closing and contacts. The email is the short "I just applied"
  note. Every written sentence cites CV facts and is checked like **Draft an answer**; buzzwords and
  em dashes are flagged. Edits are kept unless you confirm replacing them. Downloads: letter PDF
  (LaTeX, with the shared `cv-style.sty`; named like `Aino-Makela-Cover-Letter-Data-Analyst-EN.pdf`),
  letter text, the CV PDF, and the email via Copy or "Open in email". The writing runs in the
  background queue. AI writes the text only in live mode with "AI with your CV" on; otherwise CV
  facts are copied in for you to rewrite.
- **Listings (sources):** `sources.json` lists every source with its robots.txt and terms notes. By default only
  feeds published for reuse are read: [Valtiolle](https://valtiolle.fi/fi/tyopaikat/) (all state agencies, in
  Finnish and English), [Kuntarekry](https://kuntarekry.fi/fi/tyopaikat/) (municipalities and wellbeing services
  counties, the whole feed), [Metsälehti](https://www.metsalehti.fi/tyopaikat/) and
  [Metsähallitus](https://metsa.rekrytointi.com/paikat/?o=A_LOJ&list=2). Page readers and internal APIs (employer
  career sites, Workday) are off; `JOBDESK_ENABLE_SOURCES` turns one on only with the site's permission. There are
  no readers for job boards (Jobly, Duunitori, LinkedIn ...). Every automatic request is checked against robots.txt
  first.
  **Työmarkkinatori** (`core/importers.py`) is read once `JOBDESK_TMT_API_URL` and `JOBDESK_TMT_API_KEY` are set;
  its ads carry the required credit line and are closed within a day of leaving the API. The timer
  (`deploy/systemd/jobdesk-jobs.timer`) runs `server.py --check-jobs` at 06:00 and 15:00 Helsinki time; an
  administrator can also start a check from Discover.
- **Each job** is tagged with its career fields (title roles, keyword profiles, old category) and, read from the ad
  with rules in Finnish, English and Swedish (`core/jobmeta.py`): level (thesis, internship, trainee, entry,
  experienced), type (summer, full-time, part-time, fixed-term, permanent, apprenticeship, gig), work mode, town and
  region (`core/places.py`), deadline and start date, pay and period, TES, Finnish/Swedish/English requirement,
  work permit notes, study credits, paid or unpaid, alongside studies, and employer type. A value is set only when
  the ad says it. An AI Finnish check of the current ad text, when there is one, wins over the rules.
- **Duplicates and closing:** a posting already listed from another source (same address, or the same title,
  employer and town) isn't added again (`core/dedupe.py`). A listing closes when its deadline passes, or when it
  has been missing for 7 days from a feed that answered with postings in a complete check (a feed that fails
  closes nothing). Closed listings leave Discover but stay in the Tracker of members who saved them; one that comes
  back is opened again. Each job shows a 0–100 **Match** against the member's own CVs.
  **Search scope:** Discover searches every field; a member's chosen fields are ticked as the default filter and
  can be unticked (`field=all` in the address).
  **Administrator view:** jobs the administrator stored earlier under their own job types (Industrial,
  Construction, Warehouse, IT-Data centre) are tagged "Only you" and never shown to members. `python3 server.py --prune-unrelated-jobs` (add
  `--apply` to delete, after an automatic backup) removes stored jobs that nobody can see.
- **Show text in English:** Discover and My jobs have an Original / English switch, remembered in the
  browser (Home follows it). English machine-translates Finnish and Swedish titles on the device with the browser's built-in Translator API: nothing is sent to a server
  and there is no cost. It needs desktop Chrome 138+ or Edge 148+; the first use downloads a
  language pack. Other browsers and phones show the original text with a note (their own
  "Translate page" option still works, helped by `lang` attributes). Each item's language is
  worked out on the server by counting common Finnish, English and Swedish words (`language.py`);
  items that already have English text are left alone.
- **What to study:** groups the jobs you can see into the role types of your fields' keyword profiles
  (`fields/*.json`; for example software, data and support for IT) and lists the skills
  their ads ask for, in Finnish and English, compared with your own CVs. "Study next" shows skills
  that two or more ads mention but none of your CVs shows; each skill shows how many ads ask for it.
  "Start a CV for this role" opens an unsaved draft based on your closest CV, with the role as target
  and the skills still to learn on a "Want to learn" row (never as skills already held). It uses
  keyword matching, not AI; jobs with the full ad saved give better counts than title-only listings.
- **Tracker** (Applications): a board with one column per status (Rejected is titled "Not this time"). Each card
  shows the employer, a small fit ring and one next step: your own, a follow-up reminder, or what usually comes next
  (prepare documents, practise answers). Private to the signed-in member. Each card holds the date applied, CV,
  link sent, contact, notes and the next action. Overdue actions are red; "Applied" with no change
  for 5 days shows a `Call <contact>` reminder. Deadlines and interviews export as `.ics`.
- **My CV:** your CVs on the left (the main one first, tailored copies marked), the chosen CV in a section editor in
  the middle, and a rough live preview on the right ("CV as PDF" shows the real page). Switching CV, or making a new
  one, asks before discarding unsaved changes. New CVs start from the example below.
  Preview a fictional two-page CV, then create an editable draft from its structure;
  the sample is not saved to the account. Create multiple private Finnish or English CVs with
  profile, education, experience, skills, research/projects, certifications, languages and links.
  Edit, copy or delete a CV, then
  view its formatted PDF using the same LaTeX document layout and shared style as the
  original role CVs. Imported role PDFs are compiled on demand from their original LaTeX source when
  a prebuilt PDF is not present in the CV repository. On startup, JobDesk imports the administrator's
  existing Finnish and English role CVs from the configured CV repository once, including forestry, industrial, IT, sales, trainee
  and warehouse versions. These are editable text copies stored only in the administrator's account.
  Their download uses the exact original, role-specific PDF compiled from the LaTeX source in the
  CV repository. New CVs created by members use that same LaTeX style and document structure:
  centered name and role, contact header, paragraph summary, labeled education and skills rows,
  dated experience entries with indented details, optional Hobbies, and the standard References
  section. Member CV PDFs are compiled on the server from saved data and are not uploaded to the
  shared repository.
  Choosing the other language in the CV editor opens that CV's version in the other language when
  one exists (imported role CVs come in Finnish/English pairs; drafts from What to study are
  rebuilt in that language). Without one, the text stays as written and only the PDF headings
  change, so translate it before saving.
- **Account** (Profile, from the avatar): your progress as colour blocks (jobs checked against your CV, applications
  sent, Finnish level), a link to What to study, and the settings as rows: fields and Finnish, the "AI with your CV"
  switch, data download, invitations (administrator), deleting the account and signing out.
  Download your private data, sign out, or delete the account (type your email to
  confirm). There are no passwords: you sign in with a one-time link sent to your email
  (`JOBDESK_EMAIL_BACKEND`, see `mailer.py`). Administrators can create single-use, seven-day
  invitation codes; with `JOBDESK_OPEN_SIGNUP=0` only people with a code can create an account.

## AI and mock mode

Set `JOBDESK_LLM_MODE=live` and **one** key, `ANTHROPIC_API_KEY` or `OPENROUTER_API_KEY`, to use Claude (see
`.env.example`). Otherwise everything runs in mock mode: the keyword rule for Finnish levels, and drafts copied from
CV facts, all clearly labelled. Only ad text is sent for the Finnish check; CV facts (never name or contact details)
are sent for drafting, and only with the member's opt-in. Evaluations: `python3 scripts/eval_finnish.py` and
`python3 scripts/eval_drafts.py` (mock by default; live runs cost money).

## Where it runs

**Server (the main copy).** An Oracle Cloud Always Free Ubuntu server at
`https://<server-ip-with-dashes>.sslip.io`, behind an application account. Use it from any phone or
computer.

**Mac (optional).** First run `python3 server.py --provision-admin` to set the local administrator
account, then `python3 server.py` to open http://localhost:8765. Its `data/jobdesk.db` is separate
from the server's, so treat it as a test copy.

Paths, host and port come from environment variables; see `config.py`.

## Setting up the server (once)

1. **Oracle account and server.** Sign up at cloud.oracle.com (Always Free; a card is asked for to
   check identity but Always Free resources aren't charged). Create an instance:
   - Image: **Canonical Ubuntu 24.04**. Shape: the Always Free one offered (`VM.Standard.E2.1.Micro`
     or `VM.Standard.A1.Flex`).
   - Add your Mac's SSH public key (`~/.ssh/id_ed25519.pub`; create it with `ssh-keygen -t ed25519`
     if you don't have one).
   - Note the **public IP address**.
2. **Open the web ports.** Instance → Subnet → Default Security List → Add Ingress Rules: source
   `0.0.0.0/0`, TCP, destination ports `80,443`. (The script opens them in the server's own firewall.)
3. **Check SSH works:** `ssh ubuntu@<ip>`.
4. **Install** from this repo on the Mac:
   ```bash
   JOBDESK_CV_GIT_URL=https://github.com/<you>/cv.git deploy/deploy.sh ubuntu@<ip> --setup
   ```
   It installs Python, git, SQLite, Caddy and the LaTeX packages used by the shared CV template,
   opens the firewall, clones the CV repository named in `JOBDESK_CV_GIT_URL`, configures HTTPS and
   starts the app. It prints the address at the end. The HTTPS certificate is fetched on the first visit.

   Private settings never go in the repo. Put them in `/srv/jobdesk/private.env` on the server (read by
   the service if it exists), for example `JOBDESK_CV_TEMPLATE_OWNER=<the name in the CV template footer>`;
   without it, member CV PDFs are not built. The owner tools (prompt builder, Prep page) read
   `/srv/jobdesk/owner/profile.json` (see `owner_profile.example.json`); without it they answer
   "not set up". Both must be readable by the `jobdesk` user. See `.env.example` for every setting.
5. **Copy your data up**, once:
   ```bash
   deploy/upload-data.sh ubuntu@<ip>
   ```
   The upload provisions the existing owner account without dropping existing tracker data. Sign in
   with a link sent to the owner email, then create invitation codes from **Account**. From then on,
   use the server copy.

To use your own domain instead of sslip.io, point its DNS at the server's IP, then run:
`ssh -t ubuntu@<ip> sudo JOBDESK_DOMAIN=jobs.example.com bash /srv/jobdesk/app/deploy/install.sh`.
If sslip.io's certificate ever fails (Let's Encrypt limits shared domains), a free DuckDNS name
works the same way.

### Migrating an existing server

Deploy the new code normally; the installer removes Caddy Basic Auth and enables JobDesk accounts.
Then set the owner's email on the existing owner record without replacing the server database
(sign-in is by emailed link; old passwords are cleared):

```bash
ssh -t ubuntu@<ip> sudo -u jobdesk env JOBDESK_DATA=/srv/jobdesk/data JOBDESK_CV_REPO=/srv/jobdesk/cv \
  /usr/bin/python3 /srv/jobdesk/app/server.py --provision-admin
```

This preserves existing user 1 and its tracker data. Use `upload-data.sh` only when intentionally
copying a database from your Mac; uploading with `--replace` overwrites all server accounts, CVs,
applications and invitation records with the local database.

## Day to day

| What | How |
|---|---|
| Ship a code change | commit, then `deploy/deploy.sh ubuntu@<ip>` (only committed files are sent) |
| Sign in | Enter your email on the sign-in page and open the link (development mode prints it in the server log) |
| Download a backup to the Mac | `deploy/backup.sh ubuntu@<ip>` → `data/backups/` |
| See the logs | `ssh ubuntu@<ip> journalctl -u jobdesk -n 50` |

What runs on the server (`deploy/systemd/`):

- `jobdesk.service`: the app as the `jobdesk` user, on 127.0.0.1:8765, restarted if it stops.
- `jobdesk-jobs.timer`: the job check (`server.py --check-jobs`) at 06:00 and 15:00 Helsinki time; it also closes
  listings that are over and deletes old employer submissions.
- `jobdesk-pull.timer`: `git pull` of the cv repo every 10 minutes.
- `jobdesk-backup.timer`: a copy of the database every day in `/srv/jobdesk/backups`, 14 kept.
- Caddy (`deploy/Caddyfile`): HTTPS and security headers; JobDesk handles accounts and `X-Robots-Tag`.

## Privacy

Job ads, recruiter names and numbers, the tracker, and employers' submissions live in
`data/jobdesk.db` (git-ignored here too) and on the server in `/srv/jobdesk/data`, readable only by
the `jobdesk` user. There are no passwords: sign-in links are single-use, expire after 15 minutes, are stored only as
SHA-256 hashes and are rate-limited per email and per IP; sessions use HttpOnly, SameSite cookies and HTTPS
Secure cookies on the server. CVs, applications and preferences are scoped to each user. Job listings are shared
with members in the same fields. An employer's contact details are seen only by administrators and deleted 90 days
after the decision on their ad. News stories members saved on the old News page stay in their data download and
nowhere else. Invitation codes are one-time, hashed at rest and
expire after seven days. The site sends `noindex` and refuses cross-site state changes. Oracle hosts
the server, so the data is on their hardware.

## Layout

```
jobdesk/
├── server.py        HTTP server and API routes
├── config.py        paths, host, port (environment variables)
├── db.py            SQLite: users, checks, jobs, applications; numbered migrations (PRAGMA user_version)
├── scraper.py       job feeds (sources.json), classification into fields, the job check
├── taxonomy/        fields.json, roles.json (ISCO-08), places.json (Statistics Finland kunnat/maakunnat)
├── core/taxonomy.py career fields and roles     core/jobmeta.py   job details read from the ad
├── core/places.py   towns and regions           core/dedupe.py    same posting from two sources
├── core/importers.py  API adapters (Työmarkkinatori)
├── search.py        job search shared by Discover and the public pages
├── public.py        public pages: /jobs, landing pages, /job/<id>, sitemap.xml, robots.txt
├── scripts/seed_demo.py  fictional demo jobs for development
├── language.py      Finnish / English / Swedish detection, used by the English switch
├── skills.py        What to study: skills asked for by role type vs. the member's CVs
├── match.py         match score, blockers, employer and PDF links
├── prompt.py        new-CV questions and prompt
├── prep.py          Prep page: reads prep/*.yaml, fills in the job, applies saved answers
├── prep/            call script, questions and blocker answers per job type (YAML subset)
├── ics.py           calendar export
├── facts.py         reads facts.json from the cv repo
├── static/          HTML, CSS, JS (one file per page in static/pages/)
├── tests/           isolated database and HTTP API tests
├── deploy/          install.sh, deploy.sh, upload-data.sh, backup.sh, Caddyfile, systemd/
└── data/            git-ignored: jobdesk.db, backups/
```
