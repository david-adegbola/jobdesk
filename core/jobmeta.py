"""What a job ad says about the job, read from its title, location and text with rules in Finnish, English
and Swedish. No AI; every value can be blank when the ad doesn't say.

extract(job, source_sector="") returns:
    levels            [] or some of LEVELS: thesis, internship, trainee, entry, experienced
    employment_types  [] or some of EMPLOYMENT_TYPES: summer, full_time, part_time, fixed_term, permanent,
                      apprenticeship, gig
    work_mode         "" | onsite | hybrid | remote
    municipality_code, region_code   Statistics Finland codes (core/places.py), "" when not recognised
    deadline, start_date             ISO dates ("2026-06-01"); start_date may also be "asap"
    salary_min, salary_max           numbers in euros (None when not given); salary_period "" | hour | month | year
    tes               the collective agreement named (e.g. "KVTES"), "TES" for an unnamed one, or ""
    permits           [] or some of PERMITS: citizenship, security_clearance, eu_eea, right_to_work, sponsorship
    internship_credits  study credits (op / ECTS) the ad mentions, or None
    paid              1 paid, 0 unpaid, None not said
    combinable_with_studies  1 when the ad says it fits alongside studies, else None
    employer_sector   "" | public | private | third
    lang_fi           Finnish: required | preferred | not_needed | unclear (core.finnish.LEVELS)
    lang_sv, lang_en  the same scale for Swedish and English ("unclear" when not mentioned)
    ad_language       the ad's main language (fi, en, sv) or ""

Rules match word stems, so "harjoittelija", "harjoitteluun" and "kesäharjoittelijaksi" all count. They are
deliberately cautious: a value is set only on wording that says it, never guessed from the field or title
alone (except levels and summer jobs, whose titles say it).
"""

import re
from datetime import date

from core import language as core_language
from core import places as core_places

LEVELS = ("thesis", "internship", "trainee", "entry", "experienced")
EMPLOYMENT_TYPES = ("summer", "full_time", "part_time", "fixed_term", "permanent", "apprenticeship", "gig")
WORK_MODES = ("onsite", "hybrid", "remote")
PERMITS = ("citizenship", "security_clearance", "eu_eea", "right_to_work", "sponsorship")
SECTORS = ("public", "private", "third")
LANGUAGE_LEVELS = ("required", "preferred", "not_needed", "unclear")


def _rx(pattern):
    return re.compile(pattern, re.I)


LEVEL_RULES = {
    "thesis": _rx(r"opinnäyte|pro gradu|gradu(?:tutkielma|työ)|diplomityö|kandidaatintutkielma|lopputyö|"
                  r"master'?s thesis|bachelor'?s thesis|thesis (?:worker|work|position|project)|examensarbete|"
                  r"\bthesis\b|\bgradu\b"),
    "internship": _rx(r"harjoittel|työssäoppi|\bintern\b|\binterns\b|internship|praktikant|\bpraktik|"
                      r"summer trainee|kesätrainee|kesäharjoit|työelämäjakso"),
    "trainee": _rx(r"trainee(?:-| )?(?:ohjelma|program)|graduate (?:program|programme|trainee|scheme)|"
                   r"traineeohjelma|(?<!summer )\btrainees?\b"),          # a "summer trainee" is an internship
    "entry": _rx(r"\bjunior|nuorempi |entry[- ]level|vastavalmistun|recent(?:ly)? graduat|new graduates?\b|"
                 r"ei vaadi (?:aiempaa )?(?:työ)?kokemusta|no (?:prior |previous )?(?:work )?experience "
                 r"(?:is )?(?:required|needed)|aloittelev|nyutexaminer|ensimmäinen työpaikka|first job"),
    "experienced": _rx(r"\bsenior\b|\bkokenut|\bexperienced\b|\blead\b|\bjohtava |\bhead of\b|"
                       r"vähintään (?:[3-9]|1\d) vuo|at least (?:[3-9]|1\d) years|"
                       r"(?:[3-9]|1\d)\+? years?['’]? (?:of )?(?:work |relevant |professional )?experience|"
                       r"(?:[3-9]|1\d)(?:-\d+)? vuoden (?:työ)?kokemu"),
}

# Job titles that are internships even when the ad never says "intern" (Finnish summer jobs for students)
SUMMER_TITLE = _rx(r"kesätyö|kesätöi|kesäksi|kesä(?:kausi|harjoit|trainee|apulai|työntekijä|duuni)|"
                   r"summer (?:job|work|trainee|intern|employee|worker|assistant)|"
                   r"(?:summer|kesä) 20\d\d|sommarjobb|sommarpraktik|sommarvikarie")

