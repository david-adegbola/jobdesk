# Changes explained

One section per phase of the "student jobs + LLM" work. Each section says what changed, why, how
the code works step by step, and what an interviewer might ask.

---

## Phase 1: Fix known problems and decouple from one person

### 1. The CV slug bug

**What changed.** `enrich()` in `server.py` now returns `use_cv_slug` next to `use_cv`. The Prep
route and the email-prompt route use the slug.

**Why.** Every CV ("role") has two names: a *slug* such as `trainee-master` (the folder name, used
as a key in code) and a *title* such as "Trainee CV" (for people). `enrich()` only returned the
title. `prep.type_for()` looks the CV up in a dictionary keyed by slug, so it never found it and
quietly fell back to the job's category. `build_email()` looked for a role whose slug equalled the
title, found none and reported "CV to send" as missing.

**How it works.**
1. `enrich()` scores the job against every CV with `match.match()` and picks the best one.
2. It returns both `use_cv` (title, shown on screen) and `use_cv_slug` (key, used by code).
3. `api_prep` calls `prep.type_for(e["use_cv_slug"], ...)`, and `api_email_prompt` stores
   `use_cv_slug` as `suggested_cv`.

**Test.** `test_prep_and_email_prompt_look_up_the_cv_by_slug_not_title` uses a job whose category
(Warehouse) points one way and whose best CV (trainee-master) points another. Before the fix the
Prep page said "warehouse"; now it says "trainee".

**Interview questions.**
- *Why didn't any test catch this?* The routes were admin-only and tests replaced `context()` with
  empty roles, so the code path with a real match never ran. The new test gives it a real match.
- *How would you stop this class of bug?* Don't pass display strings where identifiers are
  expected: return both explicitly, or pass the whole object.

### 2. Request bodies that aren't JSON objects

**What changed.** The prompt routes and `/api/prep/answer` now return **400** when the body (or
its `job`/`answers` field) isn't a JSON object, or when prep answers aren't text. `Handler.json()`
also treats bytes that aren't valid UTF-8 as an empty body instead of crashing.

**Why.** `body.get(...)` on a list or a string raises `AttributeError`. The dispatcher only caught
`KeyError`, so the request died with no proper answer. Invalid UTF-8 raised `UnicodeDecodeError`,
which isn't a `JSONDecodeError`, so it got through the old `except` too.

**How it works.** `_prompt_body(h)` reads the body and returns it only when it is a dict and its
`job` and `answers` are dicts (or absent). Otherwise the route returns
`400 "The request body must be a JSON object."` before touching the database.

**Interview question.** *Why validate at the route rather than deeper down?* The route is the
trust boundary: everything after it can assume well-formed input, and a bad request is rejected
before any work or database access happens.

### 3. Missing facts.json no longer stops the request

**What changed.** `facts.load()` raises `FactsUnavailable` instead of `SystemExit`. The
dispatcher turns it into **503** with a short message, and server start-up prints a warning and
keeps running.

**Why.** `SystemExit` inside a request handler thread ends that thread without a response, so the
browser got a dropped connection. At start-up it stopped the whole server, which matters now that
facts.json is only needed by the owner tools.

**How it works.** The dispatcher has
`except (facts.FactsUnavailable, owner.OwnerProfileMissing): send 503`. The message sent to the
browser doesn't include the server's file path; the full path goes to the server log (stderr).

**Interview question.** *Why 503 and not 500?* 500 means "the code failed". 503 means "this
service isn't available here", which is what a missing configuration file is, and the message
tells the administrator what to fix.

### 4. robots.txt on every automatic request; Duunitori off

**What changed.**
- New `core/robots.py` with a `RobotsCache` class.
- `scraper.fetch()`, `fetch_workday_jobs()` and `fetch_ad_text()` check it before every request
  and skip disallowed URLs (logged as "skipped (robots.txt)").
- Jobly's wait between pages is now the larger of 10 s and the site's `Crawl-delay`.
- Duunitori's two search pages are read only when `JOBDESK_ENABLE_DUUNITORI=1` (default off).

**Why.** The scraper's own comment said Duunitori disallows generic crawlers, yet it read
Duunitori anyway. A tool that tells students to be honest should follow the sites' rules itself.

**How it works.**
1. `RobotsCache.allowed(url)` works out the site (`https://host`) and looks in its cache.
2. On a miss it downloads `https://host/robots.txt` through the function it was given
   (`scraper._fetch_robots`), which returns the HTTP status and the text.
