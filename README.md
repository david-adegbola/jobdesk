# Woodesk

A multi-user forestry careers portal for students, researchers, forest owners and professionals.
Members share forestry opportunities and news, while CVs, applications and recommendation
preferences stay private to each account. New accounts are invitation-only.

Python 3 standard library, SQLite and plain HTML/CSS/JS: nothing to install.

## Tests

Run `python3 -m unittest discover -s tests -v`. Tests use temporary SQLite files and a local HTTP
server; they cover authentication, ownership boundaries, forestry filtering and API behavior.

## Accessibility requirements

Digital accessibility is a key product requirement. Woodesk targets **WCAG 2.1 Level AA** for
all user-facing flows. Changes should preserve keyboard operation and visible focus, accessible
names and form labels, sufficient text and control contrast, and content reflow at 320 CSS pixels
and 200% zoom. Do not rely on color alone to convey meaning. Verify the affected flow with keyboard
navigation and the available automated and manual accessibility checks; document any known gaps.
This is a development target, not a conformance claim: the complete app has not been independently
evaluated or certified against WCAG 2.1 Level AA.

## Pages

- **For you:** a weekly overview of keyword-matched jobs and recent stories, upcoming job deadlines and follow-ups, plus a combined list of saved jobs and News. Choose one or more audiences (students, researchers, forest owners or professionals), topics and a location to tune the overview. Focus preferences are private to the account. Recommendations are transparent keyword matches, not AI rankings.
- **Jobs:** "Check for new forestry jobs" reads Jobly's Finland-wide forestry, internship
  (`harjoittelija`) and summer-job (`kesatyo`) category pages, waiting 10 s between
  requests as Jobly's robots.txt asks. The source list follows the 2025 forestry internship
  overview. It also checks
  [Metsälehti](https://www.metsalehti.fi/tyopaikat/) (its jobs page when the RSS feed is empty),
  [Metsähallitus](https://metsa.rekrytointi.com/paikat/?o=A_LOJ&list=2),
  [Valtiolle](https://valtiolle.fi/fi/tyopaikat/) (all state agencies, including Luke, MMM, SYKE,
  ELY centres and Maanmittauslaitos),
  [Kuntarekry](https://kuntarekry.fi/fi/tyopaikat/) (municipalities, by keyword search),
  [Metsäkeskus](https://www.metsakeskus.fi/fi/tietoa-meista/toihin-metsakeskukseen/avoimet-tyopaikat),
  [Duunitori's Metsäala search](https://duunitori.fi/tyopaikat?haku=mets%C3%A4ala),
  [Duunitori's Joensuu search](https://duunitori.fi/tyopaikat/alue/joensuu?haku=mets%C3%A4ala),
  [University of Eastern Finland](https://www.uef.fi/fi/avoimet-tyopaikat),
  [Metsä Group](https://metsagroup.wd103.myworkdayjobs.com/fi-FI/MetsaGroup_Careers),
  [UPM](https://upm.wd103.myworkdayjobs.com/fi-FI/Careers) and
  [Stora Enso](https://storaenso.wd502.myworkdayjobs.com/fi-FI/Stora_Enso_site_opportunities).
  Sources are read in **both Finnish and English** (for example `valtiolle.fi/fi/tyopaikat/` and
  `/en/jobs/`, UEF's Finnish and English pages), because English-only postings can be missing from
  the Finnish listing. Duplicates are merged by posting number. Search keywords and filter words
  come in Finnish/English pairs (metsä/forest, puukauppa/timber trade). When you add a source,
  check its fi and en slugs, category tags and robots.txt; the notes are at the top of `scraper.py`.
  RSS descriptions are checked
  as well as titles, and postings are filtered for forestry, forest bioeconomy, natural resources,
  forest-data and geospatial/GIS-related terms.
  RSS descriptions are saved for matching. All results and community submissions are filtered for
  forestry, forest bioeconomy, natural resources, forest data and geospatial/GIS-related terms.
  Community listings are shared, so only public opportunity details should be entered. Older
  non-forestry jobs may remain stored from the previous single-user setup, but members only see
  forestry-related listings. Each job
  shows a 0–100 **Match** against the member's own CVs, the matched words and that member's private
  application status. Administrators refresh shared feeds.
  **Administrator view:** the check also reads the administrator's earlier Jobly searches
  (Industrial, Construction, Warehouse, IT-Data centre). Those jobs, and any non-forestry job the
  administrator adds by hand, are stored in the administrator's account. They are tagged "Only you"
  and never shown to members. `python3 server.py --prune-unrelated-jobs` (add `--apply` to delete,
  after an automatic backup) removes stored jobs that nobody can see.
- **News:** a forestry and forest-bioeconomy news desk focused on Finland and Joensuu/North Karelia,
  with research, industry, policy, climate/nature, markets and forest-tech coverage. Refreshes
  Finnish-language feeds from [Luke](https://www.luke.fi/fi/feed),
  [Metsäteollisuus ry](https://metsateollisuus.fi/feed/) and
  [Tornator](https://www.tornator.fi/feed/), plus Finnish, regional, EU-policy, forest-tech and
  European Forest Institute RSS searches. Search and filter by topic, read status, saved items and
  date; reading-list state is private and persists. Similar headlines published within three days
  are grouped with links to corroborating coverage. Results use source-provided RSS summaries and
  transparent keyword matching, not generated analysis; open each publisher for the full article.
  Refresh is manual and respects source-specific 30–60-minute intervals; source-level errors are
  shown.
- **What to study:** groups the jobs you can see into role types (forest specialist, wood
  procurement, research, GIS and forest data, nature, field work and so on) and lists the skills
  their ads ask for, in Finnish and English, compared with your own CVs. "Study next" shows skills
  that two or more ads mention but none of your CVs shows; each skill shows how many ads ask for it.
  "Start a CV for this role" opens an unsaved draft based on your closest CV, with the role as target
  and the skills still to learn on a "Want to learn" row (never as skills already held). It uses
  keyword matching, not AI; jobs with the full ad saved give better counts than title-only listings.
- **Tracker:** Saved / Applied / Interview / Offer / Rejected, private to the signed-in member. Each card holds the date applied, CV,
  link sent, contact, notes and the next action. Overdue actions are red; "Applied" with no change
  for 5 days shows a `Call <contact>` reminder. Deadlines and interviews export as `.ics`.
- **My CVs:** preview a fictional two-page CV, then create an editable draft from its structure;
  the sample is not saved to the account. Create multiple private Finnish or English CVs with
  profile, education, experience, skills, research/projects, certifications, languages and links.
  Edit, copy or delete a CV, then
  view its formatted PDF using the same LaTeX document layout and shared style as the
  original role CVs. Imported role PDFs are compiled on demand from their original LaTeX source when
  a prebuilt PDF is not present in the CV repository. On startup, Woodesk imports the administrator's
  existing Finnish and English role CVs from the configured CV repository once, including forestry, industrial, IT, sales, trainee
  and warehouse versions. These are editable text copies stored only in the administrator's account.
  Their download uses the exact original, role-specific PDF compiled from the LaTeX source in the
  CV repository. New CVs created by members use that same LaTeX style and document structure:
  centered name and role, contact header, paragraph summary, labeled education and skills rows,
  dated experience entries with indented details, optional Hobbies, and the standard References
  section. Member CV PDFs are compiled on the server from saved data and are not uploaded to the
  shared repository.
- **Account:** change your password, download your private data and sign out. Administrators can
  create single-use, seven-day invitation codes to onboard classmates.

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
   deploy/deploy.sh ubuntu@<ip> --setup
   ```
   It installs Python, git, SQLite, Caddy and the LaTeX packages used by the shared CV template,
   opens the firewall, clones the public CV repository, configures HTTPS and starts the app. It
   prints the address at the end. The HTTPS certificate is fetched on the first visit.
5. **Copy your data up**, once:
   ```bash
   deploy/upload-data.sh ubuntu@<ip>
   ```
   The upload provisions the existing owner account without dropping existing tracker data. Use the
   email/password you set to sign in, then create invitation codes from **Account**. From then on,
   use the server copy.

To use your own domain instead of sslip.io, point its DNS at the server's IP, then run:
`ssh -t ubuntu@<ip> sudo JOBDESK_DOMAIN=jobs.example.com bash /srv/jobdesk/app/deploy/install.sh`.
If sslip.io's certificate ever fails (Let's Encrypt limits shared domains), a free DuckDNS name
works the same way.

### Migrating an existing server

Deploy the new code normally; the installer removes Caddy Basic Auth and enables Woodesk accounts.
Then set credentials on the existing owner record without replacing the server database:

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
| Change your password | Sign in, then use **Account → Change password** |
| Download a backup to the Mac | `deploy/backup.sh ubuntu@<ip>` → `data/backups/` |
| See the logs | `ssh ubuntu@<ip> journalctl -u jobdesk -n 50` |

What runs on the server (`deploy/systemd/`):

- `jobdesk.service`: the app as the `jobdesk` user, on 127.0.0.1:8765, restarted if it stops.
- `jobdesk-pull.timer`: `git pull` of the cv repo every 10 minutes.
- `jobdesk-backup.timer`: a copy of the database every day in `/srv/jobdesk/backups`, 14 kept.
- Caddy (`deploy/Caddyfile`): HTTPS, `noindex` and security headers; Woodesk handles accounts.

## Privacy

Job ads, recruiter names and numbers, the tracker, and News reading-list state live in
`data/jobdesk.db` (git-ignored here too) and on the server in `/srv/jobdesk/data`, readable only by
the `jobdesk` user. Passwords are PBKDF2-hashed; sessions use HttpOnly, SameSite cookies and HTTPS
Secure cookies on the server. CVs, applications, preferences and news read/save state are scoped to
each user. Forestry listings and news are shared. Invitation codes are one-time, hashed at rest and
expire after seven days. The site sends `noindex` and refuses cross-site state changes. Oracle hosts
the server, so the data is on their hardware.

## Layout

```
jobdesk/
├── server.py        HTTP server and API routes
├── config.py        paths, host, port (environment variables)
├── db.py            SQLite: users, checks, jobs, applications
├── scraper.py       Jobly, forestry-sector and Workday job feeds
├── skills.py        What to study: skills asked for by role type vs. the member's CVs
├── news.py          Forestry news RSS feeds and transparent topic matching
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
