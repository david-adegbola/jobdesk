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

**A second bug the new test found.** `enrich()` also read `cv["id"]`. Member CVs have an id, but
the CV-repository roles used by the owner tools don't, so whenever a repository CV matched a job,
`enrich()` raised `KeyError`, and the dispatcher turned that into **404**. The Prep and
email-prompt pages failed exactly when they had something useful to show. It now uses
`cv.get("id")`.

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

---

## Phase 3: More fields than forestry

### Field profiles (`fields/*.json`, read by `core/fields.py`)

**What changed.** What "a forestry job" means used to be several Python lists in `scraper.py` and
`skills.py`. It is now one JSON file per field: `forestry`, `it`, `engineering`, `health`,
`business`. Each profile has:

| Key | Used for |
|---|---|
| `label_en`, `label_fi`, `category` | names; `category` is the "Type" shown on the Jobs page |
| `search_terms` | keyword searches on portals that search by word (Kuntarekry) |
| `jobly.slugs`, `jobly.title_words` | Jobly category pages to read, and words a title must contain |
| `relevance.words` / `core_words` / `whole_words` / `ignore_patterns` | deciding whether a job belongs to the field |
| `skills` | "What to study": skills with a Finnish + English regex and a study hint |
| `role_types` | "What to study": groups of jobs by title |

**How forestry kept today's behaviour.** `fields/forestry.json` wasn't typed by hand. A short script
imported the old Python constants and wrote them out as JSON, so the lists are exact copies. All
127 earlier tests then ran against the JSON-driven code unchanged and passed. That is the evidence
that nothing about forestry changed.

**How a job is matched to a field** (`core.fields.is_relevant`), depending on its source's *kind*:
1. `field_board` (Metsälehti): everything it lists belongs to its fields.
2. `broad_portal` (Valtiolle, Kuntarekry): every public-sector job in Finland. Words like
   "tietojärjestelmä" appear in police ads too, so the **title** must contain a field word, or the
   **ad text** one of the stricter `core_words`.
3. everything else: the title, description, ad or location must contain a field word.

Words are lower-case substrings ("metsänhoit" matches "metsänhoitaja"); `whole_words` must stand
alone ("gis" must not match "logistiikka").

**Word collisions found while writing the new profiles** (each now has a test):
- health never uses bare "hoitaja", which is inside "metsän**hoitaja**" (forester);
- business never uses bare "talous" or "hankinta", which are inside "metsä**talous**", "bio**talous**"
  and "puun**hankinta**";
- IT never uses bare "it", which is an English word ("let it be"); it uses "it-tuki", "it support" etc.

### Job sources as configuration (`sources.json`)

Every source now has: `fields` (a list, or `"all"`), `kind`, `reader` (which parser to use), its
URLs, and notes on what its robots.txt and terms say. `scraper.sources(field_ids)` builds the list
of readers for the fields being scraped.

**Which fields are scraped.** Only the fields at least one member has chosen
(`db.active_field_ids`). With nobody choosing IT, nothing is fetched for IT, so no requests or time
are spent on fields nobody uses.

**What was checked before adding sources** (on 2026-11-24, recorded in `sources.json`):

| Site | robots.txt | Decision |
|---|---|---|
| Jobly | allows `/tyopaikat/`, `Crawl-delay: 10` | Added the verified category pages `sairaanhoitaja`, `lahihoitaja` (health), `ohjelmistokehittaja` (IT), `insinoori` (engineering), `kirjanpitaja` (business). **Jobly's terms couldn't be read** (the terms page needs sign-in); read Alma Media's general terms before deploying. |
| Valtiolle, Kuntarekry | `Allow: /`, both offer RSS | Now used for every field; Kuntarekry searches each field's `search_terms`. |
| UEF, Metsä Group, UPM, Stora Enso | (checked automatically at fetch time) | Now `fields: "all"`: they hire IT, engineering and business people too. |
| Duunitori | `Disallow: /` for generic bots | Stays off. |
| Työmarkkinatori | public pages allowed, `/api/` disallowed | **Not added.** The official route is KEHA's job-ad API, which needs registration and forbids passing ads on without permission. Apply for access (tmt-rajapinnat@keha-keskus.fi) rather than scraping. |

### Members choose fields

- New Account section "Fields and Finnish": checkboxes for fields and a Finnish level
  (none / basic / intermediate / fluent), saved by `POST /api/account/fields` into the member's
  private preferences. Members who haven't chosen get `forestry`, so nothing changes for existing members.
