"""Haq web server: FastAPI backend + single-page frontend.

Run:  .venv/bin/uvicorn app:app --reload
"""
import threading
from contextlib import asynccontextmanager

from haq import config  # noqa: F401  (loads .env, initialises neatlogs before anything else)

import neatlogs
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from haq import agent, catalog, intake, present, state

_running: set[str] = set()
_running_lock = threading.Lock()


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
            pass  # error is persisted on the run record
        finally:
            with _running_lock:
                _running.discard(hid)

    threading.Thread(target=_target, daemon=True).start()
    return True


@asynccontextmanager
async def lifespan(_app):
    # Resume any run that was in progress when the server last died.
    for hid, h in (state._load().get("households") or {}).items():
        if h["runs"] and h["runs"][-1]["status"] == "running":
            _run_in_background(hid)
    yield
    neatlogs.flush()
    neatlogs.shutdown()


app = FastAPI(title="Haq", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


Lang = Literal["hi", "en"]


class Create(BaseModel):
    lang: Lang = "hi"


class Intake(BaseModel):
    lang: Lang = "hi"
    text: str | None = None          # one open answer (spoken or typed)
    builder: dict | None = None      # tap-only family builder


class Answers(BaseModel):
    lang: Lang = "hi"
    answers: dict[str, str] = {}     # follow-up id -> chosen option value


class Ask(BaseModel):
    lang: Lang = "hi"
    text: str


def _get(hid: str) -> dict:
    h = state.get(hid)
    if not h:
        raise HTTPException(404, "household not found")
    return h


def _start(hid: str, lang: str) -> None:
    """Interview finished: fill remaining unknowns with safer assumptions and start the research run."""
    def _fin(h):
        h["profile"] = intake.finalize(h["profile"])
        h["interview"]["done"] = True
        h["lang"] = lang
    state.update(hid, _fin)
    _run_in_background(hid)


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/households")
def create_household(body: Create):
    hid = state.new_household()
    state.update(hid, lambda h: h.update(lang=body.lang))
    return {"id": hid, "neatlogs_session_id": hid}


@app.post("/api/households/{hid}/intake")
def submit_intake(hid: str, body: Intake):
    """The one open answer or the builder. Returns at most 2 tap follow-ups (or starts the run)."""
    _get(hid)
    trace = None
    if body.builder:
        profile = intake.profile_from_builder(body.builder)
        source = {"role": "user", "builder": body.builder}
    elif body.text and body.text.strip():
        out = intake.extract_from_text(body.text.strip(), body.lang, hid)
        profile, trace = out["profile"], out["trace"]
        source = {"role": "user", "text": body.text.strip()}
    else:
        raise HTTPException(400, "send text or builder")
    followups = intake.pick_followups(profile, body.lang)

    def _save(h):
        h["profile"], h["lang"] = profile, body.lang
        h["interview"]["messages"].append({**source, **({"trace": trace} if trace else {})})
        h["interview"]["followups"] = [f["id"] for f in followups]
    state.update(hid, _save)
    if not followups:
        _start(hid, body.lang)
    return {"followups": followups, "started": not followups,
            "members": len(profile["members"])}


@app.get("/api/households/{hid}/followups")
def get_followups(hid: str, lang: Lang = "hi"):
    """The pending follow-ups in another language (when the family switches language mid-way)."""
    h = _get(hid)
    pending = h["interview"].get("followups", [])
    return {"followups": [f for f in intake.pick_followups(h["profile"], lang) if f["id"] in pending]}


@app.post("/api/households/{hid}/answers")
def submit_answers(hid: str, body: Answers):
    """Tap answers to the follow-ups; then start the run."""
    h = _get(hid)
    allowed = set(h["interview"].get("followups", []))

    def _apply(hh):
        for qid, value in body.answers.items():
            if qid in allowed:
                intake.apply_answer(hh["profile"], qid, value)
        hh["interview"]["messages"].append({"role": "user", "answers": body.answers})
    state.update(hid, _apply)
    _start(hid, body.lang)
    return {"started": True}


@app.post("/api/households/{hid}/ask")
def ask(hid: str, body: Ask):
    """A returning family asks about their results or reports a change (which triggers a fresh search)."""
    _get(hid)
    out = agent.followup(hid, body.text, body.lang)
    if out["profile_changed"]:
        state.start_run(hid)  # new run; run(resume=True) picks it up
        _run_in_background(hid)
    return {"answer": out["answer"], "rerun": out["profile_changed"]}


@app.get("/api/households/{hid}")
def get_household(hid: str, lang: Lang = "hi"):
    h = _get(hid)
    run = h["runs"][-1] if h["runs"] else None
    progress, result = None, None
    if run:
        progress = {
            "id": run["id"], "status": run["status"], "stage": run["stage"], "error": run["error"],
            "total": len(run["candidates"]), "done": len(run["research"]),
            "events": run.get("events", []),
            "recoveries": len(run["recovery_log"]), "conflicts": len(run["conflicts"]),
            "cost_usd": run["usage"]["cost_usd"], "traces": run.get("traces", []),
        }
        if run["status"] == "done" and run["result"]:
            result = present.localized(hid, run["id"], run["result"], lang)
    return {"id": hid, "neatlogs_session_id": hid, "lang": h.get("lang", "hi"),
            "interview_done": h["interview"]["done"], "run": progress, "result": result,
            "running": hid in _running,
            "schemes": {s["id"]: {"name": catalog.display_name(s["id"], lang) or s["name_en"], "emoji": s["emoji"]}
                        for s in catalog.SCHEMES}}


@app.post("/api/households/{hid}/run")
def start_or_resume(hid: str):
    _get(hid)
    return {"started": _run_in_background(hid)}