EMPLOYMENT_RULES = {
    "summer": SUMMER_TITLE,
    "full_time": _rx(r"kokoaika|full[- ]time|\bheltid|päätoimi"),
    "part_time": _rx(r"osa-aika|osa-aikai|part[- ]time|\bdeltid|tuntityö|tuntitöi"),
    "fixed_term": _rx(r"määräaika|fixed[- ]term|\btemporary\b|sijaisuu|sijaise|viransijai|\bvisstid|vikariat|"
                      r"maternity (?:cover|leave)|parental leave cover|projektiluont"),
    "permanent": _rx(r"vakituinen|vakinainen|toistaiseksi voimassa|\bpermanent\b|tillsvidare|"
                     r"(?:open-ended|indefinite) (?:contract|employment)"),
    "apprenticeship": _rx(r"oppisopimu|apprentice|läroavtal"),
    "gig": _rx(r"keikkatyö|keikkatöi|keikkalai|\bfreelanc|\bgig\b|kevytyrit|light entrepreneur"),
}

REMOTE = _rx(r"täysin etä|kokonaan etä|etätyönä|100 ?% etä|fully remote|remote[- ](?:first|only|job|position|work)|"
             r"work from home|\bremote(?:ly)?\b|distansarbete|på distans|\betätyö\b")
HYBRID = _rx(r"hybridi|\bhybrid\b|osittain etä|osittainen etä|etä- ja lähi|lähi- ja etä|mahdollisuus (?:osittaiseen )?"
             r"etätyöhön|partly remote|remote (?:days|option)|\bdistans\w* möjlig")
ONSITE = _rx(r"lähityö|\bon-?site\b|paikan päällä|työpaikalla|in the office|in-person|på plats")

# Named agreements are upper-case acronyms ending in TES ("KVTES", "AVAINTES"); case matters, or "graduates"
# would count. The health and social care agreement is "Sote-sopimus".
TES = re.compile(r"\b(KVTES|AVAINTES|TTES|OVTES|UTES|VES|VTES|[Ss]ote-sopimu\w*|[A-ZÄÖ][A-ZÄÖ-]{0,25}TES)\b")
TES_GENERIC = _rx(r"työehtosopimu|virkaehtosopimu|collective (?:labour |labor )?agreement|kollektivavtal|\bTES\b")

PERMIT_RULES = {
    "citizenship": _rx(r"suomen kansalai|finnish citizen|finskt medborgarskap|kansalaisuusvaatimus"),
    "security_clearance": _rx(r"turvallisuusselvity|security clearance|security vetting|säkerhetsutredning"),
    "eu_eea": _rx(r"\bEU/?ETA|\bEU/?EEA\b|EU or EEA|EU-?kansalai|EU citizen"),
    "right_to_work": _rx(r"oikeus työskennellä suomessa|right to work in finland|valid (?:work|residence) permit|"
                         r"voimassa oleva työlupa|oleskelulupa|työlupa|work permit|residence permit|arbetstillstånd"),
    "sponsorship": _rx(r"visa sponsor|sponsor(?:ship)? (?:for )?(?:your )?(?:visa|work permit)|relocation (?:support|package|assistance)|"
                       r"autamme (?:työ|oleskelu)luv|tuemme (?:työ|oleskelu)luv|muuttotuki"),
}

CREDITS = _rx(r"\b(\d{1,2})\s*(?:op\b|opintopiste|ects|credits\b|sp\b|studiepoäng)")
CREDIT_CONTEXT = _rx(r"harjoittel|intern|opinto|study|studie|credit|praktik|thesis|opinnäyte")
UNPAID = _rx(r"palkaton|palkattom|\bunpaid\b|ei palkkaa|without pay|no salary|oleskeluraha|työkokeilu|obetald")
PAID = _rx(r"palkallinen|palkallis|paid (?:internship|traineeship|position|summer)|harjoittelupalkka|"
           r"kuukausipalkka|tuntipalkka|\bsalary\b|\bwage\b|\bpalkka|\bpalkkaus|\blön\b")
WITH_STUDIES = _rx(r"opintojen ohe|opiskelun ohe|opintojen rinnalla|opiskelijoille sopiva|sopii opiskelijalle|"
                   r"alongside (?:your )?stud|while studying|combine (?:it |work |this )?with (?:your )?stud|"
                   r"suitable for students|vid sidan av studierna|bredvid studierna")

