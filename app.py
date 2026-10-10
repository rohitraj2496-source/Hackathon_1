"""Haq web server: FastAPI backend + single-page frontend.

Run:  .venv/bin/uvicorn app:app --reload
"""
import threading
from contextlib import asynccontextmanager

from haq import config  # noqa: F401  (loads .env, initialises neatlogs before anything else)

import neatlogs
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from haq import agent, state

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


class Say(BaseModel):
    text: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/households")
def create_household():
    hid = state.new_household()
    state.update(hid, lambda h: h["interview"]["messages"].append({"role": "assistant", "text": agent.GREETING_HI}))
    return {"id": hid, "question_hi": agent.GREETING_HI}


@app.get("/api/households/{hid}")
def get_household(hid: str):
    h = state.get(hid)
    if not h:
        raise HTTPException(404, "household not found")
    run = h["runs"][-1] if h["runs"] else None
    progress = None
    if run:
        progress = {
            "id": run["id"], "status": run["status"], "stage": run["stage"], "error": run["error"],
            "total": len(run["candidates"]), "done": len(run["research"]),
            "verified": sum(1 for r in run["research"].values() if r.get("status") == "verified"),
            "likely": sum(1 for r in run["research"].values() if r.get("status") == "likely"),
            "recoveries": len(run["recovery_log"]), "conflicts": len(run["conflicts"]),
            "cost_usd": run["usage"]["cost_usd"],
        }
    return {"id": hid, "profile": h["profile"], "interview": h["interview"], "run": progress,
            "result": run["result"] if run else None, "running": hid in _running}


@app.post("/api/households/{hid}/answer")
def answer(hid: str, body: Say):
    h = state.get(hid)
    if not h:
        raise HTTPException(404, "household not found")
    if h["interview"]["done"]:
        out = agent.followup(hid, body.text)
        if out["profile_changed"]:
            state.start_run(hid)  # new run; run(resume=True) picks it up
            _run_in_background(hid)
        return {"question_hi": out["answer_hi"], "done": True, "rerun": out["profile_changed"]}
    out = agent.interview_turn(hid, body.text)
    if out["done"]:
        _run_in_background(hid)
    return {"question_hi": out["next_question_hi"], "done": out["done"], "profile": out["profile"]}


@app.post("/api/households/{hid}/run")
def start_or_resume(hid: str):
    if not state.get(hid):
        raise HTTPException(404, "household not found")
    return {"started": _run_in_background(hid)}
