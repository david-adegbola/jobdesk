# Labelling guide: how much Finnish does the ad ask for?

Each line of `ads.jsonl` is one ad:

```json
{"id": "...", "source_url": "...", "language": "fi|en|sv|mixed", "ad_text_excerpt": "...",
 "label": "required|preferred|not_needed|unclear", "evidence": "...", "note": "optional"}
```

- **id**: short and unique, e.g. `valtiolle-26001`.
- **source_url**: where the ad came from (empty for invented examples).
- **ad_text_excerpt**: the part of the ad that covers the job and its requirements, copied exactly.
  Keep every sentence about languages. Leave out contact details and names of people.
- **evidence**: the sentence(s) your label is based on, copied exactly from the excerpt. Leave it empty
  only for `unclear` ads that never mention a language.

Label what the **ad says**, not what you guess about the employer.

## The four labels

### required
Finnish is a condition: you can't get the job without it.
- "Edellytämme sujuvaa suomen kielen taitoa."
- "Suomen kielen taito on edellytys / välttämätön."
- "Vaatimukset: erinomainen suomen kielen taito."
- "Fluent Finnish is required." / "You must speak Finnish."
- "Goda kunskaper i finska krävs."

### preferred
Finnish helps, but the ad doesn't make it a condition.
- "Suomen kielen taito katsotaan eduksi." / "…on eduksi" / "…on plussaa"
- "Hyvä suomen kielen taito katsotaan eduksi." (good Finnish **and** "an advantage" = preferred)
- "Toivomme suomen kielen taitoa." ("we hope for", not "we require")
- "Finnish is an advantage / a plus / nice to have."
- "Kunskaper i finska är meriterande."

### not_needed
The ad says Finnish isn't needed, or names a working language and doesn't ask for Finnish.
- "Finnish skills are not required."
- "Our working language is English." (and nothing else asks for Finnish)
- "Työkieli on englanti." (and nothing else asks for Finnish)

### unclear
- The ad doesn't mention Finnish or any working language. **An ad that says nothing is `unclear`,
  not `not_needed`.**
- Or it is contradictory or too vague, e.g. "Kielitaito: suomi" with no word on how good, or
  "language skills" with no language named.

## Tricky cases

| Ad says | Label | Why |
|---|---|---|
| "Hyvä suomen kielen taito" in a list under "Edellytämme" | required | It is listed as a requirement |
| "Hyvä suomen kielen taito katsotaan eduksi" | preferred | "eduksi" = advantage |
| Ad written in Finnish, no language requirement | unclear | The ad's language isn't a requirement |
| "English is required" only | unclear | Says nothing about Finnish |
| "Working language English; Finnish is an advantage" | preferred | Finnish is mentioned as a plus |
| "Kotimaisten kielten taito vaaditaan" | required | Finnish or Swedish required; Finnish counts |
| "Valtion virka: kielitaitovaatimukset määräytyvät lain mukaan" | unclear | No level stated in the ad |

When two sentences point different ways (e.g. one says "required", another says "advantage"), the
stronger requirement wins, and put both sentences in `evidence` separated by " / ".

## Before you commit new rows
- Check that the evidence is a word-for-word copy from the excerpt; a test checks this.
- Aim for a mix: roughly a quarter of each label, and Finnish, English and Swedish ads.
- Remove names, phone numbers and email addresses of recruiters.
