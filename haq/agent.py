"""Haq agent: INTERVIEW -> PLAN -> RESEARCH -> VERIFY -> (RECOVER) -> WRITE.

Every stage is a neatlogs span; every Claude call is an LLM span via the
wrapped client; every tool execution is a TOOL span. Run progress is saved to
the state file after each step so a crashed run resumes where it stopped.
"""
import contextvars
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import neatlogs

from . import cache, catalog, fetcher, state
from .config import FAST_MODEL, VERIFY_MODEL
from .llm import Usage, create, structured, system_blocks

RESEARCH_WORKERS = 4
MAX_RESEARCH_TURNS = 6
MAX_SEARCHES = 2            # web searches per scheme lookup
BUDGET_NOTE = ("SEARCH BUDGET USED UP (2 searches): do not call web_search again. Use fetch_official_page on "
               "official URLs you already found, then finish with record_verified or drop_scheme.")
RESEARCH_DEADLINE_S = 420   # wall-clock budget for one scheme's research loop


class RunAborted(Exception):
    """Another lookup in this run hit an error that every call would hit (auth, billing)."""

# --------------------------------------------------------------------------
# Profile schema (shared by the interview, the eval set and the planner)
# --------------------------------------------------------------------------
NULL_STR = {"type": ["string", "null"]}
NULL_BOOL = {"type": ["boolean", "null"]}
NULL_NUM = {"type": ["number", "null"]}

MEMBER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "relation", "age", "gender", "occupation", "is_widow",
                 "disability_percent", "is_student", "student_class", "is_pregnant",
                 "income_tax_payer", "govt_employee_or_pensioner"],
    "properties": {
        "name": NULL_STR,
        "relation": {"type": "string", "description": "relation to the person answering, e.g. self, wife, son, mother"},
        "age": NULL_NUM,
        "gender": {"type": "string", "enum": ["male", "female", "other", "unknown"]},
        "occupation": {"type": "string", "description": "farmer, daily_wage, construction_worker, artisan:<trade>, homemaker, student, unemployed, salaried, small_business, retired, child, unknown"},
        "is_widow": NULL_BOOL,
        "disability_percent": NULL_NUM,
        "is_student": NULL_BOOL,
        "student_class": NULL_STR,
        "is_pregnant": NULL_BOOL,
        "income_tax_payer": NULL_BOOL,
        "govt_employee_or_pensioner": NULL_BOOL,
    },
}

PROFILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["district", "area", "annual_family_income_inr", "ration_card", "house_type",
                 "has_lpg_connection", "has_bank_account", "caste_category", "land_acres",
                 "land_owner_relation", "already_receiving", "upcoming_events", "members"],
    "properties": {
        "district": NULL_STR,
        "area": {"type": "string", "enum": ["rural", "urban", "unknown"]},
        "annual_family_income_inr": NULL_NUM,
        "ration_card": {"type": "string", "enum": ["none", "eligible_household", "antyodaya", "unknown"]},
        "house_type": {"type": "string", "enum": ["pucca", "kutcha", "homeless", "unknown"]},
        "has_lpg_connection": NULL_BOOL,
        "has_bank_account": NULL_BOOL,
        "caste_category": {"type": "string", "enum": ["general", "obc", "sc", "st", "not_shared"]},
        "land_acres": NULL_NUM,
        "land_owner_relation": NULL_STR,
        "already_receiving": {"type": "array", "items": {"type": "string"}},
        "upcoming_events": {"type": "array", "items": {"type": "string"},
                            "description": "e.g. 'daughter (19) marriage in 3 months', 'baby due'"},
        "members": {"type": "array", "items": MEMBER_SCHEMA},
    },
}

# --------------------------------------------------------------------------
# 1. INTERVIEW
# --------------------------------------------------------------------------
INTERVIEW_SYSTEM = """You are Haq (हक़), a kind helper for poor and often non-literate families in Uttar Pradesh.
You interview ONE family to find government schemes they are entitled to. Your words are read aloud.

Rules for questions:
- Hindi in Devanagari, very simple village Hindi, max 15 words, ONE question at a time.
- Prefer yes/no or a number. Never use English jargon (say "ज़मीन" not "land holding").
- Ask in this rough order, skipping anything already known: who lives in the house (ages, men/women),
  work of each adult, farm land and whose name it is in, rough yearly income, village or city + district,
  ration card type, pucca/kutcha house, gas connection, any widow, any disabled member (and %),
  children studying (class), anyone pregnant, any marriage coming up in the family (record in upcoming_events),
  govt job / income-tax payer, schemes already received.
- NEVER ask about caste. Record caste_category only if the user volunteers it; otherwise "not_shared".
- Stop (done=true) once you know members with ages/gender/occupation, area, income band, land, ration card,
  house type, and widow/disability/student/pregnancy status. Usually 6-10 questions. Do not over-ask.
- Keep everything already learned in the profile; update it with each answer. Unknown values stay null/"unknown".
- When done, next_question_hi is a short thank-you saying you will now search the schemes."""

INTERVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["profile", "done", "next_question_hi"],
    "properties": {
        "profile": PROFILE_SCHEMA,
        "done": {"type": "boolean"},
        "next_question_hi": {"type": "string"},
    },
}

GREETING_HI = "नमस्ते! मैं हक़ हूँ। मैं आपके परिवार के लिए सरकारी योजनाएँ ढूँढूँगा। आपके घर में कुल कितने लोग रहते हैं?"


def empty_profile() -> dict:
    return {"district": None, "area": "unknown", "annual_family_income_inr": None,
            "ration_card": "unknown", "house_type": "unknown", "has_lpg_connection": None,
            "has_bank_account": None, "caste_category": "not_shared", "land_acres": None,
            "land_owner_relation": None, "already_receiving": [], "upcoming_events": [], "members": []}


def interview_turn(hid: str, user_text: str) -> dict:
    """Record the user's answer, update the profile, return the next question."""
    h = state.get(hid)
    with neatlogs.trace("interview_turn", kind="AGENT", session_id=hid, end_user_id=hid):
        msgs = h["interview"]["messages"] + [{"role": "user", "text": user_text}]
        transcript = "\n".join(f"{'Family' if m['role'] == 'user' else 'Haq'}: {m['text']}" for m in msgs)
        profile = h["profile"] or empty_profile()
        out = structured(
            None, model=FAST_MODEL, system=INTERVIEW_SYSTEM, effort="low", max_tokens=8000, schema=INTERVIEW_SCHEMA,
            user=f"Current profile JSON:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
                 f"Conversation so far:\n{transcript}\n\nUpdate the profile and give the next question.",
        )

    def _save(hh):
        hh["interview"]["messages"] = msgs + [{"role": "assistant", "text": out["next_question_hi"]}]
        hh["interview"]["done"] = out["done"]
        hh["profile"] = out["profile"]

    state.update(hid, _save)
    return out


# --------------------------------------------------------------------------
# 2. PLAN
# --------------------------------------------------------------------------
PLAN_SYSTEM = f"""You plan research for Haq, which finds Indian government schemes for a family in Uttar Pradesh.
Scope: central government schemes and Uttar Pradesh state schemes only.

Known scheme catalog (ids you should use):
{catalog.catalog_for_prompt()}

From the household profile, list every scheme that each member (or the household as a whole) is
PLAUSIBLY eligible for, so it can be verified on official sources. Be inclusive but not silly:
skip a scheme only if the profile clearly rules it out (e.g. no farmland -> no PM-KISAN, nobody 60+ -> no old age pension,
income-tax payer -> most welfare schemes out). Household-level schemes (ration card, PM-JAY, PMAY-G, Ujjwala)
get member "household" (Ujjwala: the adult woman). Use catalog ids; only invent a new snake_case id for a
clearly relevant central/UP scheme that is missing from the catalog. Skip schemes listed in already_receiving
unless the profile suggests another member also qualifies. A family whose ration_card is "eligible_household" or
"antyodaya" already gets NFSA ration: do not plan nfsa_ration for them.
Event-triggered one-time grants (up_shadi_anudan, up_samuhik_vivah) are only for a marriage that is actually
coming up: plan them only if the profile says a daughter (18+) or a widow is getting married soon. Never plan
them for children or just because there is a daughter in the family. At most 14 candidates."""

MARRIAGE_GRANTS = {"up_shadi_anudan", "up_samuhik_vivah"}


def marriage_planned(profile: dict) -> bool:
    """True only if the profile mentions an upcoming marriage of an adult member."""
    text = json.dumps(profile.get("upcoming_events", []), ensure_ascii=False).lower()
    return any(w in text for w in ("marriage", "wedding", "शादी", "विवाह", "byah", "ब्याह"))


HOUSEHOLD_SCHEMES = {"nfsa_ration", "pmjay", "pmay_g"}


def already_has(profile: dict) -> set[str]:
    """Scheme ids the family already receives, from what they told us and from facts like a ration card."""
    have = {catalog.canonical_id(s) for s in profile.get("already_receiving", [])}
    if profile.get("ration_card") in ("eligible_household", "antyodaya"):
        have.add("nfsa_ration")
    return have

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {"candidates": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["scheme_id", "member", "why"],
        "properties": {
            "scheme_id": {"type": "string"},
            "member": {"type": "string", "description": "relation/name of the member, or 'household'"},
            "why": {"type": "string"},
        }}}},
}


