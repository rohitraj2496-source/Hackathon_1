"""Short interview: one open answer (or a tap-only family builder), then at most 2 tap follow-ups.

- extract_from_text: Haiku turns one spoken/typed description into a household profile.
- profile_from_builder: deterministic, for families who tap chips instead of talking.
- pick_followups: up to MAX_FOLLOWUPS fixed, tap-only questions, only for facts that change
  eligibility. Questions are written here in both languages, so no model call and no open questions.
- finalize: anything still unknown gets the safer assumption (the one that keeps a scheme in view)
  and is recorded in profile["assumptions"]; write() marks the affected schemes
  "Likely eligible — confirm <fact>".
"""
import json

import neatlogs

from .config import FAST_MODEL, trace_ref
from .llm import structured

LANGS = ("hi", "en")
MAX_FOLLOWUPS = 2

INCOME_BANDS = {"low": 60000, "medium": 200000, "high": 600000}   # rupees per year

# Builder chip -> member skeleton. Ages are typical values, recorded as an assumption where they matter.
BUILDER_MEMBERS = {
    "father": {"relation": "father", "gender": "male", "age": 42},
    "mother": {"relation": "mother", "gender": "female", "age": 38},
    "grandfather": {"relation": "grandfather", "gender": "male", "age": 65},
    "grandmother": {"relation": "grandmother", "gender": "female", "age": 62},
    "son": {"relation": "son", "gender": "male", "age": 14},
    "daughter": {"relation": "daughter", "gender": "female", "age": 12},
}
BUILDER_TAGS = {"farmer", "labourer", "student", "widow", "disabled"}

# Which schemes each assumed fact can change (for "Likely eligible — confirm <fact>").
AFFECTS = {
    "income": {"up_old_age_pension", "up_widow_pension", "up_divyang_pension", "up_kanya_sumangala",
               "up_scholarship", "nsp_scholarship", "up_shadi_anudan", "pm_sym", "nfsa_ration", "pmjay"},
    "ration_card": {"nfsa_ration", "pmjay", "pmuy"},
    "area": {"pmay_g", "nfsa_ration"},
    "house": {"pmay_g"},
    "land": {"pm_kisan", "pm_kisan_maandhan", "pmfby"},
    "lpg": {"pmuy"},
    "age": {"up_old_age_pension", "ayushman_vay_vandana", "pm_sym", "pm_kisan_maandhan"},
    "disability": {"up_divyang_pension"},
}

# Fixed follow-up questions. Each option sets profile fields deterministically.
QUESTIONS = {
    "income": {
        "q": {"hi": "पूरे परिवार की साल की कमाई कितनी है?", "en": "What is your whole family's yearly income?"},
        "options": [
            {"value": "low", "hi": "कम (₹1 लाख से कम)", "en": "Low (under ₹1 lakh)"},
            {"value": "medium", "hi": "मध्यम (₹1–3 लाख)", "en": "Medium (₹1–3 lakh)"},
            {"value": "high", "hi": "ज़्यादा (₹3 लाख से ऊपर)", "en": "High (above ₹3 lakh)"},
        ],
    },
    "ration_card": {
        "q": {"hi": "क्या आपके पास राशन कार्ड है?", "en": "Do you have a ration card?"},
        "options": [
            {"value": "none", "hi": "नहीं है", "en": "No card"},
            {"value": "eligible_household", "hi": "हाँ, राशन कार्ड", "en": "Yes, ration card"},
            {"value": "antyodaya", "hi": "अंत्योदय कार्ड", "en": "Antyodaya (AAY) card"},
        ],
    },
    "area": {
        "q": {"hi": "आप गाँव में रहते हैं या शहर में?", "en": "Do you live in a village or a town?"},
        "options": [
            {"value": "rural", "hi": "गाँव", "en": "Village"},
            {"value": "urban", "hi": "शहर / कस्बा", "en": "Town / city"},
        ],
    },
    "house": {
        "q": {"hi": "आपका घर पक्का है या कच्चा?", "en": "Is your house pucca or kutcha?"},
        "options": [
            {"value": "pucca", "hi": "पक्का", "en": "Pucca (brick/cement)"},
            {"value": "kutcha", "hi": "कच्चा", "en": "Kutcha (mud/thatch)"},
            {"value": "homeless", "hi": "घर नहीं है", "en": "No house"},
        ],
    },
    "land": {
        "q": {"hi": "क्या खेती की ज़मीन परिवार के नाम पर है?", "en": "Is the farmland in your family's name?"},
        "options": [
            {"value": "yes", "hi": "हाँ", "en": "Yes"},
            {"value": "no", "hi": "नहीं", "en": "No"},
        ],
    },
    "lpg": {
        "q": {"hi": "क्या घर में गैस (LPG) कनेक्शन है?", "en": "Does your home have an LPG gas connection?"},
        "options": [
            {"value": "yes", "hi": "हाँ", "en": "Yes"},
            {"value": "no", "hi": "नहीं", "en": "No"},
        ],
    },
}


