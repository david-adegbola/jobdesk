# Pilot proposal: helping international students find internships they can apply to

*For Metropolia career services and international affairs · Draft, [date] · [name, contact]*

## The problem

In Metropolia's internationalisation survey (954 respondents, results published 6 May 2026), international students
said their **number one concern is employment**. They worried about whether their **Finnish is good enough**, and
asked for **more support with job seeking**
([Metropolia news, 6.5.2026](https://www.metropolia.fi/en/about-us/news/metropolias-international-students-are-satisfied-with-teaching-and-support-and-wish-to-stay-and-work-in-finland)).
Every degree includes practical training, so every student has to find a placement.

Many internship ads mention Finnish, but the wording varies. *"Suomen kielen taito katsotaan eduksi"* (an advantage)
and *"edellytämme sujuvaa suomen kielen taitoa"* (required) look alike to someone who doesn't read Finnish.
Students translate ads one by one, or skip Finnish-language ads and miss ones they could apply to.

## What students get

**JobDesk** is a small web app. Each student has a private account. Five things matter for the pilot:

1. **Shortlist.** Paste up to 20 ads, or links to them. For each ad the student sees whether Finnish is *required*,
   *an advantage*, *not needed* or *unclear*, the exact sentence from the ad it is based on, and how many of their
   skills it mentions. The ads they can realistically apply to come first.
2. **Job ads in their field.** Ads collected automatically, only from public job portals whose robots.txt allows it
   (Valtiolle, Kuntarekry, Jobly's category pages and employer career sites). They cover Metropolia's four fields:
   Technology, Health Care and Social Services, Business, and Culture.
3. **Draft an answer.** Help with application questions such as "Tell us about your work experience". The draft uses
   only facts from the student's own CV. Every sentence is checked against the CV, and sentences the CV doesn't
   support are marked, not hidden. Students opt in to this separately.
4. **Tracker.** Applications, deadlines and follow-up reminders.
5. **What to study.** The skills the ads in their field ask for that their CV doesn't show yet.

## Why it can be trusted

- **Quotes are checked in code:** the app shows the exact sentence it relied on, and code checks that the sentence
  really is in the ad. An invented quote turns the answer into "unclear".
- **Accuracy so far:** measured on 38 hand-labelled ads (30 real ads from Valtiolle and Kuntarekry).
  - The AI (Claude Haiku 5.5) answered "is Finnish required?" correctly on **19 of 20 real ads**.
  - A simple keyword rule got 9 of 20.
  - The set is small, and the pilot would measure accuracy on real use.
- **Students check it:** every result asks "Was this right?", and the pilot reports how often students said yes.

## What the pilot would look like

- **Who:** [20–30] international degree students looking for a practical training place, from [fields/programmes].
- **When:** [6–8 weeks] in [spring 2027], during the internship search period.
- **Start:** a 20-minute introduction (online or on campus), then each student signs in with a single-use invitation
  code.
- **End:** a short survey and an optional 30-minute feedback session. All accounts are then deleted.

## What we need from Metropolia

- A **contact person** in career services or international affairs.
- Help **reaching students**, for example a mention in the international students' newsletter.
- **Review of the privacy notice** by the data protection officer (a draft is ready).
- Optionally, a 15-minute check-in halfway through.

No integration with Metropolia's systems is needed: no sign-in integration and no data from Metropolia.

## How success is measured

| Measure | How |
|---|---|
| Accuracy on real ads | Share of "Was this right?" answers that say yes (the app records this) |
| Usefulness | End survey: did the tool change which ads you applied to? Did it save time? (1–5 scale and free text) |
| Use | Number of students who used the Shortlist more than once; ads checked |
| Applications | Self-reported in the end survey: applications sent to ads previously skipped because of Finnish |

## Data, privacy and accessibility

- **What's stored:** the server stores only what students enter (account, settings, CVs, tracker), visible only to
  them. Pasted ads and drafts are not stored.
- **What's sent to the AI service:** only the ad text, for the Finnish check. CV facts are sent for drafting only
  after the student's own opt-in, and never their name or contact details.
- **Deletion:** students can download or delete their data at any time. Everything is deleted when the pilot ends.
- **Hosting and accessibility:** an EU region [to be confirmed]. Accessibility target WCAG 2.1 AA; automated checks
  pass, and manual testing is still to be done (a draft accessibility statement is ready).

## Cost

- **Hosting:** a free-tier cloud server.
- **AI:** each ad checked is one AI call at a fraction of a cent. For 30 students checking about 100 ads each, the
  **estimate is under €5** in total at current Claude Haiku prices, to be confirmed from the provider's usage report
  after the first week. A daily limit per student caps the cost.
- **Cost to Metropolia:** none.

## Limits, stated up front

- The AI can misread an ad. Students are told to read the ad before applying.
- The interface is in English.
- Job ads come only from sources that allow automated reading, so some employers' ads won't appear. Students can
  always paste any ad themselves.
