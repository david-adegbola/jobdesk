# JobDesk pilot: privacy notice (DRAFT)

> **Draft for review by Metropolia's data protection officer.** Everything in [square brackets] must be filled in or
> confirmed before students are invited. This draft describes what the software actually does; it is not legal advice.

## Who is responsible

- **Controller:** [to be agreed: the pilot organiser, or Metropolia University of Applied Sciences]
- **Contact for privacy questions:** [name, email]
- **Pilot period:** [start date] – [end date]. All data is deleted by [deletion date] (see "How long").

## What is stored, and why

| Data | Why | Who can see it |
|---|---|---|
| Name and email address | Your account; signing in with a one-time link sent to your email (no password is stored) | You; the administrator can see that the account exists |
| Settings: your fields, your Finnish level, whether AI drafting is on | Showing the right job ads and ordering the shortlist | You |
| CVs you create | Matching ads to your skills, drafting answers, PDF CVs | Only you |
| Applications you track (status, dates, notes, contacts you add) | The Tracker and reminders | Only you |
| "Was this right?" answers (the Finnish level shown, your yes/no, your correction, the quoted sentence from the ad) | Measuring how accurate the tool is in the pilot | The administrator, as totals and per answer, linked to your account until it is deleted |
| Job ads you save (private: only you see them), and public ads you choose to share | Collecting and comparing opportunities | Saved: only you. Shared: members in that field (your name is not shown) |
| A session cookie (`jobdesk_session`) | Keeping you signed in. It is strictly necessary; there are no analytics or advertising cookies | — |

**Not stored:** the ads you paste on the Shortlist page, and the answers you draft. They are processed for that one
request and then discarded.

## When data leaves the server

| When | What is sent | To whom |
|---|---|---|
| Shortlist and Jobs: checking what an ad says about Finnish | Only the text of the job ad, never your skills, CV or name | [Anthropic's Claude API / OpenRouter, which forwards to Claude. With OpenRouter, only providers that don't store or train on the data are allowed.] |
| Drafting an answer, **only if you turned "AI drafting" on** (off by default) | The question, the job ad, and facts from the CV you chose (education, experience, projects, skills, certificates, languages, hobbies). **Never** your name, email, phone, location or links | Same AI provider |

[The AI provider may process data outside the EU/EEA. The transfer mechanism, and the provider's own retention of
requests, must be confirmed from its current terms and filled in here.]

**Hosting:** [Oracle Cloud Infrastructure, region: …]. Daily backups are kept on the same server for 14 days.

## Legal basis

[To be confirmed by the data protection officer, e.g. consent for taking part in the pilot, and separate consent for
AI drafting, which can be withdrawn at any time by turning it off.]

## How long

Data is kept until you delete your account, or until the pilot ends. On [end date] all student accounts, and
everything in them, are deleted with one command. Backups still containing the data are deleted by [deletion date,
at most 14 days later].

## Your rights

- **See and take a copy of your data:** Account → *Download my data*.
- **Correct it:** edit your CVs, applications and settings at any time.
- **Delete it:** Account → *Delete my account* deletes everything listed above immediately (job ads you shared stay
  visible to others, without your name).
- **Withdraw consent for AI drafting:** Account → turn *AI drafting* off.
- **Complain:** to the Data Protection Ombudsman (tietosuoja.fi), or first to [contact].

## Security

HTTPS only; no passwords (one-time sign-in links that expire after 15 minutes and are stored only as hashes); each student's CVs and applications are visible only to that student;
sign-in emails rate-limited; the site asks search engines not to index it.