def plan(profile: dict, usage: Usage, hid: str) -> list[dict]:
    with neatlogs.trace("plan", kind="CHAIN", session_id=hid):
        out = structured(usage, model=FAST_MODEL, system=PLAN_SYSTEM, effort="medium", schema=PLAN_SCHEMA,
                         user=f"Household profile:\n{json.dumps(profile, ensure_ascii=False, indent=1)}")
    seen, cands = set(), []
    have = already_has(profile)
    for c in out["candidates"]:
        c["scheme_id"] = catalog.canonical_id(c["scheme_id"])
        if c["scheme_id"] in have and c["scheme_id"] in HOUSEHOLD_SCHEMES:
            continue  # one per family, and this family already gets it
        if c["scheme_id"] in MARRIAGE_GRANTS and not marriage_planned(profile):
            continue  # one-time grant for a wedding nobody mentioned
        key = f"{c['scheme_id']}:{c['member'].strip().lower()}"
        if key not in seen:
            seen.add(key)
            cands.append({**c, "key": key})
    return cands


# --------------------------------------------------------------------------
# 3-5. RESEARCH + VERIFY + RECOVER (one agent loop per candidate)
# --------------------------------------------------------------------------
RESEARCH_SYSTEM = """You are Haq's research agent. You verify ONE government scheme for ONE member of a family in Uttar Pradesh.

Method:
1. You have AT MOST 2 web searches for this scheme (none if cached official rules are given). Use them to
   find the official page or rule document; prefer *.gov.in, *.nic.in, myscheme.gov.in, the scheme's portal.
   STOP as soon as an official page confirms the rules you need: call record_verified in that same turn.
   Do not search again to re-confirm something an official page already confirmed.
2. Confirm EVERY eligibility rule you rely on against an OFFICIAL page. Use fetch_official_page to read an
   official URL directly (it retries and falls back to other official sources automatically). An official
   page that appears in your web_search results also counts as read. Portal home pages often lack the rules:
   then read the scheme's official rule documents (guidelines / niyamawali / shasanadesh PDFs on .gov.in or
   .nic.in; fetch_official_page extracts PDF text) or search for them before giving up.
3. Non-government sources (news, blogs, banks, coaching/scholarship sites) may only guide you. In your final
   call, list in unofficial_sources every non-government page from your searches whose claim you looked at,
   with verdict: "agrees" (the official page says the same), "conflicts" (the official page says something
   different; the official one is trusted) or "not_on_official_source" (no official page states it, so it is
   NOT used as a confirmed rule). You may also call log_conflict as soon as you notice a conflict.
4. Finish by calling exactly ONE of:
   - record_verified with verification="confirmed": the member qualifies and you confirmed EVERY rule you rely
     on (including any income limit) on an official page.
   - record_verified with verification="likely": you confirmed the scheme's core eligibility on an official page
     (who it is for, e.g. "widow aged 18+ resident of UP", "rural household in a kutcha house", "student of class
     9-10") and the member clearly meets it, but the ONLY rule you could not find on an official page is the
     income limit / poverty-line criterion. List that in unconfirmed_rules. The family will be told
     "Likely eligible - confirm income limit". If the member's income is clearly above a limit you did confirm,
     drop instead.
   - drop_scheme: the member does not qualify, or you could not confirm the core eligibility on any official page.
   Never record a scheme whose core eligibility you could only confirm on unofficial sites.

Facts that are unknown in the profile do not disqualify by themselves; judge on what is known and note the
assumption in assumptions_hi. annual_value_inr: yearly cash or cash-equivalent value for this member
(pension 1000/month -> 12000; one-time grants: the amount; insurance/health cover or contributory schemes: 0
with counts_toward_total=false). Write all *_hi fields in simple Hindi (Devanagari) for a non-literate family."""

UNOFFICIAL_SOURCES_SCHEMA = {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "required": ["url", "claim", "official_says", "official_url", "verdict"],
    "properties": {
        "url": {"type": "string"},
        "claim": {"type": "string"},
        "official_says": {"type": "string", "description": "empty if no official page states it"},
        "official_url": {"type": "string"},
        "verdict": {"type": "string", "enum": ["agrees", "conflicts", "not_on_official_source"]},
    }}}

TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES,
     "user_location": {"type": "approximate", "country": "IN", "region": "Uttar Pradesh", "timezone": "Asia/Kolkata"}},
    {
        "name": "fetch_official_page",
        "description": "Fetch the text of an OFFICIAL government web page or PDF rule document (.gov.in / .nic.in / scheme portal). "
                       "Retries with backoff and falls back to other official URLs for the same scheme if it fails. "
                       "Non-official URLs are refused.",
        "strict": True,
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["url", "query"],
                         "properties": {"url": {"type": "string"},
                                        "query": {"type": "string", "description": "keywords to focus on, e.g. 'eligibility age income'"}}},
    },
    {
        "name": "log_conflict",
        "description": "Record that an unofficial source conflicts with an official one, and which you trusted.",
        "strict": True,
        "input_schema": {"type": "object", "additionalProperties": False,
                         "required": ["topic", "official_url", "official_says", "unofficial_url", "unofficial_says", "reason"],
                         "properties": {k: {"type": "string"} for k in
                                        ["topic", "official_url", "official_says", "unofficial_url", "unofficial_says", "reason"]}},
    },
    {
        "name": "record_verified",
        "description": "Final answer: eligible (verification=confirmed), or core eligibility confirmed on an official "
                       "page with only the income limit unconfirmed (verification=likely).",
        "strict": True,
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["scheme_id", "scheme_name_hi", "member", "official_url", "verification", "rules_checked",
                         "unconfirmed_rules", "benefit_hi", "annual_value_inr", "counts_toward_total", "documents_hi",
                         "where_to_apply_hi", "apply_url", "assumptions_hi", "unofficial_sources"],
            "properties": {
                "scheme_id": {"type": "string"},
                "scheme_name_hi": {"type": "string"},
                "member": {"type": "string"},
                "official_url": {"type": "string", "description": "official page where the rules were confirmed"},
                "verification": {"type": "string", "enum": ["confirmed", "likely"]},
                "unconfirmed_rules": {"type": "array", "items": {"type": "string"},
                                      "description": "empty for confirmed; for likely, the income-limit rule(s) not found officially"},
                "rules_checked": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["rule", "member_fact", "official_url"],
                    "properties": {"rule": {"type": "string"}, "member_fact": {"type": "string"},
                                   "official_url": {"type": "string"}}}},
                "benefit_hi": {"type": "string"},
                "annual_value_inr": {"type": "integer"},
                "counts_toward_total": {"type": "boolean"},
                "documents_hi": {"type": "array", "items": {"type": "string"}},
                "where_to_apply_hi": {"type": "string"},
                "apply_url": {"type": "string"},
                "assumptions_hi": {"type": "string"},
                "unofficial_sources": UNOFFICIAL_SOURCES_SCHEMA,
            },
        },
    },
    {
        "name": "drop_scheme",
        "description": "Final answer: not eligible, or could not be verified on an official source.",
        "strict": True,
        "input_schema": {"type": "object", "additionalProperties": False,
                         "required": ["scheme_id", "member", "reason", "official_url", "unofficial_sources"],
                         "properties": {"scheme_id": {"type": "string"}, "member": {"type": "string"},
                                        "reason": {"type": "string"},
                                        "official_url": {"type": "string", "description": "official page used, or empty"},
                                        "unofficial_sources": UNOFFICIAL_SOURCES_SCHEMA}},
    },
]


# Chosen once per loop and never changed mid-loop: editing the tool list invalidates the prompt cache and,
# on Sonnet 5.5, counts as a history edit for the conversation's thinking blocks.
TOOLS_NO_SEARCH = [t for t in TOOLS if t["name"] != "web_search"]


def _search_result_urls(content) -> list[str]:
    urls = []
    for b in content:
        if b.type == "web_search_tool_result" and isinstance(b.content, list):
            urls.extend(r.url for r in b.content if getattr(r, "url", None))
    return urls


def _norm(url: str) -> str:
    return url.strip().rstrip("/").lower().replace("http://", "https://").replace("://www.", "://")


