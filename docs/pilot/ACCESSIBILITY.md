# JobDesk pilot: accessibility statement (DRAFT)

> Draft. [Square brackets] must be filled in before the pilot starts.

**Target:** WCAG 2.1 level AA. **Status: partially conforming.** The service has been checked with an automated
tool, but not yet tested by people using assistive technology.

## How it was checked (24 November 2026)

- **Automated:** axe-core 4.10.2 (WCAG 2.1 A and AA rules) on the sign-in page and every page a pilot student uses
  (Jobs, Shortlist with results, Draft an answer, Tracker, What to study, My CVs, Account), in Firefox, light colour
  scheme, desktop width.
- **Result:** three problems were found and fixed: a sorted table header with too little colour contrast, a
  sideways-scrolling Tracker board that couldn't be reached with the keyboard, and a button with too little contrast.
  After the fixes, no automated rule failed.
- **Built in:** visible focus, a "Skip to content" link, form labels, status messages announced to screen readers,
  colour never the only signal (every Finnish-level badge and every UNSUPPORTED sentence also says it in words).

## Not yet checked

- A full keyboard-only walkthrough, and screen readers (NVDA, VoiceOver).
- 200% zoom and 320-pixel-wide screens (reflow); the dark colour scheme.
- Automated tools find only part of all accessibility problems.

## Known limitations

- The interface is in **English only**. Ads and news can be shown in English by the browser's on-device translation,
  which needs desktop Chrome or Edge; other browsers show a note and can use their own "Translate page".
- AI results (the Finnish level, drafted sentences) can be wrong; each shows its evidence so it can be checked.

## Feedback

Report accessibility problems to [email]. We aim to reply within [5 working days]. If you are not satisfied with the
answer, you can contact the supervisory authority: [the current Finnish digital-accessibility supervisor; see
saavutettavuusvaatimukset.fi].
