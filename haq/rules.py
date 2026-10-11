"""Hard eligibility rules checked in plain code, after (and independent of) the model.

The model's judgment is not deterministic, so anything that is a clear rule is enforced here instead:
a card that breaks a rule is dropped with a reason, whatever the research said. Rules only fire on facts
the family actually gave (an unknown age never drops a scheme; it becomes "check needed" elsewhere).

Used in three places: planning (do not research what cannot apply), writing results, and showing
results saved earlier. One pension per person and one-time-vs-yearly money are applied when totals
are computed (see present._view), because they change what is counted, not whether a scheme shows.
"""
from . import catalog

# (min_age, max_age) for the member the scheme is for; None = no bound
AGE = {
    "up_old_age_pension": (60, None), "ayushman_vay_vandana": (70, None),
    "pm_sym": (18, 40), "pm_kisan_maandhan": (18, 40),
    "pmjjby": (18, 50), "pmsby": (18, 70), "up_widow_pension": (18, None),
}
HOUSEHOLD_WORDS = {"household", "whole family", "family", "पूरा परिवार", "परिवार"}


def find_member(member: str, profile: dict) -> dict | None:
    """The profile member a card is for (by relation or name), or None for household-level / unclear."""
    key = " ".join((member or "").lower().replace("(", " ").replace(")", " ").split())
    if not key or key in HOUSEHOLD_WORDS:
        return None
    first = key.split()[0]
    alias = {"you": "self", "me": "self", "आप": "self"}
    for m in profile.get("members", []):
        rel = (m.get("relation") or "").lower()
        name = (m.get("name") or "").lower()
        if rel and (rel == key or rel == first or rel == alias.get(first)) or (len(name) >= 3 and name in key.split()):
            return m
    return None


def _pregnancy_or_infant(profile: dict) -> bool:
    return any(m.get("is_pregnant") is True or (m.get("age") is not None and m["age"] < 1)
               for m in profile.get("members", []))


def violation(scheme_id: str, member: str, profile: dict) -> str | None:
    """Why this scheme cannot apply to this member of this family, or None."""
    sid = catalog.canonical_id(scheme_id)
    m = find_member(member, profile)
    if sid == "pmmvy" and not _pregnancy_or_infant(profile):
        return "PMMVY needs a pregnancy or a child under 1, and none was mentioned"
    if sid == "pm_kisan":
        if profile.get("land_acres") == 0:
            return "PM-KISAN needs farmland in the family's name; the family said there is none"
        if m and (m.get("income_tax_payer") is True or m.get("govt_employee_or_pensioner") is True):
            return "PM-KISAN excludes income-tax payers and government employees/pensioners"
    if m:
        age = m.get("age")
        lo, hi = AGE.get(sid, (None, None))
        if age is not None and lo is not None and age < lo:
            return f"{sid} needs age {lo}+; {m.get('relation')} is {age}"
        if age is not None and hi is not None and age > hi:
            return f"{sid} is for ages up to {hi}; {m.get('relation')} is {age}"
        if sid == "up_widow_pension" and m.get("is_widow") is False:
            return "widow pension is only for a woman whose husband has died"
        if sid == "up_divyang_pension" and m.get("disability_percent") is not None and m["disability_percent"] < 40:
            return "disability pension needs 40% or more disability"
        if sid == "up_kanya_sumangala" and m.get("gender") == "male":
            return "Kanya Sumangala is for girls"
    return None


def post_check(cards: list[dict], profile: dict | None) -> tuple[list[dict], list[dict]]:
    """Drop cards that break a hard rule. Returns (kept, dropped-with-reason). Deterministic."""
    if not profile:
        return cards, []
    kept, dropped = [], []
    for c in cards:
        why = violation(c["scheme_id"], c.get("member", ""), profile)
        if why:
            dropped.append({"scheme_id": c["scheme_id"], "member": c.get("member"), "reason": why})
        else:
            kept.append(c)
    return kept, dropped