def empty_profile() -> dict:
    return {"district": None, "state": "Uttar Pradesh", "area": "unknown", "annual_family_income_inr": None,
            "ration_card": "unknown", "house_type": "unknown", "has_lpg_connection": None,
            "has_bank_account": None, "caste_category": "not_shared", "land_acres": None,
            "land_owner_relation": None, "already_receiving": [], "upcoming_events": [], "members": [],
            "assumptions": []}


def _member(**kw) -> dict:
    base = {"name": None, "relation": "", "age": None, "gender": "unknown", "occupation": "unknown",
            "is_widow": False, "disability_percent": None, "is_student": False, "student_class": None,
            "is_pregnant": False, "income_tax_payer": False, "govt_employee_or_pensioner": False}
    return {**base, **kw}


def _assume(profile: dict, fact: str, field: str, value, note: str = "") -> None:
    profile.setdefault("assumptions", []).append({"fact": fact, "field": field, "assumed": value, "note": note})


# ---------------------------------------------------------------- open answer
EXTRACT_SYSTEM = """Extract a household profile for an Indian welfare-scheme finder from ONE description a
family gave (spoken or typed, Hindi or English, possibly messy speech-to-text).
Record only what the family said or clearly implied. Anything not mentioned stays null / "unknown".
Never guess caste: "not_shared" unless they said it. The family lives in Uttar Pradesh (state is fixed).
Use relation words relative to the speaker: self, wife, husband, father, mother, son, daughter,
grandfather, grandmother, daughter-in-law, ... Occupation values: farmer, daily_wage, construction_worker,
artisan:<trade>, homemaker, student, unemployed, salaried, small_business, retired, child, unknown.
Annual income in rupees if they gave a number or a clear monthly figure (multiply by 12).
A widow is a woman whose husband has died. Disability: put the percent if given, else 40 if they say a
member is disabled without a number."""


def extract_from_text(text: str, lang: str, hid: str) -> dict:
    from .agent import PROFILE_SCHEMA  # profile schema lives with the agent
    with neatlogs.trace("intake_extract", kind="AGENT", session_id=hid, end_user_id=hid, lang=lang) as span:
        ref = trace_ref(span, "intake_extract", hid)
        out = structured(None, model=FAST_MODEL, effort="low", max_tokens=6000, system=EXTRACT_SYSTEM,
                         schema=PROFILE_SCHEMA, user=f"Family's description:\n{text}")
    profile = {**empty_profile(), **out, "assumptions": [], "state": "Uttar Pradesh"}
    return {"profile": profile, "trace": ref}


# ---------------------------------------------------------------- tap builder
def profile_from_builder(builder: dict) -> dict:
    """builder = {"members": [{"role": "father", "tags": ["farmer"]}, ...], "income": "low"|"medium"|"high"|None}"""
    p = empty_profile()
    for m in builder.get("members", []):
        role = m.get("role")
        if role not in BUILDER_MEMBERS:
            continue
        tags = {t for t in m.get("tags", []) if t in BUILDER_TAGS}
        sk = dict(BUILDER_MEMBERS[role])
        occ = ("farmer" if "farmer" in tags else "daily_wage" if "labourer" in tags
               else "student" if "student" in tags else "child" if role in ("son", "daughter") else "unknown")
        mem = _member(**sk, occupation=occ, is_student="student" in tags,
                      is_widow="widow" in tags and sk["gender"] == "female",
                      disability_percent=40 if "disabled" in tags else None)
        p["members"].append(mem)
        if role in ("grandfather", "grandmother"):
            _assume(p, "age", f"members[{len(p['members']) - 1}].age", sk["age"], f"{role} assumed 60+")
        if "disabled" in tags:
            _assume(p, "disability", f"members[{len(p['members']) - 1}].disability_percent", 40,
                    "assumed 40% (certificate needed)")
    if "farmer" in {t for m in builder.get("members", []) for t in m.get("tags", [])}:
        p["land_owner_relation"] = next((m["relation"] for m in p["members"] if m["occupation"] == "farmer"), None)
    if builder.get("income") in INCOME_BANDS:
        p["annual_family_income_inr"] = INCOME_BANDS[builder["income"]]
    return p