def research_one(profile: dict, cand: dict, usage: Usage, hid: str, run_id: str,
                 abort: threading.Event | None = None) -> dict:
    """Agent loop for a single (scheme, member). Returns a verified or dropped record."""
    seed = catalog.BY_ID.get(cand["scheme_id"])
    if seed:
        docs = seed.get("rules_docs", [])
        seed_txt = (f"Known official starting points: {', '.join(seed['official_urls'] + seed['fallback_urls'])}\n"
                    + (f"Official rule documents (PDF, readable with fetch_official_page): {', '.join(docs)}\n"
                       if docs else "")
                    + f"Catalog note (re-verify, may be outdated): {seed['hint']}")
    else:
        seed_txt = "Not in catalog."
    cached_rules = cache.get_rules(cand["scheme_id"])
    # Shared instructions, then this scheme's context (same for every member/family), then the family.
    system = system_blocks(RESEARCH_SYSTEM, f"SCHEME: {cand['scheme_id']}\n{seed_txt}"
                           + ("\n\n" + rules_block(cached_rules) if cached_rules else ""))
    user = (f"Scheme to verify: {cand['scheme_id']}\nMember: {cand['member']}\nWhy planned: {cand['why']}\n\n"
            f"Household profile:\n{json.dumps(profile, ensure_ascii=False)}")
    messages = [{"role": "user", "content": user}]
    ctx = {
        "read_official": set(),     # official URLs successfully read (fetch or search result)
        "unofficial_seen": set(),   # non-government URLs that came back in web_search results
        "conflicts": [],            # official vs unofficial disagreements (official trusted)
        "unofficial_claims": [],    # claims found only on non-government pages (not used as rules)
        "recovery": [],
        "asked_for_sources": False,
    }
    if cached_rules:
        # Rules confirmed on these official pages by an earlier lookup count as read.
        ctx["read_official"].update(_norm(r["official_url"]) for r in cached_rules["rules"])
        ctx["read_official"].add(_norm(cached_rules["official_url"]))

    started = time.time()
    tools = TOOLS_NO_SEARCH if cached_rules else TOOLS
    searches, budget_noted, over_budget_turn = 0, False, None
    with neatlogs.trace(f"research:{cand['key']}", kind="AGENT", session_id=hid):
        for turn in range(MAX_RESEARCH_TURNS):
            if abort is not None and abort.is_set():
                raise RunAborted("run aborted after a fatal API error in another lookup")
            if time.time() - started > RESEARCH_DEADLINE_S:
                return {**_dropped(cand, f"time budget ({RESEARCH_DEADLINE_S}s) exhausted without official "
                                         "confirmation", ""), **_logs(ctx)}
            if over_budget_turn is not None and turn > over_budget_turn:
                return {**_dropped(cand, "search budget exceeded without official confirmation", ""),
                        **_logs(ctx), "searches": searches}
            resp = create(usage, model=VERIFY_MODEL, effort="medium", system=system, tools=tools,
                          messages=messages, loop=True)
            messages.append({"role": "assistant", "content": resp.content})
            searches += getattr(getattr(resp.usage, "server_tool_use", None), "web_search_requests", 0) or 0
            if searches > MAX_SEARCHES and over_budget_turn is None:
                over_budget_turn = turn + 1   # one more turn to finish, then stop
            for u in _search_result_urls(resp.content):
                (ctx["read_official"] if catalog.is_official(u) else ctx["unofficial_seen"]).add(_norm(u))

            if resp.stop_reason == "pause_turn":
                continue  # server tool still working; resend to let it finish
            if resp.stop_reason == "refusal":
                return {**_dropped(cand, "model declined", ""), **_logs(ctx)}
            note = []  # appended to the next user message, after any tool results
            if searches >= MAX_SEARCHES and not budget_noted:
                budget_noted = True
                note = [{"type": "text", "text": BUDGET_NOTE}]
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                messages.append({"role": "user", "content": note + [
                    {"type": "text", "text": "Finish by calling record_verified or drop_scheme."}]})
                continue

            results, final = [], None
            for tu in tool_uses:
                out, is_err, fin = _run_tool(tu.name, tu.input, cand, ctx)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": out, **({"is_error": True} if is_err else {})})
                final = final or fin
            messages.append({"role": "user", "content": results + note})
            if final:
                final.update(**_logs(ctx), turns=turn + 1, rules_from_cache=bool(cached_rules), searches=searches)
                if final["status"] in ("verified", "likely"):
                    cache.put_rules(final, source=f"{hid}:{run_id}:{cand['key']}")
                return final

    return {**_dropped(cand, "verification budget exhausted without official confirmation", ""), **_logs(ctx),
            "searches": searches}


def rules_block(cached: dict) -> str:
    """Scheme rules confirmed on official pages by an earlier lookup, for the research prompt."""
    when = time.strftime("%Y-%m-%d", time.localtime(cached["cached_at"]))
    lines = [f"CACHED OFFICIAL RULES for {cached['scheme_id']} (confirmed on official pages on {when}; these "
             "official URLs count as already read):"]
    lines += [f"- {r['rule']}  [source: {r['official_url']}]" for r in cached["rules"]]
    if cached.get("unconfirmed_rules"):
        lines.append(f"Not confirmed on any official page yet: {'; '.join(cached['unconfirmed_rules'])}")
    lines.append(f"Documents: {', '.join(cached.get('documents_hi', []))}")
    lines.append(f"Where to apply: {cached.get('where_to_apply_hi', '')} {cached.get('apply_url', '')}")
    lines.append(f"Benefit as described for another family: {cached.get('benefit_example_hi', '')}")
    lines.append("Use these rules; do not search the web again for them. If a rule you need for this member is "
                 "missing (e.g. an income limit), read the cited official page with fetch_official_page "
                 "(cached pages are free) or use verification=likely.")
    return "\n".join(lines)


