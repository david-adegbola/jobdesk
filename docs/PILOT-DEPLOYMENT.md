# Running a JobDesk pilot for Metropolia students

This is the checklist for a pilot server, separate from the administrator's own JobDesk. Everything a student enters
lives on this server only, and is deleted at the end of the pilot.

## 1. A separate server and database

- Use a **new server** (or at least a new data folder and a new domain). Never copy the administrator's own
  `jobdesk.db` to it: that holds personal job searches, CVs and tracker data.
- **Choose and record where the data lives.** On Oracle Cloud the region is chosen when the account is created
  (Console → the region name at the top). For students in Finland, use an EU region, and write the region into the
  privacy notice. The region of the existing personal server hasn't been checked for this document.
- Follow README → "Setting up the server", with the settings below in `/srv/jobdesk/private.env`.

## 2. Settings (`/srv/jobdesk/private.env`, never committed)

```bash
# AI: Shortlist, Jobs "Check Finnish requirements" and drafting (with each student's opt-in)
JOBDESK_LLM_MODE=live
OPENROUTER_API_KEY=sk-or-...            # or ANTHROPIC_API_KEY=sk-ant-...
JOBDESK_LLM_MODEL=claude-haiku-5-5      # the evaluated model; claude-opus-5-5 is stronger and costs more
JOBDESK_AI_DAILY_LIMIT=200              # AI checks per student per day on the Shortlist page

# Until a student chooses, show all of Metropolia's fields
JOBDESK_DEFAULT_FIELDS=it,engineering,health,business,culture

# The administrator's own tools stay off: point the owner folder at an empty directory
JOBDESK_OWNER_DIR=/srv/jobdesk/no-owner

# Member CV PDFs: the name in the LaTeX template's footer (see "CV repository" below)
JOBDESK_CV_TEMPLATE_OWNER=...
```

**CV repository.** On every start, JobDesk imports the CVs it finds in `JOBDESK_CV_REPO/roles/` into the
administrator account. On a pilot server, point `JOBDESK_CV_REPO` at a copy that contains **only**
`shared/cv-style.sty` (the template), not anyone's CVs. Member PDFs need that template, and nothing else from the
repository.

**AI provider.** With OpenRouter, JobDesk only allows providers that don't store or train on the data
(`data_collection: "deny"`). Whichever provider is used, read its current data-processing terms and name it in the
privacy notice. Only ad text is sent for the Finnish check. CV facts are sent for drafting, and only for students who
turned AI drafting on.

## 3. Accounts

```bash
# The administrator (once)
sudo -u jobdesk env $(cat /srv/jobdesk/app/deploy/jobdesk.env /srv/jobdesk/private.env | xargs) \
  /usr/bin/python3 /srv/jobdesk/app/server.py --provision-admin

# One single-use invitation code per student, valid for the sign-up period (here 30 codes, 30 days)
sudo -u jobdesk env $(cat /srv/jobdesk/app/deploy/jobdesk.env /srv/jobdesk/private.env | xargs) \
  /usr/bin/python3 /srv/jobdesk/app/server.py --create-invitations 30 --days 30
```

Give each student one code, directly (not in a shared list). A code works once.

## 4. During the pilot

- **Job ads:** sign in as administrator and use **Check for new jobs** (Jobs page). It reads only the fields students
  have chosen, checks robots.txt before every request, and waits between requests.
- **Finnish levels:** **Check Finnish requirements (AI)** on the Jobs page classifies up to 25 saved ads per click.
- **Accuracy from students:** `GET /api/finnish/feedback/summary` (administrator only) gives the share of "Was this
  right?" answers that said yes, for the AI and for the keyword rule.
- **Cost:** each ad checked is one AI call. With Claude Haiku 5.5 through OpenRouter, the 38-ad evaluation cost a few
  cents. The daily limit caps what one student can use.

## 5. End of the pilot (retention)

```bash
# 1. See how many accounts would go (nothing is deleted)
... server.py --delete-member-accounts
# 2. Delete every student account and everything in it (a backup is taken first)
... server.py --delete-member-accounts --apply
# 3. Check the result, then delete the backups, which still contain the students' data
sudo rm -f /srv/jobdesk/data/backups/jobdesk-before-deleting-members-*.db
sudo rm -f /srv/jobdesk/backups/*.db
```

The daily backup timer keeps 14 copies. Unless step 3 is done, student data stays in backups for up to 14 days.
The privacy notice should state the date by which all data is gone.

## 6. Before inviting students

- [ ] Privacy notice published and linked (draft: `docs/pilot/PRIVACY-NOTICE.md`), with the server region and the AI provider filled in
- [ ] Metropolia contact person agreed; their data protection officer has seen the notice
- [ ] Accessibility statement published (draft: `docs/pilot/ACCESSIBILITY.md`)
- [ ] A test student account walked through: setup card → fields → CV → Shortlist → Draft → Delete account
- [ ] Invitation codes created and handed out
- [ ] End date and deletion date written down