- **Visibility rule** (`server.can_see`):
  - *personal* jobs (the administrator's own Jobly categories and jobs they added outside every
    field) are visible only to that administrator, even if they happen to match a member's field;
  - every other job is visible to members whose fields it belongs to.
- A Valtiolle job that is both forestry and IT shows as "IT" to an IT member: the Type comes from the
  first of *their* fields it matches.
- "What to study" uses the member's fields' skills and role types.
- **A bug fixed on the way:** the "For you" page saved preferences by replacing the whole object, so
  it would have wiped the chosen fields. It now merges.

### Finnish level on the Jobs page

**What the member sees.** A "Finnish" column with *Finnish required / an advantage / not needed /
unclear*, the sentence it is based on, and how it was decided: "AI; the quote was checked against
the ad" or "keyword rule". The words carry the meaning; colour only repeats it, for accessibility.
A filter can hide "Finnish required", or show only "not needed / an advantage".

**Where the level comes from** (`server.finnish_for`):
1. If an LLM result is stored for this job **and** was made from the same text (a SHA-256 hash of
   title + ad text matches), show it.
2. Otherwise show `core.finnish.fallback`, the old keyword rule. It can only say "required" or
   "unclear", never "not needed", because it can't tell the difference.

**How LLM results get stored.** An administrator clicks "Check Finnish requirements (AI)". The
button only appears in live mode, and the route refuses in mock mode. A background thread then
classifies up to 25 shared jobs that have saved ad text and no current result, and stores each in
the new `finnish_levels` table (keyed by job and prompt version). Only the **ad's own text** is
sent: never a CV, never personal jobs, never title-only listings.

**Interview questions.**
- *Why store a hash of the text?* If an ad is re-fetched with different text, the old answer may
  be wrong. Comparing hashes notices that without storing the text twice.
- *Why is classification an admin action and not automatic?* Each ad is a paid API call. Batches of
  25 make the cost visible and controllable. Results are shared, so every member benefits from one
  call per ad.
- *Why only fields members chose?* Least work and least load on other people's servers.
- *What's still weak?* The keyword lists for the new fields were written by hand and have only been
  checked against the test titles. Run a scrape for one field and read what comes back before
  trusting it.

---

## Phase 4: Application answers grounded in the CV

### The idea in one paragraph

Students are asked free-text questions such as "Tell us about your previous work experience". An
LLM can write a fluent answer, but fluent text can include things that aren't true: a longer job,
a card the student doesn't have, a skill they are only learning. So the model must **cite a CV fact
for every sentence**, and code then **checks each sentence against the facts it cites**. Sentences
that fail are kept and marked UNSUPPORTED, never silently removed or kept, and the student edits
the draft before using it anywhere.

### Step by step (`core/draft.py`)

1. **CV → facts** (`core/cv_facts.py`). The CV's sections become numbered facts:
   `sum-1` (summary paragraphs), `edu-1`, `exp-1` (one per job: heading + details, "Tags:" lines
   removed), `proj-1`, `skill-1`, `cert-1`, `lang-1`, `hob-1`. "Want to learn: …" rows are **not**
   facts; they go in a separate `learning` list. **Name, email, phone, location, links and target
   role are never included**, because the model doesn't need them to answer the question
   (data minimisation).
2. **What the ad asks for but the CV doesn't show** (`core/blockers.py`): the same licence / card /
   qualification / fluent-Finnish patterns as before, now without anyone's personal facts. A
   requirement counts as missing when no CV fact matches its pattern.
3. **Live mode**: the system prompt (`core/prompts/grounded_answer.md`) gives the rules. The user
   message carries the ad, question, facts, `<not_held>` and `<ad_asks_for_but_cv_lacks>` in tags,
   marked as data, not instructions. The answer comes back in a fixed JSON shape
   `{"sentences": [{"text", "fact_ids"}]}` (structured output).
   **Mock mode**: the three facts sharing most words with the question are copied as sentences,
   each starting `[MOCK OUTPUT – not a model result]`.
4. **Verification** (`core/verify.py`): every sentence is checked (below).
5. **Word count** against the limit; `over_limit` is reported, not enforced by cutting text.

### The five checks (`core/verify.py`)

