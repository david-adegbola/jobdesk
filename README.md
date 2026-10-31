# JobDesk

David's private job dashboard. It finds jobs on Jobly, tracks applications, matches each job to the
best CV and writes the prompt for the next tailored CV.

This repo is **private**. The CVs live in the public [cv repo](https://github.com/david-adegbola/cv),
and JobDesk only reads from it: the `roles/` folders (titles, keywords, languages) and `facts.json`
(name, contact details, what David does and doesn't hold). It runs none of the cv repo's code and
never writes to it. A new CV pushed to the cv repo shows up here on the next pull.

Python 3 standard library, SQLite and plain HTML/CSS/JS: nothing to install.

## Tests

Run `python3 -m unittest discover -s tests -v`. Database tests use temporary SQLite files and
exercise data isolation across 100 users; the HTTP API tests use only a local test server.

## Pages

- **Jobs:** "Check for new jobs" reads Jobly's Finland-wide category pages, waiting 10 s between
  requests as Jobly's robots.txt asks. "Add job manually" is for jobs from anywhere else. Each job
  shows a 0–100 **Match** with the matched words, red **Blockers** (what the ad asks that David
  doesn't have yet), the **CV** to send and its **Status**.
- **Tracker:** Saved / Applied / Interview / Offer / Rejected. Each card holds the date applied, CV,
  link sent, contact, notes and the next action. Overdue actions are red; "Applied" with no change
  for 5 days shows a `Call <contact>` reminder. Deadlines and interviews export as `.ics`.
- **CVs:** every role with its language (fi-first, en-first or en-only, from its `job.md`), its PDF
  links (the file to send first), employer link (copy button), last update and how many applications
  used it. On the Jobs page, "Use CV" marks roles that open in English ("EN first", "EN only").
- **New CV prompt:** pick a job or paste an ad. It asks what your facts don't answer, then writes the
  Claude Code prompt for the cv repo. Its Language choice (en-first for ads written in English,
  otherwise fi-first) sets the role's language, the emails and the commit message.
- **Prep:** for one job (the "Prep" link on the Jobs page, and on tracker cards at Applied or
  Interview): a call script in Finnish with the English underneath ("Copy call script"), 8–10 likely
  questions with draft answers, an honest answer for each of the job's blockers, and questions to ask.
  No AI: the templates are in `prep/` (one file per job type), with drafts built only from the
  CV-RULES.md facts. Answers you edit are saved per job type and reused for the next job. "Print"
  gives a clean sheet.
- **Insights:** the most common blockers (what to learn next) and the funnel per CV.

## Where it runs

**Server (the main copy).** An Oracle Cloud Always Free Ubuntu server at
`https://<server-ip-with-dashes>.sslip.io`, behind a login. Use it from any phone or computer.

**Mac (optional).** `python3 server.py` opens http://localhost:8765. It reads `../CV` and keeps its
own `data/jobdesk.db`, separate from the server's, so treat it as a test copy.

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
   It installs Python, git, SQLite and Caddy, opens the firewall, clones the cv repo, asks for a
   login name and a password (16+ characters; use a password manager), and starts everything. It
   prints the address at the end. The HTTPS certificate is fetched on the first visit.
5. **Copy your data up**, once:
   ```bash
   deploy/upload-data.sh ubuntu@<ip>
   ```
   From then on, use the server copy.

To use your own domain instead of sslip.io, point its DNS at the server's IP, then run:
`ssh -t ubuntu@<ip> sudo JOBDESK_DOMAIN=jobs.example.com bash /srv/jobdesk/app/deploy/install.sh`.
If sslip.io's certificate ever fails (Let's Encrypt limits shared domains), a free DuckDNS name
works the same way.

## Day to day

| What | How |
|---|---|
| Ship a code change | commit, then `deploy/deploy.sh ubuntu@<ip>` (only committed files are sent) |
| Change the password | `deploy/deploy.sh ubuntu@<ip> --setup` (asks again; keeps the data) |
| Download a backup to the Mac | `deploy/backup.sh ubuntu@<ip>` → `data/backups/` |
| See the logs | `ssh ubuntu@<ip> journalctl -u jobdesk -n 50` |

What runs on the server (`deploy/systemd/`):

- `jobdesk.service`: the app as the `jobdesk` user, on 127.0.0.1:8765, restarted if it stops.
- `jobdesk-pull.timer`: `git pull` of the cv repo every 10 minutes.
- `jobdesk-backup.timer`: a copy of the database every day in `/srv/jobdesk/backups`, 14 kept.
- Caddy (`deploy/Caddyfile`): HTTPS, the login, `noindex` and other security headers.

"Build PDFs" on the CVs page needs `pdflatex`, which the server doesn't have. The cv repo's GitHub
Action builds the PDFs anyway.

## Privacy

Job ads, recruiter names and numbers, and the tracker live in `data/jobdesk.db` (git-ignored here
too) and on the server in `/srv/jobdesk/data`, readable only by the `jobdesk` user. Nothing is
published. The whole site is behind the login, sends `noindex`, and refuses changes sent from other
websites. Oracle hosts the server, so the data is on their hardware.

All data access is in `db.py`. Every table has a `user_id` column (default 1), so a later version
could support more users.

## Layout

```
jobdesk/
├── server.py        HTTP server and API routes
├── config.py        paths, host, port (environment variables)
├── db.py            SQLite: users, checks, jobs, applications
├── scraper.py       Jobly reader
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