3. The status decides, following RFC 9309 with one stricter rule:
   - 2xx: parse the rules with Python's `urllib.robotparser`;
   - 401/403: disallow everything;
   - other 4xx (e.g. 404, no file): allow everything;
   - 5xx, network error, or a fetcher that raises: disallow everything.
4. The result is cached per site for six hours (`CACHE_SECONDS`).
5. `can_fetch("JobDesk", url)` gives the answer: rules under `User-agent: JobDesk` apply if present,
   otherwise those under `User-agent: *`.

`RobotsCache` has no network code: the download function is passed in. That is why
`tests/test_robots.py` can test every status code without the internet, and why it lives in
`core/`, the package that must also work in the separate Flask app.

**Test changes to existing tests.**
- `tests/test_scraper.py` setUp now replaces the robots check with "allow" so no test touches the
  network.
- `test_run_imports_only_forestry_related_jobs_from_added_sources` now expects 7 jobs, not 8, and
  no Duunitori source, because Duunitori is off by default. This is the behaviour change you asked for.

**Interview questions.**
- *Is robots.txt legally binding?* Not as such. It is the site's stated wish, and ignoring it can
  breach a site's terms of use. Respecting it is the honest default for a low-volume tool.
- *Why disallow everything when robots.txt can't be fetched?* If the server is down or erroring we
  can't know its rules. Not reading is the safe choice, and we try again after the cache expires.
- *Known gap:* the scraper's HTTP `User-Agent` header still says "Mozilla/5.0 (personal job check;
  low volume)", while robots rules are matched with the token "JobDesk". A more honest set-up
  would send a `JobDesk/1.0 (+contact URL)` header. That is left as a decision, because some sites
  may treat a non-browser header differently.

### 5. Personal details moved out of the code

**What changed.**

| Before (hard-coded) | Now |
|---|---|
| CV repo name and public CV address in `prompt.py`, `match.py` | `owner/profile.json` (git-ignored), read by `owner.py` |
| Tailoring lines about one specific job | `summary_lead` and `tags_job` in the profile |
| Footer name in `cv_latex.py` | `JOBDESK_CV_TEMPLATE_OWNER` environment variable; if unset, member PDFs are refused |
| Personal interview answers in `prep/*.yaml` | Generic templates in `prep/`; personal ones in `owner/prep/` (git-ignored), used automatically when present |
| CV repo URL in `deploy/install.sh` | `JOBDESK_CV_GIT_URL` passed from `deploy.sh --setup` |
| Default admin name in `db.py`, calendar PRODID, comments | Neutral wording |

New files: `owner.py`, `owner_profile.example.json`, `.env.example`. The server reads private
values from `/srv/jobdesk/private.env` (optional `EnvironmentFile` in the systemd unit).

**How the owner profile works.**
1. `owner.load()` reads `owner/profile.json`. If it is missing, or lacks `cv_repo` or
   `public_cv_base`, it raises `OwnerProfileMissing`.
2. `prompt.build()` and `build_email()` call `owner.load()` first, so without a profile the route
   answers 503 "not set up" instead of producing a prompt with someone else's details.
3. `match.employer_link()` and `pdf_links()` use `owner.get()`, which returns an empty string when
   the value is missing, so other pages keep working.

**Why the CV footer "fails closed".** The shared LaTeX template prints its owner's name in the
footer, and member PDFs replace it with the member's name. If the configured name isn't set, or
isn't in the template, the code refuses to build. Otherwise the wrong person's name could end up
on someone's CV.

**Important: git history.** Removing personal text from the current files does not remove it from
earlier commits. If this repository is or becomes public, the old answers are still visible in
its history. Rewriting history (e.g. `git filter-repo`) is a separate, deliberate decision.

**Interview questions.**
- *Why a JSON file and not more environment variables?* The profile has several related text
  values, some long. A JSON file is easier to read and edit; secrets would still go in environment
  variables.
- *Why keep the owner tools at all?* They are useful to the administrator. They are now opt-in
  through configuration and can't leak one person's data into other people's output.

---

## Phase 2: Core package, Finnish classifier and evaluation

### The `core/` package