# ---------------------------------------------------------------- follow-ups
def _has_farmer(p):
    return any(m.get("occupation") == "farmer" for m in p["members"])


def _has_adult_woman(p):
    return any(m.get("gender") == "female" and (m.get("age") or 30) >= 18 for m in p["members"])


def _unknowns(p: dict) -> list[str]:
    """Eligibility-changing facts still unknown, most impactful first."""
    out = []
    if p.get("annual_family_income_inr") is None:
        out.append("income")
    if p.get("ration_card") in (None, "unknown"):
        out.append("ration_card")
    if _has_farmer(p) and p.get("land_acres") is None:
        out.append("land")
    if p.get("area") in (None, "unknown"):
        out.append("area")
    if p.get("area") != "urban" and p.get("house_type") in (None, "unknown"):
        out.append("house")
    if _has_adult_woman(p) and p.get("has_lpg_connection") is None:
        out.append("lpg")
    return out


# Ranking weights for follow-up questions: first-year money per scheme (yearly amount, or the one-time grant),
# from official amounts in the catalog notes and from test-run research where amounts vary. Used only to decide
# which questions are worth asking; never shown to families.
VALUE_INR = {
    "pm_kisan": 6000, "pmay_g": 120000, "pmuy": 2050, "pmmvy": 5000, "up_kanya_sumangala": 25000,
    "up_old_age_pension": 12000, "up_widow_pension": 12000, "up_divyang_pension": 12000,
    "up_scholarship": 2250, "up_shadi_anudan": 20000, "nfsa_ration_per_person": 1550,
}


def _girls(p):
    return [m for m in p["members"] if m.get("gender") == "female" and (m.get("age") or 0) <= 21
            and m.get("relation") in ("daughter", "granddaughter", "beti", "sister")]


def _money_at_stake(p: dict) -> dict[str, int]:
    """First-year ₹ of each scheme that plausibly fits this family (0 if it clearly cannot)."""
    ms = p["members"]
    pensions = sum(1 for m in ms if (m.get("age") or 0) >= 60 or m.get("is_widow")
                   or (m.get("disability_percent") or 0) >= 40)   # one pension per person
    return {
        "pm_kisan": VALUE_INR["pm_kisan"] if _has_farmer(p) else 0,
        "pmay_g": VALUE_INR["pmay_g"] if p.get("area") != "urban" and p.get("house_type") != "pucca" else 0,
        "pmuy": VALUE_INR["pmuy"] if _has_adult_woman(p) and p.get("has_lpg_connection") is not True else 0,
        "nfsa_ration": VALUE_INR["nfsa_ration_per_person"] * max(len(ms), 1)
        if p.get("ration_card") not in ("eligible_household", "antyodaya") else 0,
        "pensions": VALUE_INR["up_old_age_pension"] * pensions,
        "up_kanya_sumangala": VALUE_INR["up_kanya_sumangala"] if _girls(p) else 0,
        "up_scholarship": VALUE_INR["up_scholarship"] * sum(1 for m in ms if m.get("is_student")),
    }


# Which profile facts must be known to move each scheme from "check needed" to confirmed.
GATES = {
    "pm_kisan": {"land"}, "pmay_g": {"area", "house"}, "pmuy": {"lpg", "ration_card"},
    "nfsa_ration": {"ration_card", "area", "income"}, "pensions": {"income"},
    "up_kanya_sumangala": {"income"}, "up_scholarship": {"income"},
}


def rank_followups(profile: dict) -> list[tuple[list[str], int]]:
    """All sets of at most MAX_FOLLOWUPS unknown facts, by the ₹ they would move to confirmed
    (a scheme counts only if every unknown fact gating it is in the set). Best first; ties ask fewer
    questions, then follow the fixed fact order so the result is deterministic."""
    from itertools import combinations
    unknown = _unknowns(profile)
    stake = _money_at_stake(profile)
    order = {f: i for i, f in enumerate(["income", "ration_card", "land", "area", "house", "lpg"])}
    options = []
    for k in range(1, MAX_FOLLOWUPS + 1):
        for combo in combinations(sorted(unknown, key=order.get), k):
            chosen = set(combo)
            value = sum(v for s, v in stake.items() if v and (GATES[s] & set(unknown)) and (GATES[s] & set(unknown)) <= chosen)
            options.append((list(combo), value))
    options.sort(key=lambda o: (-o[1], len(o[0]), [order[f] for f in o[0]]))
    return options


