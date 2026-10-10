"""Results in the family's chosen language (Hindi or English), ready for the cards.

Research writes card text in Hindi. Hindi is served as-is. English is translated once by Haiku and
cached on the run, so switching language costs one small call per household. Official scheme names
stay as they are (e.g. "PM-KISAN"); only the explanation around them is translated.
"""
import json
import threading

import neatlogs

from . import catalog, state
from .config import FAST_MODEL
from .llm import structured

ROLE_LABELS = {
    "self": {"hi": "आप", "en": "You"}, "household": {"hi": "पूरा परिवार", "en": "Whole family"},
    "father": {"hi": "पापा", "en": "Father"}, "mother": {"hi": "माँ", "en": "Mother"},
    "grandfather": {"hi": "दादा", "en": "Grandfather"}, "grandmother": {"hi": "दादी", "en": "Grandmother"},
    "son": {"hi": "बेटा", "en": "Son"}, "daughter": {"hi": "बेटी", "en": "Daughter"},
    "wife": {"hi": "पत्नी", "en": "Wife"}, "husband": {"hi": "पति", "en": "Husband"},
    "daughter-in-law": {"hi": "बहू", "en": "Daughter-in-law"}, "son-in-law": {"hi": "दामाद", "en": "Son-in-law"},
    "grandson": {"hi": "पोता", "en": "Grandson"}, "granddaughter": {"hi": "पोती", "en": "Granddaughter"},
    "brother": {"hi": "भाई", "en": "Brother"}, "sister": {"hi": "बहन", "en": "Sister"},
}

TRANSLATE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["cards", "summary"],
    "properties": {
        "summary": {"type": "string"},
        "cards": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["i", "member", "benefit", "documents", "where_to_apply", "scheme_name"],
            "properties": {"i": {"type": "integer"}, "member": {"type": "string"}, "benefit": {"type": "string"},
                           "documents": {"type": "array", "items": {"type": "string"}},
                           "where_to_apply": {"type": "string"}, "scheme_name": {"type": "string"}}}},
    },
}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _member_label(member: str, lang: str) -> str | None:
    key = " ".join((member or "").lower().replace("(", " ").replace(")", " ").split()[:1])
    full = (member or "").strip().lower()
    return (ROLE_LABELS.get(full) or ROLE_LABELS.get(key) or {}).get(lang)


def _scheme_name(card: dict) -> str:
    seed = catalog.BY_ID.get(card["scheme_id"])
    return seed["name_en"] if seed else card.get("name_hi") or card["scheme_id"]


def _view(result: dict, lang: str, tr: dict | None) -> dict:
    cards = []
    for i, c in enumerate(result["cards"]):
        t = (tr or {}).get(i, {})
        cards.append({
            "scheme_id": c["scheme_id"], "emoji": c["emoji"],
            "name": _scheme_name(c) if catalog.BY_ID.get(c["scheme_id"]) else (t.get("scheme_name") or c["name_hi"]),
            "member": _member_label(c["member"], lang) or t.get("member") or c["member"],
            "benefit": t.get("benefit") or c["benefit_hi"],
            "documents": t.get("documents") or c["documents_hi"],
            "where_to_apply": t.get("where_to_apply") or c["where_to_apply_hi"],
            "annual_value_inr": c["annual_value_inr"],
            "verification": c["verification"],
            "check_needed": c.get("check_needed") or (["income_limit"] if c["verification"] == "likely" else []),
            "counts_toward_total": c["counts_toward_total"],
            "already_receiving": c["already_receiving"],
            "apply_url": c["apply_url"], "official_url": c["official_url"],
        })
    return {"lang": lang, "total_missing_inr_per_year": result["total_missing_inr_per_year"],
            "likely_extra_inr_per_year": result.get("likely_extra_inr_per_year", 0),
            "summary": (tr or {}).get("summary") or result["summary_hi"], "cards": cards}


def localized(hid: str, run_id: str, result: dict, lang: str) -> dict:
    if lang != "en":
        return _view(result, "hi", None)
    cached = (result.get("i18n") or {}).get("en")
    if cached is None:
        with _locks_guard:
            lock = _locks.setdefault(hid, threading.Lock())
        with lock:  # one translation per household even if the page polls in parallel
            h = state.get(hid)
            run = next((r for r in h["runs"] if r["id"] == run_id), None)
            cached = ((run or {}).get("result") or {}).get("i18n", {}).get("en")
            if cached is None:
                cached = _translate(hid, result)
                state.update_run(hid, run_id, lambda r: r["result"].setdefault("i18n", {}).update(en=cached))
    tr = {c["i"]: c for c in cached["cards"]}
    tr["summary"] = cached["summary"]
    return _view(result, "en", tr)


def _translate(hid: str, result: dict) -> dict:
    src = {"summary_hi": result["summary_hi"],
           "cards": [{"i": i, "member": c["member"], "scheme_name_hi": c["name_hi"], "benefit_hi": c["benefit_hi"],
                      "documents_hi": c["documents_hi"], "where_to_apply_hi": c["where_to_apply_hi"]}
                     for i, c in enumerate(result["cards"])]}
    with neatlogs.trace("translate_results", kind="CHAIN", session_id=hid, lang="en"):
        return structured(
            None, model=FAST_MODEL, effort="low", max_tokens=8000, schema=TRANSLATE_SCHEMA,
            system="Translate these welfare-scheme results from Hindi to plain, simple English for a family with "
                   "little schooling (short sentences, no jargon). Keep official scheme and portal names exactly "
                   "as written (e.g. PM-KISAN, Ayushman Bharat, sspy-up.gov.in). Keep every rupee amount. "
                   "summary: the spoken summary, max 70 words. member: who it is for, in English.",
            user=json.dumps(src, ensure_ascii=False))