def _dropped(cand, reason, url):
    return {"status": "dropped", "scheme_id": cand["scheme_id"], "member": cand["member"],
            "reason": reason, "official_url": url}


def _logs(ctx):
    return {"conflicts": ctx["conflicts"], "unofficial_claims": ctx["unofficial_claims"],
            "recovery_log": ctx["recovery"]}


def _object_list(value) -> list[dict]:
    """Tool inputs occasionally arrive with a nested array serialised as a JSON string, or as bare URLs.
    Normalise to a list of dicts so one odd tool call cannot crash a research loop."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [value] if value.strip() else []
    out = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str) and item.strip():
            out.append({"url": item.strip()})
    return out


def _account_for_unofficial(args, cand, ctx):
    """Turn the agent's unofficial_sources list into conflict / unofficial-claim records.

    Returns a rejection message if non-government pages came back in search but none were
    accounted for (asked once per loop, so a stubborn model cannot stall the run)."""
    defaults = {"url": "", "claim": "", "official_says": "", "official_url": "", "verdict": "not_on_official_source"}
    listed = [{**defaults, **s} for s in _object_list(args.get("unofficial_sources", []))]
    listed = [s for s in listed if s["url"] and not catalog.is_official(s["url"])]
    if ctx["unofficial_seen"] and not listed and not ctx["asked_for_sources"]:
        ctx["asked_for_sources"] = True
        seen = sorted(ctx["unofficial_seen"])[:12]
        return ("REJECTED: your searches returned non-government pages "
                f"{seen}. List in unofficial_sources each one whose claim you looked at, with verdict "
                "agrees / conflicts / not_on_official_source, then call this tool again.")
    for src in listed:
        if src["verdict"] == "conflicts":
            ctx["conflicts"].append({
                "topic": cand["scheme_id"], "unofficial_url": src["url"], "unofficial_says": src["claim"],
                "official_url": src["official_url"], "official_says": src["official_says"],
                "reason": "official government source trusted over non-government source"})
        elif src["verdict"] == "not_on_official_source":
            ctx["unofficial_claims"].append({
                "topic": cand["scheme_id"], "unofficial_url": src["url"], "claim": src["claim"],
                "reason": "not stated on any official page read; not used as a confirmed rule"})
    return None


def _run_tool(name, args, cand, ctx):
    """Execute a client tool. Returns (content_str, is_error, final_record_or_None)."""
    with neatlogs.trace(f"tool:{name}", kind="TOOL", tool_name=name, input=json.dumps(args, ensure_ascii=False)[:2000]):
        if name == "fetch_official_page":
            r = fetcher.fetch_official(args["url"], cand["scheme_id"], args.get("query"))
            failed = [a for a in r["attempts"] if not a["ok"]]
            if failed or r.get("fell_back"):
                ctx["recovery"].append({"requested": args["url"], "served_by": r["url"] if r["ok"] else None,
                              "ok": r["ok"], "attempts": r["attempts"]})
            if not r["ok"]:
                return (f"FAILED: {r.get('error')}. Attempts: {json.dumps(r['attempts'], ensure_ascii=False)}. "
                        "Try another official URL (web_search for it) or drop the scheme."), True, None
            ctx["read_official"].add(_norm(r["url"]))
            note = f"(requested {args['url']} failed; served by official fallback {r['url']})\n" if r.get("fell_back") else ""
            return f"{note}SOURCE: {r['url']}\n\n{r['text']}", False, None

        if name == "log_conflict":
            ctx["conflicts"].append({**args, "topic": f"{cand['scheme_id']}: {args['topic']}"})
            return "conflict logged; continue using the official source", False, None

        if name in ("drop_scheme", "record_verified"):
            rejection = _account_for_unofficial(args, cand, ctx)
            if rejection:
                return rejection, True, None

        if name == "drop_scheme":
            return "ok", False, _dropped(cand, args["reason"], args.get("official_url", ""))

        if name == "record_verified":
            args["rules_checked"] = [r for r in _object_list(args.get("rules_checked", [])) if "official_url" in r]
            urls = [args["official_url"]] + [r["official_url"] for r in args["rules_checked"]]
            bad = [u for u in urls if not catalog.is_official(u)]
            unread = [u for u in urls if catalog.is_official(u) and _norm(u) not in ctx["read_official"]]
            if bad or unread or not args["rules_checked"]:
                msg = ("REJECTED: every rule must cite an official URL you actually read in this session. "
                       f"Non-official: {bad}. Not read yet: {unread}. Read them with fetch_official_page "
                       "(or cite an official URL from your search results), or call drop_scheme.")
                return msg, True, None
            if args["verification"] == "likely" and not args["unconfirmed_rules"]:
                return ("REJECTED: verification=likely needs unconfirmed_rules naming the income-limit rule you "
                        "could not confirm. If everything is confirmed, use verification=confirmed."), True, None
            if args["verification"] == "confirmed":
                args["unconfirmed_rules"] = []
            status = "verified" if args["verification"] == "confirmed" else "likely"
            rec = {**args, "status": status, "scheme_id": catalog.canonical_id(args["scheme_id"])}
            return "recorded", False, rec

        return f"unknown tool {name}", True, None


# --------------------------------------------------------------------------
# 6. WRITE
# --------------------------------------------------------------------------
LIKELY_LABEL_EN = "Likely eligible — confirm income limit"
LIKELY_LABEL_HI = "शायद पात्र — आय सीमा की पुष्टि करें"

SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary_hi"],
                  "properties": {"summary_hi": {"type": "string"}}}


def write(profile: dict, research: dict, usage: Usage, hid: str) -> dict:
    with neatlogs.trace("write", kind="CHAIN", session_id=hid):
        received = already_has(profile)
        cards = []
        for rec in research.values():
            if rec.get("status") not in ("verified", "likely"):
                continue
            likely = rec["status"] == "likely"
            seed = catalog.BY_ID.get(rec["scheme_id"], {})
            already = rec["scheme_id"] in received
            cards.append({
                "scheme_id": rec["scheme_id"],
                "emoji": seed.get("emoji", "📄"),
                "name_hi": rec["scheme_name_hi"],
                "name_en": seed.get("name_en", rec["scheme_id"]),
                "level": seed.get("level", "central"),
                "member": rec["member"],
                "benefit_hi": rec["benefit_hi"],
                "annual_value_inr": rec["annual_value_inr"],
                "verification": "likely" if likely else "confirmed",
                "label_en": LIKELY_LABEL_EN if likely else "Confirmed on official source",
                "label_hi": LIKELY_LABEL_HI if likely else "सरकारी स्रोत से पक्का",
                "unconfirmed_rules": rec.get("unconfirmed_rules", []),
                "counts_toward_total": rec["counts_toward_total"] and not already and not likely,
                "counts_toward_likely_total": rec["counts_toward_total"] and not already and likely,
                "already_receiving": already,
                "documents_hi": rec["documents_hi"],
                "where_to_apply_hi": rec["where_to_apply_hi"],
                "apply_url": rec["apply_url"],
                "official_url": rec["official_url"],
                "rules_checked": rec["rules_checked"],
                "assumptions_hi": rec["assumptions_hi"],
            })
        cards.sort(key=lambda c: (c["verification"] != "confirmed", -int(c["counts_toward_total"]),
                                  -c["annual_value_inr"]))
        total = sum(c["annual_value_inr"] for c in cards if c["counts_toward_total"])
        likely_total = sum(c["annual_value_inr"] for c in cards if c["counts_toward_likely_total"])
        brief = [{"name": c["name_hi"], "member": c["member"], "benefit": c["benefit_hi"],
                  "value": c["annual_value_inr"], "counted": c["counts_toward_total"],
                  "status": c["verification"]} for c in cards]
        summary = structured(
            usage, model=FAST_MODEL, effort="low", max_tokens=4000, schema=SUMMARY_SCHEMA,
            system="Write a warm spoken summary in very simple Hindi (Devanagari) for a non-literate family. "
                   "3-5 short sentences, max 70 words. Say the total rupees per year they are missing, name the top "
                   "2-3 schemes and for whom, and say to take the listed documents to the CSC / Jan Seva Kendra. "
                   "Schemes with status 'likely' are NOT confirmed: say they are 'शायद मिल सकती है, आय सीमा की "
                   "जाँच करवाएँ' and never add them to the confirmed total. "
                   "Write numbers as words a Hindi speaker would say (e.g. 'बारह हज़ार रुपये'). No English.",
            user=json.dumps({"confirmed_total_inr_per_year": total, "likely_extra_inr_per_year": likely_total,
                             "schemes": brief}, ensure_ascii=False),
        )["summary_hi"]
    return {"total_missing_inr_per_year": total, "likely_extra_inr_per_year": likely_total,
            "cards": cards, "summary_hi": summary}


# --------------------------------------------------------------------------
# Orchestrator (resumable)
# --------------------------------------------------------------------------
def run(hid: str, resume: bool = True) -> dict:
    """Run (or resume) the full pipeline for a household. Returns the finished run."""
    h = state.get(hid)
    last = h["runs"][-1] if h["runs"] else None
    run_ = last if (resume and last and last["status"] != "done") else state.start_run(hid)
    rid = run_["id"]
    state.update_run(hid, rid, lambda r: r.update(status="running", error=None))
    usage = Usage(run_["usage"])
    profile = h["profile"]

    with neatlogs.trace("haq_run", kind="WORKFLOW", session_id=hid, end_user_id=hid,
                        run_id=rid, resumed=bool(run_["candidates"])):
        try:
            # PLAN
            cands = run_["candidates"]
            if not cands:
                cands = plan(profile, usage, hid)
                state.update_run(hid, rid, lambda r: r.update(candidates=cands, stage="research",
                                                              usage=usage.snapshot()))
            # RESEARCH + VERIFY + RECOVER (skip candidates finished before a crash)
            done = set(state.get(hid)["runs"][-1]["research"])
            todo = [c for c in cands if c["key"] not in done]
            errors = []
            abort = threading.Event()
            # Wave 1 looks up each scheme once (filling the rules cache); wave 2 handles the other
            # members of the same scheme from that cache instead of searching the web again.
            first_of_scheme, wave1, wave2 = set(), [], []
            for c in todo:
                if c["scheme_id"] in first_of_scheme:
                    wave2.append(c)
                else:
                    first_of_scheme.add(c["scheme_id"])
                    wave1.append(c)
            for wave in (wave1, wave2):
                if wave and not abort.is_set():
                    _research_wave(wave, profile, usage, hid, rid, abort, errors)
            if errors:
                raise RuntimeError(f"{len(errors)} scheme lookups failed (resume to retry): {errors[0]}")

            # WRITE
            state.update_run(hid, rid, lambda r: r.update(stage="write"))
            research = state.get(hid)["runs"][-1]["research"]
            result = write(profile, research, usage, hid)
            return state.update_run(hid, rid, lambda r: r.update(
                result=result, stage="done", status="done", finished_at=time.time(), usage=usage.snapshot()))
        except Exception as e:
            state.update_run(hid, rid, lambda r: r.update(status="failed", error=f"{type(e).__name__}: {e}",
                                                          usage=usage.snapshot()))
            raise


def _research_wave(wave, profile, usage, hid, rid, abort, errors):
    """Research candidates in parallel; save each finished record as soon as it completes."""
    with ThreadPoolExecutor(RESEARCH_WORKERS) as pool:
        futs = {pool.submit(contextvars.copy_context().run, research_one, profile, c, usage, hid, rid,
                            abort): c
                for c in wave}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                # Not saved: the candidate stays unfinished so a resume retries it.
                errors.append(f"{c['key']}: {type(e).__name__}: {e}"[:300])
                if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                                  anthropic.BadRequestError)):
                    abort.set()  # the same error will hit every call; other loops stop at their next turn
                continue

            def _save(r, c=c, rec=rec):
                r["research"][c["key"]] = rec
                r["conflicts"].extend({**x, "scheme": c["key"]} for x in rec.get("conflicts", []))
                r["recovery_log"].extend({**x, "scheme": c["key"]} for x in rec.get("recovery_log", []))
                r.setdefault("unofficial_claims", []).extend(
                    {**x, "scheme": c["key"]} for x in rec.get("unofficial_claims", []))
                r["usage"] = usage.snapshot()
            state.update_run(hid, rid, _save)


# --------------------------------------------------------------------------
# Follow-ups for families who come back
# --------------------------------------------------------------------------
FOLLOWUP_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["answer_hi", "profile_changed", "profile"],
    "properties": {"answer_hi": {"type": "string"}, "profile_changed": {"type": "boolean"}, "profile": PROFILE_SCHEMA},
}


def followup(hid: str, question: str) -> dict:
    h = state.get(hid)
    last = next((r for r in reversed(h["runs"]) if r["status"] == "done"), None)
    result = last["result"] if last else None
    with neatlogs.trace("followup", kind="AGENT", session_id=hid, end_user_id=hid):
        out = structured(
            None, model=FAST_MODEL, effort="low", max_tokens=8000, schema=FOLLOWUP_SCHEMA,
            system="You are Haq. A family that already got scheme results is back with a question or new information. "
                   "Answer in very simple spoken Hindi (max 60 words) using ONLY their saved results and profile. "
                   "If they report a change (new baby, death, new job, land, disability...), update the profile, set "
                   "profile_changed=true and tell them you will check schemes again. Otherwise return the profile unchanged.",
            user=json.dumps({"profile": h["profile"], "results": result, "question": question}, ensure_ascii=False),
        )

    def _save(hh):
        hh["interview"]["messages"] += [{"role": "user", "text": question}, {"role": "assistant", "text": out["answer_hi"]}]
        if out["profile_changed"]:
            hh["profile"] = out["profile"]
    state.update(hid, _save)
    return out
