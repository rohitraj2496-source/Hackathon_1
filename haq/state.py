"""JSON-file persistence for household profiles, interviews and run progress.

One file holds every household. Writes are atomic (temp file + rename) and
guarded by a process-wide lock, so a crash mid-run leaves the last good state
on disk and `resume` can pick up from the last completed step.
"""
import copy
import json
import os
import threading
import time
import uuid

from .config import STATE_FILE

_lock = threading.RLock()


def _load() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"households": {}}
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    tmp = f"{STATE_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def new_household(profile: dict | None = None, source: str = "web") -> str:
    hid = uuid.uuid4().hex[:10]
    with _lock:
        data = _load()
        data["households"][hid] = {
            "id": hid,
            "source": source,
            "created_at": time.time(),
            "updated_at": time.time(),
            "profile": profile or {},
            "interview": {"messages": [], "done": bool(profile)},
            "runs": [],
        }
        _save(data)
    return hid


def get(hid: str) -> dict | None:
    with _lock:
        h = _load()["households"].get(hid)
        return copy.deepcopy(h) if h else None


def update(hid: str, fn) -> dict:
    """Apply fn(household) under the lock and persist. Returns a copy."""
    with _lock:
        data = _load()
        h = data["households"][hid]
        fn(h)
        h["updated_at"] = time.time()
        _save(data)
        return copy.deepcopy(h)


def latest_run(hid: str) -> dict | None:
    h = get(hid)
    return h["runs"][-1] if h and h["runs"] else None


def start_run(hid: str) -> dict:
    run = {
        "id": uuid.uuid4().hex[:8],
        "status": "running",      # running | done | failed
        "stage": "plan",          # plan | research | write | done
        "started_at": time.time(),
        "finished_at": None,
        "candidates": [],          # from PLAN
        "research": {},            # scheme_key -> verified/dropped record
        "conflicts": [],           # official vs non-government disagreements (official trusted)
        "unofficial_claims": [],   # claims seen only on non-government pages (never used as rules)
        "recovery_log": [],
        "result": None,            # from WRITE
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0, "web_search_requests": 0, "cost_usd": 0.0},
        "error": None,
        "traces": [],              # neatlogs trace refs, one per attempt (resume adds one)
        "events": [],              # live step log for the UI checklist
    }
    update(hid, lambda h: h["runs"].append(run))
    return run


def add_event(hid: str, run_id: str, type_: str, **data) -> None:
    """Append one step to the run's live log (shown as a checklist while the agent works)."""
    update_run(hid, run_id, lambda r: r.setdefault("events", []).append({"t": time.time(), "type": type_, **data}))


def update_run(hid: str, run_id: str, fn) -> dict:
    def _apply(h):
        for r in h["runs"]:
            if r["id"] == run_id:
                fn(r)
                return
        raise KeyError(run_id)
    h = update(hid, _apply)
    return next(r for r in h["runs"] if r["id"] == run_id)