PUBLIC_EMPLOYER = _rx(r"kaupunki|\bkunta\b|kunnan |kuntayhtymä|hyvinvointialue|yliopisto|university|ammattikorkeakoulu|"
                      r"ministeriö|ministry|virasto|poliisi|puolustusvoim|verohallinto|\bkela\b|valtiokonttori|"
                      r"luonnonvarakeskus|metsähallitus|tulli\b|maanmittauslaitos|\bstad\b|kommun|välfärdsområde")
THIRD_SECTOR = _rx(r"\bry\b|\br\.y\.|säätiö|foundation|yhdistys|association|liitto\b|förening|stiftelse|\bsrk\b")
PRIVATE_EMPLOYER = _rx(r"\b(?:oy|oyj|ab|abp|ltd|inc|gmbh|plc|llc|as|tmi|ky)\b\.?$|\b(?:oy|oyj|ltd)\b")

# Finnish requirement wording (rules, not the LLM classifier in core/finnish.py)
FI_NOT_NEEDED = _rx(r"finnish (?:language )?(?:skills? )?(?:is |are )?not (?:required|needed|necessary|a requirement)|"
                    r"no finnish (?:required|needed|necessary|skills required)|without (?:any )?finnish|"
                    r"(?:don't|do not|doesn't|does not) (?:need|require) (?:to speak |any )?finnish|"
                    r"suomen kielen taitoa ei (?:vaadita|edellytetä|tarvita)|suomen kieltä ei (?:vaadita|tarvita)|"
                    r"finska (?:krävs|behövs) inte|working language (?:is|will be) english|työkieli(?:nä)? on englanti|"
                    r"english[- ]speaking (?:team|environment|workplace)|all (?:work|communication) (?:is )?in english")
# Gaps stop at "." "," and ";" so "suomi vaaditaan, ruotsi eduksi" isn't read as Finnish being an advantage
FI_PREFERRED = _rx(r"suome\w* (?:kielen |kieli\w* )?(?:taito|osaaminen|kieli)?\w*[^.,;]{0,40}(?:eduksi|etu\b|plussaa|hyödyksi|toivottava)|"
                   r"(?:eduksi|etua|plussaa)[^.,;]{0,40}suome|"
                   r"finnish[^.,;]{0,40}(?:is |would be |considered )?(?:an? )?(?:advantage|plus|asset|bonus|beneficial|nice to have)|"
                   r"(?:advantage|plus|asset|bonus)[^.,;]{0,25}finnish|finska[^.,;]{0,30}merit")
FI_REQUIRED = _rx(r"sujuva\w* suome|(?:hyvä\w*|erinomai\w*|sujuva\w*) suomen (?:ja \w+ )?kiel|"
                  r"suomen kielen taito on (?:edellytys|välttämätön|vaatimus)|"
                  r"(?:fluent|native|excellent|good|strong|professional)[^.]{0,20}finnish|finnish[^.]{0,30}(?:required|mandatory|essential|must)|"
                  r"äidinkieli\w* suomi|suomen kielen (?:hyvä|erinomainen|sujuva)|kielitaitovaatimu\w*[^.]{0,60}suome|"
                  r"flytande finska|goda kunskaper i finska")


def _lang_rules(names):
    """Required / preferred wording for a language other than Finnish (names: stems in fi, en, sv)."""
    lang = "(?:" + "|".join(names) + ")"
    preferred = _rx(lang + r"[^.,;]{0,50}(?:eduksi|etu\b|plussaa|advantage|plus|asset|merit|toivottava)|"
                    r"(?:eduksi|advantage|plus|asset|merit)[^.,;]{0,25}" + lang)
    required = _rx(r"(?:sujuva\w*|hyvä\w*|erinomai\w*|fluent|native|excellent|good|strong|flytande|goda)[^.,;]{0,25}" + lang
                   + "|" + lang + r"[^.,;]{0,30}(?:required|mandatory|essential|edellytys|edellytetään|vaaditaan|vaatimus|välttämätön|krävs)")
    return preferred, required


SV_PREFERRED, SV_REQUIRED = _lang_rules(["ruotsi", "swedish", "svenska", "\\bsvensk"])
EN_PREFERRED, EN_REQUIRED = _lang_rules(["englan", "english", "engelska"])