| Check | Catches | Example flagged |
|---|---|---|
| cites at least one fact, and every cited id exists | sentences with no CV basis | "I am a hard-working team player." (no id) |
| shares at least one key word with the cited facts | made-up content | "I managed a sawmill budget." citing a field-assistant job |
| every number is in the cited facts | inflated figures and dates | "I measured **120** plots" when the CV says 40 |
| no claim of a missing requirement, unless it says "not yet" / "want to learn" | claimed cards and licences | "I hold a B driving licence." |
| no want-to-learn item presented as held | skills turned from wish into fact | "I have production experience with Kubernetes." |

"Key words" leaves out stop words, words under 4 letters and generic application words
("experience", "motivated", "kokemusta"…), so a sentence can't pass by sharing only "experience".
Finnish case endings still match ("taimikonhoitoa" ↔ "taimikonhoito"), using the same
`word_matches` as the rest of JobDesk.

### Privacy: the opt-in

- New Account setting **"AI drafting"**, **off by default**. The page says exactly what is sent
  (the chosen CV's facts, the question and the ad; never name, email, phone, location or links) and
  to whom (Anthropic's Claude API).
- `POST /api/draft` refuses live drafting with **403** unless that member has opted in. Mock drafting
  works without opt-in, because nothing leaves the server.
- A member can only draft from **their own** CV (another member's CV id gives 404). Job ads come from
  jobs they can see, or pasted text.
- The draft is only returned to the member; nothing is sent to an employer.
- Boolean ids are refused: in Python `True` counts as the integer 1, so `{"cv_id": true}` would
  otherwise mean "CV number 1".

### Evaluation

`data/eval/drafts.jsonl` has three invented cases (forestry, IT support, health care with a Finnish
answer). Each has **planted sentences** whose truth is known. `python3 scripts/eval_drafts.py` runs
the verifier on them, and drafts an answer per case (mock or live).

**Current verifier result on the planted sentences** (pinned by a test):

| | count | verifier |
|---|---|---|
| Unsupported sentences | 9 | **8 caught**, 1 missed |
| Supported sentences | 7 | **2 false alarms** |

The misses and false alarms are there on purpose, so the numbers show the real limits:
- **Missed:** "I led the field team at Example Forest Research." The employer and the job are real,
  so the words match, but the CV says *assistant*, not *lead*. Word checks can't see a real fact used
  misleadingly. **The student must still read every sentence.**
- **False alarm 1:** "I am learning to use drones." It's honest, but the want-to-learn row has no fact
  id, so the cited fact shares no words with it.
- **False alarm 2:** a true sentence written in Finnish about an English CV. No words match across
  languages. Drafting in the CV's own language avoids this; a future fix could check against both
  language versions of a CV.

For **real drafts**, a person must say which sentences are true. The report lists every drafted
sentence with a ready-made line for `data/eval/draft_labels.jsonl`
(`{"case", "text", "supported": true|false}`). With labels, it reports how many unsupported
sentences the model produced, how many the verifier caught, how many it missed, and false alarms.

**Interview questions.**
- *Why not ask the model to check itself?* The same model that invented a fact may defend it.
  Plain code is predictable, explainable and free, and the evaluation shows exactly what it misses.
- *What's the trade-off in the checks?* Stricter checks (e.g. "most key words must match") would
  catch more invented detail but flag more honest paraphrases. The planted set measures that
  trade-off, so a change can be judged by its numbers.
- *Why keep failing sentences instead of deleting them?* Deleting would hide the problem and could
  leave an answer that reads oddly. Marking them lets the student fix or remove them knowingly.
- *Why send facts and not the whole CV?* Less personal data leaves the server, and the facts have ids
  the model must cite.

---

## Pilot P1–P2: one shared core, the shortlist page and the drafting page

### Why JobDesk and finnish-check stay two apps

`finnish-check` is the small Flask app for the Metropolia application: about 600 lines that can be explained line by
line. JobDesk is the full multi-user app (accounts, CVs, tracker, drafting) that a pilot needs. Both use the same
logic in `core/`. To stop the two copies drifting apart:
- the fixes made in `finnish-check` (OpenRouter support, evaluations that stop at the first failed API call) are now in
  JobDesk too;
- `finnish-check/core/__init__.py` records the JobDesk commit its copy matches.

### OpenRouter (`core/llm.py`)

`OPENROUTER_API_KEY` is a second way to reach Claude, used when it is set:
- **Model names:** `openrouter_model()` turns `claude-haiku-5-5` into OpenRouter's `anthropic/claude-haiku-5.5`.
- **Request:** `build_request()` returns the URL, headers and body for whichever service is in use. OpenRouter uses
  OpenAI-style `messages` and `response_format`.
- **Provider rules:** `provider: {"require_parameters": true, "data_collection": "deny"}` lets only providers that
  support the JSON schema, and that don't store or train on the data, answer.
- **Reading the reply:** `answer_text()` reads either service's reply shape. A cut-off or refused answer is an error.

### Shortlist page (`POST /api/shortlist`, `static/pages/shortlist.js`)

1. **Input:** pasted ads (separated by `---`), a CSV, or up to 10 links. Links go through `scraper.fetch_ad_text`,
   so the SSRF guard and robots.txt both apply. A link that can't be read gets a "paste the ad text instead" message.
2. **Limits:** at most 20 ads per request. In live mode there is a **daily limit of 200 AI checks per member**,
   counted in memory (`SHORTLIST_USAGE`). It is a simple cost guard for the pilot; it resets when the server restarts.
3. **Finnish level:** each ad is classified by the AI in live mode, 4 at a time, or by the keyword rule otherwise. If
   one AI call fails, that ad falls back to the keyword rule and says so.
4. **Ranking:** `core.rank` uses the member's saved Finnish level. Skills are prefilled from a chosen CV's Skills rows,
   but "Want to learn" rows are skipped.
5. **Privacy:** only the ads' text goes to the AI service; skills stay on the server.
6. **Next step:** each row has **Draft an answer**, which hands the ad to the drafting page through sessionStorage
   (this browser tab only).

### Drafting page (`static/pages/draft.js`, using `POST /api/draft` from Phase 4)

- **Input:** choose a CV and a job (or paste the ad), type the question and the word limit.
- **If AI drafting is off:** in live mode without the member's opt-in, the page says so and links to Account → AI
  drafting.
- **Result:** every checked sentence is listed with the CV facts it cites. Unsupported ones are marked
  **UNSUPPORTED** with their reasons.
- **The answer box** starts with the supported sentences only, and says how many unsupported ones were left out, so
  nothing is dropped silently. The word count updates as the student edits, and there is a copy button. Nothing is
  sent anywhere.
- **Tip on the page:** answer in the CV's language, because the check compares words.

**Interview question.** *Why is the daily limit in memory and not in the database?* For a pilot with a few dozen
students it is enough, and it needs no new table. If the pilot grows, the count should move to the database so a
restart doesn't reset it.

---

## Pilot P3: what students need in a pilot

### Metropolia's fields

Metropolia names four fields: **Business, Culture, Health Care and Social Services, and Technology**
([source](https://www.metropolia.fi/en/academics/bachelors-degrees), checked 24 November 2026).
- **Culture is new** (`fields/culture.json`): games, 3D and XR, visual and UX design, media production, fashion,
  music and events.
- **Programme names were added to the existing profiles:** robotics, electronics, construction site management →
  engineering; biomedical laboratory science, physiotherapy, gerontology → health; logistics → business.
- **Words avoided in Culture,** because they appear in ordinary ads: bare "art" (inside "part", "start"),
  "kulttuuri" ("työkulttuuri" = work culture) and bare "media" ("social media"). Tests check these.

### First-login setup and a field-aware menu

- A **"Get started in three steps"** card (choose fields and Finnish level → add a CV → try the Shortlist) appears
  at the top of the start page until the first two steps are done (`static/getting-started.js`).
- A page can now say which fields it belongs to: `register({ id: "news", fields: ["forestry"], … })`. The menu
  shows it only to members who chose that field. The forestry "For you" page and News desk are hidden for
  everyone else, whose start page becomes Jobs. Saving fields on Account rebuilds the menu.
- **Neutral name:** the app is now called "JobDesk" everywhere, and the sign-in screen no longer says "forestry careers portal".

### "Was this right?"

Every Finnish result, on Jobs and on Shortlist, has **Yes / No**. On No, the student picks what the ad really says.
`POST /api/finnish/feedback` stores the level shown, the vote, the correction, the method (AI or keyword rule) and
the quoted sentence, which is public ad text. The administrator's `GET /api/finnish/feedback/summary` gives the share
of "right" answers per method. That is the pilot's accuracy measurement on real ads chosen by real students. The
values are checked against fixed lists, so nothing else can be stored.

### Delete my account

`POST /api/account/delete` asks for the password again, so an open, forgotten session can't be used to delete
someone's account. `db.delete_user` runs in one transaction:
- **deleted:** CVs, applications, prep answers, sessions, news reading state, feedback and the account;
- **kept:** job ads the member shared with others, moved to the administrator account. They are public ads that
  other students may be tracking.
- The administrator account (id 1) owns the shared listings, so it can't be deleted.

**A CSS bug found by clicking through in a browser:** JobDesk's `label.field { display: grid }` overrode the
`hidden` attribute, so "hidden" inputs were still visible. The fix is one rule, `[hidden] { display: none
!important; }`. The unit tests couldn't catch this; only a real browser could.

**Interview question.** *Why keep shared ads after deletion; isn't that personal data?* A shared ad is the
employer's public text. The member's name isn't stored with it, and the contact fields are always cleared when a
member shares an ad. Deleting it would remove it from other students' trackers.

---

## Pilot P4: a pilot deployment

- **`--create-invitations N --days D`** prints N single-use invitation codes, valid for D days (1–500 codes,
  1–120 days). Previously there was one 7-day code per click.
- **`--delete-member-accounts`** counts every account except the administrator's (a dry run). With **`--apply`** it
  takes a backup, then deletes them all through `db.delete_user`. It then reminds the administrator that the backups
  still hold the deleted data, because a retention promise is only kept once the backups are gone too.
- **`JOBDESK_AI_DAILY_LIMIT`** (default 200) and **`JOBDESK_DEFAULT_FIELDS`** are now settings, not code.
- **`docs/PILOT-DEPLOYMENT.md`** is the checklist: a separate server and database, the EU region recorded, the
  settings, accounts and codes, what to do during the pilot, deletion at the end, and what must be ready before
  students are invited.

**Found while writing the checklist.** On every start, JobDesk imports the CVs in `JOBDESK_CV_REPO/roles/` into the
administrator account. Pointed at the administrator's own CV repository, a pilot server would hold their CVs. The
checklist says to use a copy that contains only the LaTeX template.

**Interview question.** *Why a command for deleting everyone, rather than asking students to delete themselves?* A
pilot has an end date, and the privacy notice promises that the data is gone by then. One dry-run-first command makes
that promise checkable. Students can still delete their own account at any time.

---

## Pilot P5: documents for Metropolia, and an accessibility check

- **Accessibility check:** axe-core 4.10.2 (WCAG 2.1 A/AA rules) was run in headless Firefox, in a container, on the
  sign-in page and every page a pilot student uses. It found three problems, all fixed:
  - a sorted table header with too little contrast, which was already there before the pilot work;
  - the Tracker board, which scrolls sideways but couldn't get keyboard focus;
  - a new button style of mine that broke contrast on My CVs.

  After the fixes no automated rule fails. Automated tools only find part of the problems, so screen readers, zoom
  and dark mode are listed as not yet checked.
- **`docs/pilot/PROPOSAL.md`:** a 1–2 page proposal for Metropolia staff. It covers the problem (their own survey),
  what students get, why the results can be trusted, the pilot's shape, what's needed from Metropolia (no system
  integration), how success is measured, privacy, cost and limits.
- **`docs/pilot/PRIVACY-NOTICE.md`:** a draft for the data protection officer. It describes exactly what the software
  stores and sends. Decisions that aren't the software's to make (controller, legal basis, transfer mechanism, server
  region) are left as clearly marked blanks.
- **`docs/pilot/ACCESSIBILITY.md`:** a draft statement of "partially conforming", saying what was checked and what
  wasn't.
- **README:** now describes JobDesk as it is: fields, Shortlist, Draft, AI and mock mode, pilot documents.

**Interview question.** *Why leave blanks in the privacy notice instead of filling them in?* The controller, the legal
basis and the transfer mechanism are legal decisions for the university. Guessing them would make the document look
finished when it isn't. The draft is precise about what the software does, and leaves the rest visibly open.

## Platform A: sign-in by email link, and private jobs

JobDesk is opening up from one Metropolia pilot to students at any Finnish university, so two foundations changed.

**1. No more passwords.** Students sign in with a one-time link sent to their email ("magic link").

How it works, step by step:

1. The sign-in page asks for an email (and a name, when creating an account). It POSTs `/api/auth/link`.
2. The server makes a random token, stores only its SHA-256 hash in the `login_links` table with a 15-minute expiry,
   and emails `JOBDESK_PUBLIC_URL/#/auth?token=...` through `mailer.py`.
3. The answer is the same whether or not the email has an account, so the form can't be used to find out who uses
   JobDesk.
4. Opening the link loads the page, which first removes the token from the address bar and then POSTs it to
   `/api/auth/verify`. Using a POST matters: email security scanners open links with GET, and a GET that signed in
   would use the link up before the student clicks it.
5. `use_login_link` marks the link used inside one `BEGIN IMMEDIATE` transaction, so two clicks at the same time can't
   both succeed. A new email gets an account at this point, not before, so a mistyped address never creates one.
6. Limits: 5 links per email and 30 per IP address per hour. Behind the Caddy proxy, the IP is the right-most
   `X-Forwarded-For` entry, trusted only when the request comes from 127.0.0.1 (otherwise anyone could fake it).

`JOBDESK_OPEN_SIGNUP=0` keeps a closed pilot: then a new account needs an invitation code. Email goes out by SMTP
(any provider), or, in development, is printed to the server log. Tests use an in-memory outbox. Existing password
hashes are cleared by a migration, and deleting an account now needs the account's email typed in as confirmation.

**2. Jobs you add are private.** Before, any job a member added was shown to everyone in that field. Now it is
saved for that member only (`jobs.private`), unless they tick "Share this public ad with students in my field".
Deleting an account deletes its private jobs; shared ones stay, without the name.

**Interview questions.**
- *Why are magic links safer than passwords here?* Students reuse passwords, and a leaked password database is the
  usual breach. With links there is nothing to leak: the server only holds hashes of short-lived, single-use tokens.
  The risk moves to the student's email account, which is usually better protected than a new site's password.
- *Why does the page POST the token instead of the link signing you in directly?* Link scanners in Outlook and
  similar services fetch every URL in an email. If a GET signed in, the scanner would consume the single-use link.
- *Why make jobs private by default?* A student may save an ad they found through a contact or an internal list.
  Sharing should be a choice, not a side effect.

## Platform B: collecting jobs by link

Students find jobs everywhere: LinkedIn, employer sites, Duunitori, a teacher's email. Phase B lets them collect all
of them in one place.

**What changed**
- **Add a job by link.** Paste a link and click "Read this link". JobDesk fills in the title, employer, place, dates
  and description, and the student checks them before saving. Nothing is stored until they click Save.
- **When a page can't be read**, the same form opens empty (with the link filled in) and the reason is shown:
  robots.txt disallows it, the page needs a sign-in, or the site didn't answer.
- **Bookmarklet.** "Save to JobDesk" is a bookmark that opens JobDesk with the current page's link and title. If the
  student selected the ad's text first, it goes into the description. That covers sites JobDesk can't read, such as
  LinkedIn.
- **No duplicates.** The same ad written two ways (`www.`, `?utm_source=…`, `#apply`, a trailing slash) counts as one.
- **My jobs and Discover.** The Jobs page now has two views: the student's own jobs with a count per status, and the
  shared listings in their fields with a Save button. A job added by link starts as "Saved", so it also appears in
  the Tracker's Saved column.

**How it works, step by step**
1. `POST /api/jobs/preview` checks the link (http/https, no user name or password in it, a public address so the
   server can't be pointed at its own network), then checks whether the student already has it.
2. It checks robots.txt, then fetches the page with `core/fetch.fetch_page` (public redirects only, 2 MB at most,
   15-second timeout, an honest User-Agent).
3. `core/jobpage.extract` reads the page. Most job sites publish a schema.org `JobPosting` in a
   `<script type="application/ld+json">` block, because Google for Jobs uses it. The code looks for it at the top
   level, in lists and in `@graph`, and skips blocks that aren't valid JSON. The description is HTML inside JSON, so
   it is converted to plain text. Dates keep only the `YYYY-MM-DD` part.
4. Without a `JobPosting`, the title comes from `og:title`, then the first `<h1>`, then `<title>`, and the description
   from the visible text (without menus, scripts and forms). The answer says which method was used, so the page can
   tell the student to check more carefully.
5. `canonical_url` writes a link one way: https, lower-case host without `www.`, no fragment, no trailing slash, no
   tracking parameters (`utm_*`, `gclid`, `fbclid` and similar), the remaining parameters sorted. Parameters such as
   `?id=7` stay, because they often identify the job.
6. `POST /api/jobs` uses the same check. If the link is a shared listing, it saves that listing for the student
   instead of making a private copy. If it is their own earlier copy, that copy is updated.

**Interview questions**
- *Why structured data instead of scraping each site?* One parser works on thousands of sites, because employers
  publish `JobPosting` for search engines anyway. Site-specific scrapers break whenever a site changes its layout.
- *Why check robots.txt for a link the student pasted?* JobDesk applies the same rule to every request it makes.
  The bookmarklet and the manual form are the way around it that respects the site: the student copies what they
  can already see.
- *Why not drop every query parameter when comparing links?* On many sites the parameter is the job (`?jobId=123`).
  Removing only known tracking parameters can miss a duplicate now and then, but it never merges two different jobs.
- *What stops the preview being used to make the server attack other sites?* Public addresses only, robots.txt, one
  page per request, and 60 links per student per hour.

## Platform C: Shortlist a job, and see how it fits your CV

**What changed**
- On **My jobs**, a **Shortlist** button moves a job to the new *Shortlisted* status and compares the ad with the
  student's CV. A panel under the row shows:
  - a rating: strong fit, possible fit, a stretch, or weak fit;
  - strengths, each with the sentence from the ad and the CV fact behind it;
  - gaps, with advice;
  - recommendations for the application.
- New statuses: *Shortlisted* and *Not a fit* (the panel has a "Mark as not a fit" button). The Tracker shows both
  as columns.
- The comparison runs in a **background queue**, not inside the web request, and is **stored**. The same ad with the
  same CV is never compared twice. When the student edits the CV, or the ad text changes, the result is marked "out
  of date" and can be run again.
- The Account setting "AI drafting" is now **"AI with your CV"**, because it also covers this comparison.

**How it works, step by step**
1. `POST /api/jobs/<id>/evaluate` (with `shortlist: true` from the button) checks the student can see the job. It
   moves Saved, unset or Not a fit to Shortlisted, and leaves later statuses such as Applied alone.
2. It picks the CV: the one asked for, the one chosen for this application, the best keyword match, or the newest.
3. It decides the method. The AI is used only when the server is in live mode **and** the student turned on "AI with
   your CV". Otherwise, rules on the server compare words. Rules mode is also what mock mode uses.
4. `fit.cache_key` hashes the ad text, the CV content, the method and the prompt version. If an evaluation with that
   key is stored, it is returned at once. Otherwise a task is queued, and an identical task that is already waiting is
   reused instead of being queued again.
5. The worker (`tasks.py`, one thread) takes the oldest queued task. `db.claim_task` marks it running in the same
   transaction that picks it. Then the worker calls `core/fit.evaluate` and stores the result. If the server stops
   mid-task, the task is queued again at the next start.
6. The page asks `GET /api/jobs/<id>/fit` every 1.5 seconds until the task is done or failed. A failure shows a short,
   safe reason, such as "the CV no longer exists", never the CV or the API's raw error.
7. `core/fit.check` applies the same rules to the AI's answer and to the rules' answer:
   - a strength must cite CV fact ids that exist;
   - it must not claim something the ad requires that the CV lacks;
   - every quote must be in the ad word for word, or it is removed (the panel says how many were removed);
   - requirements found by `core/blockers` are always gaps, and they stop a rating of "strong".
8. The rules give at most "possible fit". Shared words can't show that someone is a strong candidate.

**Interview questions**
- *Why a queue in SQLite instead of Celery or Redis?* The volume is small (a pilot), and the app already runs on
  SQLite with the standard library. A table plus one worker thread is enough, and it survives restarts. The claim
  is atomic, so a second worker can be added later. Celery would need a broker and another service to run and
  secure.
- *How do you avoid paying for the same evaluation twice?* The cache key is a hash of everything the answer depends
  on: the ad, the CV, the method and the prompt version. Duplicate requests reuse a waiting task. Changing the prompt
  changes the version, so old answers aren't mixed with new ones.
- *Why not let the AI rate freely?* The rating is advice students act on. Code checks every claim it can: fact ids,
  quotes and hard requirements. Requirements the CV doesn't show come from rules the model can't overrule.
- *What leaves the server?* Only with the student's opt-in, and only in live mode: the ad and the CV facts. Never the
  name, email, phone, location or links. The tests check that the name and email aren't in what is sent.
