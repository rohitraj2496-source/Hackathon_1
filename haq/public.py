"""Public deployment controls: DEMO replays, LIVE passcode gate, per-IP rate limits, concurrency.

Modes
- DEMO (default for visitors): replays real recorded runs (demo/recorded_runs.json) through the same UI and
  step-by-step animation. No model calls, no storage: a demo session id encodes the recording and its start
  time, and progress is computed from the clock.
- LIVE: real runs. When HAQ_PUBLIC=1 or HAQ_LIVE_PASSCODE is set, live needs the passcode (exchanged for a
  signed 12-hour token). With HAQ_PUBLIC=1 and no passcode, live is off. The daily spend cap
  (HAQ_DAILY_BUDGET_USD) is enforced on every model call in haq/llm.py.
"""
import collections
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from . import catalog, present
from .config import STATE_FILE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.environ.get("HAQ_PUBLIC") == "1"
PASSCODE = os.environ.get("HAQ_LIVE_PASSCODE", "")
GATED = PUBLIC or bool(PASSCODE)
HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
TOKEN_TTL_S = 12 * 3600
LIVE_RUNS_PER_HOUR = int(os.environ.get("HAQ_LIVE_RUNS_PER_HOUR", "2"))
MODEL_CALLS_PER_HOUR = int(os.environ.get("HAQ_MODEL_CALLS_PER_HOUR", "12"))   # typed-answer understanding, follow-up questions
UNLOCKS_PER_15MIN = 5
MAX_CONCURRENT_RUNS = int(os.environ.get("HAQ_MAX_CONCURRENT_RUNS", "2"))
RUN_RESERVE_USD = float(os.environ.get("HAQ_RUN_RESERVE_USD", "0.30"))           # budget a run needs to start


# ------------------------------------------------------------------ live access token
def _secret() -> bytes:
    """Signing key, created once per server and kept next to the state file (never sent anywhere)."""
    path = os.path.join(os.path.dirname(STATE_FILE) or ".", "live-secret.key")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(path, 0o600)
    with open(path, "rb") as f:
        return f.read()


_SECRET = None


def _sig(payload: str) -> str:
    global _SECRET
    _SECRET = _SECRET or _secret()
    return hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]


def passcode_ok(given: str) -> bool:
    return bool(PASSCODE) and hmac.compare_digest(given.strip().encode(), PASSCODE.encode())


def make_token() -> str:
    exp = str(int(time.time()) + TOKEN_TTL_S)
    return f"{exp}.{_sig('live:' + exp)}"


def token_ok(token: str | None) -> bool:
    if not GATED:
        return True                     # local / private use: no passcode configured
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, _sig("live:" + exp))


def live_status() -> dict:
    """Whether a visitor could run live right now, and why not (no secrets, no amounts)."""
    from . import llm
    if not HAS_API_KEY or (GATED and not PASSCODE):
        return {"available": False, "needs_passcode": GATED, "reason": "disabled"}
    if llm.daily_remaining_usd() is not None and llm.daily_remaining_usd() < RUN_RESERVE_USD:
        return {"available": False, "needs_passcode": GATED, "reason": "budget"}
    return {"available": True, "needs_passcode": GATED, "reason": None}


# ------------------------------------------------------------------ rate limits (single server process)
class Window:
    """At most `limit` events per `seconds` per key (sliding window, in memory)."""

    def __init__(self, limit: int, seconds: int):
        self.limit, self.seconds = limit, seconds
        self.hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()

    def allow(self, key: str, consume: bool = True) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - self.seconds:
                q.popleft()
            if len(q) >= self.limit:
                return False
            if consume:
                q.append(now)
            return True


live_runs = Window(LIVE_RUNS_PER_HOUR, 3600)
model_calls = Window(MODEL_CALLS_PER_HOUR, 3600)
unlocks = Window(UNLOCKS_PER_15MIN, 900)


# ------------------------------------------------------------------ demo replays
_DEMO = None


def recordings() -> list[dict]:
    global _DEMO
    if _DEMO is None:
        path = os.path.join(ROOT, "demo", "recorded_runs.json")
        _DEMO = json.load(open(path, encoding="utf-8"))["recordings"] if os.path.exists(path) else []
    return _DEMO


def demo_catalog() -> list[dict]:
    """What the visitor sees in the demo list (no profiles, no internals)."""
    return [{"id": r["id"], "emoji": r["emoji"], "title": r["title"], "langs": r["langs"], "source": r["source"],
             "recorded_seconds": r["recorded_seconds"], "cost_inr": r["cost_inr"]} for r in recordings()]


def new_demo_id(rid: str) -> str | None:
    if not any(r["id"] == rid for r in recordings()):
        return None
    return f"demo-{rid}-{int(time.time() * 1000)}"


def demo_view(demo_id: str, lang: str) -> dict | None:
    """The same shape as a live GET /api/households/{id}, replayed from the clock."""
    try:
        _, rest = demo_id.split("-", 1)
        rid, start_ms = rest.rsplit("-", 1)
        started = int(start_ms) / 1000
    except ValueError:
        return None
    rec = next((r for r in recordings() if r["id"] == rid), None)
    if rec is None:
        return None
    elapsed = max(0.0, time.time() - started)
    events = [{k: v for k, v in e.items() if k != "at"} for e in rec["events"] if e["at"] <= elapsed]
    done = elapsed >= rec["events"][-1]["at"] + 0.8
    result = None
    if done:
        tr = None
        en = (rec["result"].get("i18n") or {}).get("en")
        view_lang = lang if (lang == "hi" or en) else "hi"          # never translate here: no model calls in demo
        if view_lang == "en":
            tr = {c["i"]: c for c in en["cards"]}
            tr["summary"] = en["summary"]
        result = present._view(rec["result"], view_lang, tr, rec["profile"])
        result["lang_note"] = None if view_lang == lang else "recorded_in_hindi_only"
    return {"id": demo_id, "lang": lang, "interview_done": True, "running": not done,
            "demo": {"id": rid, "title": rec["title"], "source": rec["source"],
                     "recorded_seconds": rec["recorded_seconds"], "cost_inr": rec["cost_inr"]},
            "run": {"status": "done" if done else "running", "stage": "done" if done else "research",
                    "events": events, "error_code": None},
            "result": result,
            "schemes": {s["id"]: {"name": catalog.display_name(s["id"], lang) or s["name_en"], "emoji": s["emoji"]}
                        for s in catalog.SCHEMES}}