# Dates
FI_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b")
FI_DATE_NO_YEAR = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(?!\d)")
ISO_DATE = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS.update({"tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4, "toukokuuta": 5, "kesäkuuta": 6,
               "heinäkuuta": 7, "elokuuta": 8, "syyskuuta": 9, "lokakuuta": 10, "marraskuuta": 11, "joulukuuta": 12})
EN_DATE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\.?,?\s+(20\d\d)\b", re.I)
EN_DATE_US = re.compile(r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I)

DEADLINE_CUE = _rx(r"hakuaika päättyy|haku päättyy|viimeinen hakupäivä|hae viimeistään|hakemukset viimeistään|"
                   r"hakuaika(?:\s+on)?|deadline|apply by|applications? (?:by|no later than|close|must be)|"
                   r"application period ends|ansökningstiden går ut|sista ansökningsdag|viimeistään")
START_CUE = _rx(r"aloitus(?:päivä|aika)?|alkaen|työ alkaa|työt alkavat|työsuhde alkaa|alkamisaika|start(?:ing)? date|"
                r"starts? (?:on|in)?|starting (?:from|on)?|from|tillträde|med start|börjar")
ASAP = _rx(r"heti|mahdollisimman pian|sopimuksen mukaan|as soon as possible|\basap\b|immediately|snarast|omgående")

# Salary: "2 800–3 200 €/kk", "12,50 €/h", "3000 euroa kuukaudessa", "€3,000 per month", "45 000 € / vuosi"
AMOUNT = r"(\d{1,3}(?:[   .,]\d{3})+|\d+)(?:[,.](\d{1,2}))?(?!\d)"   # "3 000", "3.000", "3,000", "12,50"
SALARY = re.compile(
    r"(?:€\s*" + AMOUNT + r"(?:\s*[-–—]\s*€?\s*" + AMOUNT + r")?)|"
    r"(?:" + AMOUNT + r"(?:\s*[-–—]\s*" + AMOUNT + r")?\s*(?:€|e(?=\s*/)|euro|eur\b))", re.I)
PERIOD_HOUR = _rx(r"^\s*(?:/|per|a|an|in|euroa)?\s*(?:h\b|t\b|hour|hourly|tunti|tunnis|tunnilta|timme|tim\b)")
PERIOD_MONTH = _rx(r"^\s*(?:/|per|a|in|euroa|e)?\s*(?:kk\b|kuuk|kuussa|month|monthly|mo\b|mån)")
PERIOD_YEAR = _rx(r"^\s*(?:/|per|a|in|euroa)?\s*(?:v\b|vuo|year|yearly|annual|annum|år)")
SALARY_CUE = _rx(r"palk|salary|wage|\bpay\b|lön|ansio|compensation|tuntipalk|kuukausipalk")


def _found(rules, text):
    return [name for name, rule in rules.items() if rule.search(text)]


def _date(text, start=0, window=None):
    """The first date in text[start:start+window] as ISO, or ""."""
    part = text[start:start + window] if window else text[start:]
    candidates = []
    for m in FI_DATE.finditer(part):
        candidates.append((m.start(), int(m.group(3)), int(m.group(2)), int(m.group(1))))
    for m in ISO_DATE.finditer(part):
        candidates.append((m.start(), int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in EN_DATE.finditer(part):
        candidates.append((m.start(), int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))))
    for m in EN_DATE_US.finditer(part):
        candidates.append((m.start(), int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))))
    for _, y, mo, d in sorted(candidates):
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            continue
    return ""


def _cued_date(text, cue, window=80):
    for m in cue.finditer(text):
        found = _date(text, m.end(), window)
        if found:
            return found
    return ""


def _number(whole, decimals):
    value = float(re.sub(r"[   .,]", "", whole) + ("." + decimals if decimals else ""))
    return int(value) if value.is_integer() else value


BOUNDS = {"hour": (5, 200), "month": (400, 25_000), "year": (8_000, 300_000)}