def pick_followups(profile: dict, lang: str) -> list[dict]:
    """At most 2 tap questions: the set that confirms the most money for this family."""
    lang = lang if lang in LANGS else "hi"
    ranked = rank_followups(profile)
    if not ranked or ranked[0][1] == 0:
        return []                       # nothing worth asking: unknowns become safe assumptions
    facts, value = ranked[0]
    # house type only matters for rural housing: skip it if the family just said they live in a town
    skip = {"house": {"area": ["urban"]}}
    return [{"id": k, "question": QUESTIONS[k]["q"][lang], "unlocks_inr": value,
             "options": [{"value": o["value"], "label": o[lang]} for o in QUESTIONS[k]["options"]],
             **({"skip_if": skip[k]} if k in skip and len(facts) > 1 else {})}
            for k in facts]


def apply_answer(p: dict, qid: str, value: str) -> None:
    if qid == "income" and value in INCOME_BANDS:
        p["annual_family_income_inr"] = INCOME_BANDS[value]
    elif qid == "ration_card" and value in ("none", "eligible_household", "antyodaya"):
        p["ration_card"] = value
    elif qid == "area" and value in ("rural", "urban"):
        p["area"] = value
    elif qid == "house" and value in ("pucca", "kutcha", "homeless"):
        p["house_type"] = value
    elif qid == "land" and value in ("yes", "no"):
        farmer = next((m["relation"] for m in p["members"] if m.get("occupation") == "farmer"), "self")
        p["land_acres"], p["land_owner_relation"] = (1, farmer) if value == "yes" else (0, None)
    elif qid == "lpg" and value in ("yes", "no"):
        p["has_lpg_connection"] = value == "yes"


def finalize(p: dict) -> dict:
    """Fill every remaining eligibility-changing unknown with the safer assumption and record it."""
    for fact in _unknowns(p):
        if fact == "income":
            p["annual_family_income_inr"] = INCOME_BANDS["low"]
            _assume(p, "income", "annual_family_income_inr", INCOME_BANDS["low"], "assumed low income")
        elif fact == "ration_card":
            p["ration_card"] = "none"
            _assume(p, "ration_card", "ration_card", "none", "assumed no ration card")
        elif fact == "land":
            farmer = next((m["relation"] for m in p["members"] if m.get("occupation") == "farmer"), "self")
            p["land_acres"], p["land_owner_relation"] = 1, farmer
            _assume(p, "land", "land_acres", 1, "assumed land in the farmer's name")
        elif fact == "area":
            p["area"] = "rural"
            _assume(p, "area", "area", "rural", "assumed village (most of UP)")
        elif fact == "house":
            p["house_type"] = "kutcha"
            _assume(p, "house", "house_type", "kutcha", "assumed kutcha house")
        elif fact == "lpg":
            p["has_lpg_connection"] = False
            _assume(p, "lpg", "has_lpg_connection", False, "assumed no gas connection")
    return p


UNKNOWN = {
    "income": lambda p: p.get("annual_family_income_inr") is None,
    "ration_card": lambda p: p.get("ration_card") in (None, "unknown"),
    "area": lambda p: p.get("area") in (None, "unknown"),
    "house": lambda p: p.get("house_type") in (None, "unknown"),
    "land": lambda p: p.get("land_acres") is None,
    "lpg": lambda p: p.get("has_lpg_connection") is None,
}


def assumed_facts_for(scheme_id: str, profile: dict) -> list[str]:
    """Facts that could change this scheme's eligibility and were assumed or are still unknown
    (e.g. land for PM-KISAN when nobody said who owns land)."""
    facts = {a["fact"] for a in profile.get("assumptions", []) if scheme_id in AFFECTS.get(a["fact"], ())}
    facts |= {f for f, unknown in UNKNOWN.items() if scheme_id in AFFECTS.get(f, ()) and unknown(profile)}
    return sorted(facts)


def summarize_profile(p: dict) -> str:
    return json.dumps({"members": [(m["relation"], m["age"], m["occupation"]) for m in p["members"]],
                       "income": p.get("annual_family_income_inr"), "ration": p.get("ration_card")},
                      ensure_ascii=False)