**What it is.** A folder of modules that the JobDesk server and a separate Flask app can both
import. Three rules, checked by `tests/test_core_package.py` (which reads every file's imports with
Python's `ast` module):
1. standard library only;
2. no imports from JobDesk's own modules (server, db, config, match, scraper …);
3. nothing happens at import time (no network, no files, no subprocesses).

| Module | What it does |
|---|---|
| `core/text.py` | `tokens`, `stem`, `word_matches` and word lists, moved from match.py |
| `core/language.py` | fi/en/sv detection, moved from language.py |
| `core/fetch.py` | safe single-page fetch (public addresses only, robots.txt, honest User-Agent), moved from scraper.py |
| `core/robots.py` | robots.txt cache (Phase 1) |
| `core/llm.py` | Claude API client over `urllib` |
| `core/finnish.py` | `baseline_v1`, `classify`, `fallback`, the evidence check |
| `core/batch.py` | many ads from pasted text, CSV or URLs |
| `core/rank.py` | ranked shortlist against a student's skills |
| `core/evaluate.py` | accuracy, confusion matrix, precision/recall, Markdown report |

**Why "move and re-export".** `match.py` now does `from core.text import tokens, …`, and
`language.py` just re-exports `core.language`. Every existing `match.tokens(...)` or
`language.detect(...)` call works unchanged, and a test checks they are the very same functions
(`assertIs`).

**Why fetch.py had to move.** Importing `scraper.py` runs a macOS command to load certificates and
imports the database layer, so the Flask app can't import it. The fetch code now has its
dependencies passed in: `fetch_ad_text(url, allowed, context, agent)` *requires* the robots.txt
check as an argument, so no caller can forget it.

### Honest User-Agent

The scraper used to say `Mozilla/5.0 (personal job check; low volume)`, which looks like a browser.
It now sends `JobDesk/1.0 (job-ad reader for students in Finland; low volume)`, plus
`; +<url>` when `JOBDESK_CONTACT_URL` is set. robots.txt rules are matched on the same name,
"JobDesk". Some sites may answer differently to a non-browser client; if a source stops returning
jobs, check that first.

### The LLM client (`core/llm.py`)

Step by step for one live call:
1. `settings_from_env()` reads `JOBDESK_LLM_MODE` (mock by default), `ANTHROPIC_API_KEY`,
   `JOBDESK_LLM_MODEL` (default `claude-opus-5-5`) and `JOBDESK_LLM_EFFORT` (default `low`).
2. `build_request()` makes the JSON body: the model, the system prompt, one user message and
   `output_config.format = {"type": "json_schema", "schema": …}`. This is "structured outputs":
   the API guarantees the reply is valid JSON in exactly that shape.
3. The request goes to `https://api.anthropic.com/v1/messages` with the headers `x-api-key` and
   `anthropic-version: 2026-10-21`.
4. 429 (rate limit), 5xx and network errors are retried up to 2 times. The wait is the API's
   `retry-after` header if it sent one, otherwise 1 then 2 seconds.
5. `stop_reason` is checked: `refusal` and `max_tokens` become errors. The text block is parsed
   as JSON (thinking blocks are skipped).

**No temperature.** You asked for "low temperature", but API version 2026-10-21 rejects the
`temperature` parameter on every model. Steadiness comes instead from the fixed JSON schema, low
effort and, above all, the evidence check in code.

**Refusal fallback.** For models that support it, the request includes `fallbacks: "default"` with
the beta header `server-side-fallback-2026-07-01`. If a safety classifier wrongly declines an
ordinary job ad, the API retries on a fallback model in the same call. Set
`JOBDESK_LLM_FALLBACKS=0` to turn this off.

**Safety of secrets.** `Settings.api_key` is excluded from `repr()`. Error messages carry only the
HTTP status and the API's error type, never the prompt, the ad or the key (a test checks this).

**Mock mode.** `call_json` refuses to run unless the mode is "live" and a key is set. In mock mode
the *caller* builds a fake answer locally, labelled `[MOCK OUTPUT – not a model result]`.

### The Finnish classifier (`core/finnish.py`)

**baseline_v1** is the old regex from match.py, copied character for character. A test compares it
with match.py so it can't drift. It returns "required" or "not_required". Its known flaw is kept on
purpose: "hyvä suomen kielen taito katsotaan eduksi" (good Finnish is an advantage) comes out as
"required".

**classify(ad_text)**, step by step:
1. Empty ad: "unclear", no API call. Longer than 50,000 characters: `ValueError` (never silently cut).
2. Mock mode: find the first sentence that mentions a language, quote it, level "unclear", and
   label the explanation as fake. The evidence check still runs.
3. Live mode: send the prompt from `core/prompts/finnish_level.md` as the system prompt and the ad
   inside `<job_ad>` tags as the user message. The prompt says the ad is data, not instructions,
   which is the defence against an ad that says "ignore your rules".
4. `check()` applies the rules in code:
   - level not one of the four, or evidence not a list: **unclear**;
   - any quote not found in the ad (after collapsing whitespace, nothing else): **unclear**, with
     the bad quote kept in `rejected_evidence`;
   - required / preferred / not_needed with no quote: **unclear**;
   - otherwise the model's answer is kept and marked `verified: true`.

**fallback(ad_text)** is what screens use when the LLM is off: baseline_v1 in the four-level shape.
"not_required" becomes "unclear", never "not_needed", because the regex can't tell "preferred"
from "not needed", and telling a student "Finnish not needed" on a guess would be worse than
saying "unclear".

### Batch input (`core/batch.py`)

- **Pasted text**: ads separated by a line of `---`; the first line is the title.
- **CSV**: columns `id, title, url, ad_text`. A row needs text or a link, and `fill_from_urls()`
  fetches the rows that only have a link.
- **URLs**: one per line, at most 25. The fetcher is passed in. In JobDesk it is
  `core.fetch.fetch_ad_text` with the robots.txt check, so the SSRF guard and robots.txt both apply.

Problems never stop the batch: each reader returns `{"ads": […], "errors": […]}`, so 19 good ads
and one clear message about the 20th.

### Ranking (`core/rank.py`)

For each ad:
1. **Skills**: a skill such as "remote sensing" counts when *every* significant word of it matches a
   word in the ad, using the Finnish-aware `word_matches` ("paikkatieto" matches
   "paikkatietoaineistoista"). One- and two-letter skills such as "R" need a whole-word match, or
   "R" would match "rooli". `skill_score = 100 × matched / all skills`.
2. **Finnish tier**: not_needed 0, preferred 1, unclear 2, required 3. Required ads are sorted last,
   not hidden. A student who says they are fluent gets tier 0 everywhere; the level is still shown.
3. **Sort** by tier, then skill score, then skills in the title.

Each row has `reasons`, e.g. *Matches 2 of your 4 skills: QGIS, remote sensing.* and
*Finnish is an advantage, not a requirement – the ad says: "…".*

### Evaluation

- `data/eval/ads.jsonl`: 3 invented example rows (one per level apart from unclear), including the
  case baseline_v1 gets wrong. You add real labelled rows; `data/eval/GUIDE.md` defines the labels,
  with examples and tricky cases.
- `.gitignore` now ignores `data/*` except `data/eval/`, so the dataset can be committed while the
  database still can't.
- `tests/test_evaluate.py` checks every row: valid label, unique id, and evidence that really is a
  quote from the excerpt.
- `python3 scripts/eval_finnish.py` writes `reports/finnish-eval-<date>-<mode>.md` with:
  - **four levels** (LLM only, since baseline_v1 can't answer four levels): accuracy, confusion
    matrix, precision and recall per class;
  - **collapsed** required vs not_required for both classifiers. Ads labelled "unclear" are left
    out and counted. An LLM "unclear" on a kept ad appears as its own column and counts as wrong;
  - **every disagreement**, with the excerpt and the quotes.

**Precision and recall in one line each.** Precision: of the ads the classifier called "required",
how many really were. Recall: of the ads that really were "required", how many it caught. For
students, low *precision* on "required" hides open jobs from them, and low *recall* sends them to
jobs they can't get.

**Interview questions.**
- *Why verify quotes in code instead of trusting the model?* The model's level is only as good as
  its reading of the ad. Requiring an exact quote turns "trust me" into something checkable. A
  wrong quote is the clearest sign of a made-up answer, so the result is downgraded to "unclear".
- *What can the quote check not catch?* A real quote with a wrong level, e.g. quoting "…katsotaan
  eduksi" and calling it "required". The evaluation's confusion matrix measures that.
- *Why is the mock mode built by the caller and not by the LLM client?* Each feature knows what a
  realistic fake answer looks like; the client only knows HTTP.
- *Three examples isn't an evaluation.* Correct: they show the format and the known failure. The
  numbers become meaningful once you've labelled real ads, ideally 100 or more with a mix of
  levels and languages.