def salary(text):
    """(min, max, period) from the first plausible euro amount, or (None, None, "")."""
    for m in SALARY.finditer(text):
        groups = m.groups()
        first = groups[0:2] if groups[0] else groups[4:6]
        second = groups[2:4] if groups[0] else groups[6:8]
        low = _number(*first)
        high = _number(*second) if second[0] else low
        after = text[m.end():m.end() + 25]
        before = text[max(0, m.start() - 60):m.start()]
        period = ("hour" if PERIOD_HOUR.search(after) else "month" if PERIOD_MONTH.search(after)
                  else "year" if PERIOD_YEAR.search(after) else "")
        if not period:
            if re.search(r"tuntipalk|hourly|per hour|timlön", before, re.I):
                period = "hour"
            elif re.search(r"kuukausipalk|monthly|per month|månadslön", before, re.I):
                period = "month"
            elif re.search(r"vuosipalk|annual|per year|årslön", before, re.I):
                period = "year"
            elif SALARY_CUE.search(before):            # only guess from size when the ad talks about pay
                period = next((p for p, (lo, hi) in BOUNDS.items() if lo <= low <= hi), "")
        if not period:
            continue
        lo, hi = BOUNDS[period]
        if lo <= low <= hi and lo <= high <= hi and high >= low:
            return low, high, period
    return None, None, ""


def _language_level(text, required, preferred, not_needed=None):
    if not_needed is not None and not_needed.search(text):
        return "not_needed"
    if preferred.search(text):
        return "preferred"
    if required.search(text):
        return "required"
    return "unclear"


def sector(company, source_sector=""):
    if source_sector in SECTORS:
        return source_sector
    company = (company or "").strip()
    if not company:
        return ""
    if PUBLIC_EMPLOYER.search(company):
        return "public"
    if THIRD_SECTOR.search(company):
        return "third"
    if PRIVATE_EMPLOYER.search(company):
        return "private"
    return ""


def extract(job, source_sector="", places=None):
    places = places or core_places.load()
    title = job.get("title") or ""
    body = job.get("ad_text") or job.get("description") or ""
    text = f"{title}\n{body}"

    levels = _found(LEVEL_RULES, text)
    employment = _found(EMPLOYMENT_RULES, text)
    work_mode = ("hybrid" if HYBRID.search(text) else "remote" if REMOTE.search(text)
                 else "onsite" if ONSITE.search(text) else "")
    municipality, region = places.match(job.get("location") or "")
    if not municipality and "," in title:              # "Myyjä, Tampere"
        municipality, region = places.match(title.rsplit(",", 1)[1])
    if not (municipality or region) and re.search(r"\b(?:etätyö|remote)\b", job.get("location") or "", re.I):
        work_mode = work_mode or "remote"

    start = _cued_date(body, START_CUE, 60)
    if not start and re.search(r"(?:aloitus|alkaen|start\w*|tillträde)[^.\n]{0,25}", body, re.I):
        cue = re.search(r"(?:aloitus|alkaen|start\w*|tillträde)([^.\n]{0,40})", body, re.I)
        if cue and ASAP.search(cue.group(1)):
            start = "asap"

    low, high, period = salary(body)
    tes_match = TES.search(body)
    tes = tes_match.group(1) if tes_match else ("TES" if TES_GENERIC.search(body) else "")
    if tes.lower().startswith("sote-sopimu"):
        tes = "Sote-sopimus"

    credits = None
    for m in CREDITS.finditer(text):
        around = text[max(0, m.start() - 80):m.end() + 40]
        if CREDIT_CONTEXT.search(around) and 1 <= int(m.group(1)) <= 60:
            credits = int(m.group(1))
            break
    paid = 0 if UNPAID.search(text) else (1 if PAID.search(text) or low is not None else None)

    languages = core_language.detect(title, body)
    return {
        "levels": levels,
        "employment_types": employment,
        "work_mode": work_mode,
        "municipality_code": municipality,
        "region_code": region,
        "deadline": _cued_date(body, DEADLINE_CUE),
        "start_date": start,
        "salary_min": low,
        "salary_max": high,
        "salary_period": period,
        "tes": tes,
        "permits": _found(PERMIT_RULES, text),
        "internship_credits": credits,
        "paid": paid,
        "combinable_with_studies": 1 if WITH_STUDIES.search(text) else None,
        "employer_sector": sector(job.get("company"), source_sector),
        "lang_fi": _language_level(text, FI_REQUIRED, FI_PREFERRED, FI_NOT_NEEDED),
        "lang_sv": _language_level(text, SV_REQUIRED, SV_PREFERRED),
        "lang_en": _language_level(text, EN_REQUIRED, EN_PREFERRED),
        "ad_language": languages[0] if languages else "",
    }


def finnish_not_required(meta):
    """True when a member without Finnish can apply: the ad says Finnish isn't needed, or it is written in
    English (or Swedish) and doesn't ask for Finnish."""
    level = meta.get("lang_fi") or "unclear"
    if level == "not_needed":
        return True
    return level == "unclear" and meta.get("ad_language") in ("en", "sv")
