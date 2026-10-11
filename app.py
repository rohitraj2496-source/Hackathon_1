"""Haq web server: FastAPI backend + single-page frontend.

Run:  .venv/bin/uvicorn app:app --reload
Public deployment: see deploy/README.md (HAQ_PUBLIC=1, passcode-gated LIVE mode, DEMO by default).
"""
import json
import logging
import threading
import time
from contextlib import asynccontextmanager

from haq import config  # noqa: F401  (loads .env, initialises neatlogs before anything else)

import os
from typing import Literal

import neatlogs
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from haq import agent, catalog, intake, llm, present, public, state

log = logging.getLogger("haq")
_running: set[str] = set()
_running_lock = threading.Lock()
RESUME_WITHIN_S = 2 * 3600       # after a restart, only resume runs that were started recently


def _run_in_background(hid: str) -> bool:
    """Start (or resume) a run unless one is already in flight for this household."""
    with _running_lock:
        if hid in _running:
            return False
        _running.add(hid)

    def _target():
        try:
            agent.run(hid, resume=True)
        except Exception:
            log.exception("run %s failed", hid)   # details stay in the server log and the run record
        finally:
            with _running_lock:
                _running.discard(hid)

    threading.Thread(target=_target, daemon=True).start()
    return True


@asynccontextmanager
async def lifespan(_app):
    # Resume runs that were in progress when the server last stopped (recent ones only; spend caps still apply).
    for hid, h in (state._load().get("households") or {}).items():
        run = h["runs"][-1] if h["runs"] else None
        if run and run["status"] == "running" and time.time() - run.get("started_at", 0) < RESUME_WITHIN_S:
            _run_in_background(hid)
    yield
    neatlogs.flush()
    neatlogs.shutdown()


app = FastAPI(title="Haq", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.exception_handler(Exception)
async def _no_server_details(request: Request, exc: Exception):
    """Never send stack traces or internal error text to the browser."""
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"error": "server"}, status_code=500)


Lang = Literal["hi", "en"]
MAX_TEXT = 3000


class Create(BaseModel):
    lang: Lang = "hi"


class Intake(BaseModel):
    lang: Lang = "hi"
    text: str | None = Field(None, max_length=20000)   # one open answer (spoken or typed)
    builder: dict | None = None                        # tap-only family builder


class Answers(BaseModel):
    lang: Lang = "hi"
    answers: dict[str, str] = {}                       # follow-up id -> chosen option value


class Ask(BaseModel):
    lang: Lang = "hi"
    text: str = Field(..., max_length=2000)


class Unlock(BaseModel):
    passcode: str = Field(..., max_length=200)


def deny(status: int, code: str) -> JSONResponse:
    """A refusal the UI turns into a friendly message: budget | rate_limit | busy | passcode | live_off."""
    return JSONResponse({"error": code}, status_code=status)


def _ip(request: Request) -> str:
    # uvicorn runs with --proxy-headers behind Caddy, so this is the visitor's address
    return request.client.host if request.client else "unknown"


def _live_gate(request: Request) -> JSONResponse | None:
    status = public.live_status()
    if status["reason"] == "disabled":
        return deny(403, "live_off")
    if not public.token_ok(request.headers.get("x-haq-live")):
        return deny(401, "passcode")
    if status["reason"] == "budget":
        return deny(402, "budget")
    return None


def _get(hid: str) -> dict:
    h = state.get(hid) if not hid.startswith("demo-") else None
    if not h:
        raise HTTPException(404, "not found")
    return h


def _start(hid: str, lang: str, request: Request) -> JSONResponse | None:
    """Interview finished: check budget / rate limit / capacity, fill remaining unknowns, start the run."""
    remaining = llm.daily_remaining_usd()
    if remaining is not None and remaining < public.RUN_RESERVE_USD:
        return deny(402, "budget")
    ip = _ip(request)
    if not public.live_runs.allow(ip, consume=False):     # this visitor's hourly allowance first
        return deny(429, "rate_limit")
    with _running_lock:
        if len(_running) >= public.MAX_CONCURRENT_RUNS:     # then server capacity (does not use up an allowance)
            return deny(503, "busy")
    public.live_runs.allow(ip)

    def _fin(h):
        h["profile"] = intake.finalize(h["profile"])
        h["interview"]["done"] = True
        h["lang"] = lang
    state.update(hid, _fin)
    _run_in_background(hid)
    return None


# ------------------------------------------------------------------ pages, health, config
@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    """Liveness for monitoring: no model or web calls."""
    return {"status": "ok"}


@app.get("/api/config")
def get_config():
    return {"live": public.live_status(), "demo": public.demo_catalog()}


@app.post("/api/live/unlock")
def unlock(body: Unlock, request: Request):
    if not public.unlocks.allow(_ip(request)):
        return deny(429, "rate_limit")
    if not public.passcode_ok(body.passcode):
        return deny(401, "passcode")
    return {"token": public.make_token(), "expires_in": public.TOKEN_TTL_S}


@app.post("/api/demo/{rid}")
def start_demo(rid: str):
    demo_id = public.new_demo_id(rid)
    if not demo_id:
        raise HTTPException(404, "not found")
    return {"id": demo_id}


# ------------------------------------------------------------------ live households
@app.post("/api/households")
def create_household(body: Create, request: Request):
    if (refusal := _live_gate(request)):
        return refusal
    hid = state.new_household()
    state.update(hid, lambda h: h.update(lang=body.lang))
    return {"id": hid}


@app.post("/api/households/{hid}/intake")
def submit_intake(hid: str, body: Intake, request: Request):
    """The one open answer or the builder. Returns at most 2 tap follow-ups (or starts the run)."""
    if (refusal := _live_gate(request)):
        return refusal
    _get(hid)
    trace = None
    if body.builder:
        profile = intake.profile_from_builder(body.builder)
        source = {"role": "user", "builder": body.builder}
    elif body.text and body.text.strip():
        if not public.model_calls.allow(_ip(request)):
            return deny(429, "rate_limit")
        text = body.text.strip()[:MAX_TEXT]          # one description; anything longer adds cost, not information
        try:
            out = intake.extract_from_text(text, body.lang, hid)
        except llm.BudgetExceeded:
            return deny(402, "budget")
        profile, trace = out["profile"], out["trace"]
        source = {"role": "user", "text": text}
    else:
        raise HTTPException(400, "send text or builder")
    if not profile["members"]:
        # Nothing about a family could be understood (gibberish, emoji, only numbers, empty builder):
        # ask again instead of searching schemes for nobody.
        return {"followups": [], "started": False, "members": 0, "need_more": True}
    followups = intake.pick_followups(profile, body.lang)

    def _save(h):
        h["profile"], h["lang"] = profile, body.lang
        h["interview"]["messages"].append({**source, **({"trace": trace} if trace else {})})
        h["interview"]["followups"] = [f["id"] for f in followups]
    state.update(hid, _save)
    if not followups and (refusal := _start(hid, body.lang, request)):
        return refusal
    return {"followups": followups, "started": not followups,
            "members": len(profile["members"])}


@app.get("/api/households/{hid}/followups")
def get_followups(hid: str, lang: Lang = "hi"):
    """The pending follow-ups in another language (when the family switches language mid-way)."""
    h = _get(hid)
    pending = h["interview"].get("followups", [])
    return {"followups": [f for f in intake.pick_followups(h["profile"], lang) if f["id"] in pending]}


@app.post("/api/households/{hid}/answers")
def submit_answers(hid: str, body: Answers, request: Request):
    """Tap answers to the follow-ups; then start the run."""
    if (refusal := _live_gate(request)):
        return refusal
    h = _get(hid)
    allowed = set(h["interview"].get("followups", []))

    def _apply(hh):
        for qid, value in body.answers.items():
            if qid in allowed:
                intake.apply_answer(hh["profile"], qid, value)
        hh["interview"]["messages"].append({"role": "user", "answers": body.answers})
    state.update(hid, _apply)
    if (refusal := _start(hid, body.lang, request)):
        return refusal
    return {"started": True}


@app.post("/api/households/{hid}/ask")
def ask(hid: str, body: Ask, request: Request):
    """A returning family asks about their results or reports a change (which triggers a fresh search)."""
    if (refusal := _live_gate(request)):
        return refusal
    _get(hid)
    if not public.model_calls.allow(_ip(request)):
        return deny(429, "rate_limit")
    try:
        out = agent.followup(hid, body.text, body.lang)
    except llm.BudgetExceeded:
        return deny(402, "budget")
    if out["profile_changed"]:
        # agent.run starts a fresh run because the last one is done
        if (refusal := _start(hid, body.lang, request)):
            return {"answer": out["answer"], "rerun": False, "error": json.loads(refusal.body)["error"]}
    return {"answer": out["answer"], "rerun": out["profile_changed"]}


@app.get("/api/households/{hid}")
def get_household(hid: str, lang: Lang = "hi"):
    if hid.startswith("demo-"):
        view = public.demo_view(hid, lang)
        if not view:
            raise HTTPException(404, "not found")
        return view
    h = _get(hid)
    run = h["runs"][-1] if h["runs"] else None
    progress, result = None, None
    if run:
        err = run.get("error") or ""
        progress = {   # no traces, costs or error text: the run record keeps those
            "status": run["status"], "stage": run["stage"], "events": run.get("events", []),
            "error_code": None if not err else ("budget" if "BudgetExceeded" in err else "failed"),
        }
        if run["status"] == "done" and run["result"]:
            try:
                result = present.localized(hid, run["id"], run["result"], lang)
                result["lang_note"] = None
            except Exception:                    # e.g. English translation refused by the daily cap
                result = present.localized(hid, run["id"], run["result"], "hi")
                result["lang_note"] = "recorded_in_hindi_only"
    return {"id": hid, "lang": h.get("lang", "hi"), "demo": None,
            "interview_done": h["interview"]["done"], "run": progress, "result": result,
            "running": hid in _running,
            "schemes": {s["id"]: {"name": catalog.display_name(s["id"], lang) or s["name_en"], "emoji": s["emoji"]}
                        for s in catalog.SCHEMES}}


@app.post("/api/households/{hid}/run")
def start_or_resume(hid: str, request: Request):
    if (refusal := _live_gate(request)):
        return refusal
    _get(hid)
    remaining = llm.daily_remaining_usd()
    if remaining is not None and remaining < public.RUN_RESERVE_USD:
        return deny(402, "budget")
    return {"started": _run_in_background(hid)}


if os.environ.get("HAQ_DEBUG") == "1":     # local test harnesses only; never on the public server
    @app.get("/api/debug/spend")
    def debug_spend():
        return {"spent_usd": llm.spent_usd(), "budget_usd": llm.BUDGET_USD,
                "daily_spent_usd": llm.daily_spent_usd(), "daily_budget_usd": llm.DAILY_BUDGET_USD}
