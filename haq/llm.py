"""Thin helpers around the traced Anthropic client: one call site, cost accounting."""
import json
import os
import threading
import time

from anthropic.types import Message

from .config import (EFFORT, FALLBACK_BODY, FALLBACK_HEADERS, FALLBACK_MODELS, MODEL, PRICES,
                     WEB_SEARCH_USD, client)


class BudgetExceeded(RuntimeError):
    """The process-wide spend cap (HAQ_BUDGET_USD) has been reached; no further model calls are made."""


# Process-wide spend, including calls not tied to a run (intake extraction, follow-ups, translation).
_spend_lock = threading.Lock()
_spent_usd = 0.0
BUDGET_USD = float(os.environ["HAQ_BUDGET_USD"]) if os.environ.get("HAQ_BUDGET_USD") else None

# Daily cap (India date), persisted so a restart does not reset it. Default $1.00/day on a public server.
DAILY_BUDGET_USD = (float(os.environ["HAQ_DAILY_BUDGET_USD"]) if os.environ.get("HAQ_DAILY_BUDGET_USD")
                    else 1.00 if os.environ.get("HAQ_PUBLIC") == "1" else None)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5.5 * 3600))     # IST


def _spend_file() -> str:
    from .config import STATE_FILE
    return os.path.join(os.path.dirname(STATE_FILE) or ".", "spend-by-day.json")


def _daily_load() -> dict:
    try:
        with open(_spend_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def daily_spent_usd() -> float:
    with _spend_lock:
        return round(_daily_load().get(_today(), 0.0), 6)


def daily_remaining_usd() -> float | None:
    return None if DAILY_BUDGET_USD is None else max(0.0, DAILY_BUDGET_USD - daily_spent_usd())


def spent_usd() -> float:
    with _spend_lock:
        return round(_spent_usd, 6)


def _record_spend(cost: float) -> None:
    global _spent_usd
    with _spend_lock:
        _spent_usd += cost
        if DAILY_BUDGET_USD is not None:
            data = _daily_load()
            data[_today()] = round(data.get(_today(), 0.0) + cost, 6)
            path = _spend_file()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)


def message_cost(msg: Message) -> tuple[dict, float]:
    u = msg.usage
    price = PRICES.get(msg.model) or PRICES.get(MODEL) or PRICES["claude-opus-5-5"]
    searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
    vals = {
        "input_tokens": u.input_tokens or 0,
        "output_tokens": u.output_tokens or 0,
        "cache_read_input_tokens": u.cache_read_input_tokens or 0,
        "cache_creation_input_tokens": u.cache_creation_input_tokens or 0,
        "web_search_requests": searches,
    }
    cost = (vals["input_tokens"] * price["in"] + vals["output_tokens"] * price["out"]
            + vals["cache_read_input_tokens"] * price["cache_read"]
            + vals["cache_creation_input_tokens"] * price["cache_write"]) / 1e6
    return vals, cost + searches * WEB_SEARCH_USD


class Usage:
    """Thread-safe token/cost accumulator for one run."""

    FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
              "cache_creation_input_tokens", "web_search_requests")

    def __init__(self, initial: dict | None = None):
        self._lock = threading.Lock()
        self.totals = {k: 0 for k in self.FIELDS}
        self.totals["cost_usd"] = 0.0
        self.by_model: dict[str, dict] = {}
        if initial:
            self.totals.update({k: initial.get(k, v) for k, v in self.totals.items()})
            self.by_model = {m: dict(v) for m, v in (initial.get("by_model") or {}).items()}

    def add(self, msg: Message) -> None:
        vals, cost = message_cost(msg)
        with self._lock:
            for k, v in vals.items():
                self.totals[k] += v
            self.totals["cost_usd"] = round(self.totals["cost_usd"] + cost, 6)
            m = self.by_model.setdefault(msg.model, {**{k: 0 for k in self.FIELDS}, "calls": 0, "cost_usd": 0.0})
            for k, v in vals.items():
                m[k] += v
            m["calls"] += 1
            m["cost_usd"] = round(m["cost_usd"] + cost, 6)

    def snapshot(self) -> dict:
        with self._lock:
            return {**self.totals, "by_model": {m: dict(v) for m, v in self.by_model.items()}}


CACHE = {"type": "ephemeral"}


def system_blocks(*parts: str) -> list[dict]:
    """System prompt as text blocks, each ending in a cache breakpoint.

    Tools render before system, so the first breakpoint caches tools + the shared instructions; a
    later part (e.g. one scheme's cached official rules) gets its own read point shared by every
    request about that scheme. Byte-stable parts only: anything per-family goes in messages."""
    return [{"type": "text", "text": p, "cache_control": CACHE} for p in parts if p]


def create(usage: Usage | None, *, model: str = MODEL, effort: str | None = None, max_tokens: int = 16000,
           system: str | list[dict], loop: bool = False, **kwargs) -> Message:
    """messages.create with Haq defaults: adaptive thinking, effort, prompt caching, refusal fallback.

    Prompt caching: explicit breakpoints on the system blocks always. loop=True also turns on
    top-level automatic caching so a multi-turn tool loop re-reads its growing history from cache;
    one-shot calls leave it off (it would only pay the write premium on a unique tail)."""
    if BUDGET_USD is not None and spent_usd() >= BUDGET_USD:
        raise BudgetExceeded(f"spend cap reached: ${spent_usd():.4f} of ${BUDGET_USD:.2f}")
    if DAILY_BUDGET_USD is not None and daily_spent_usd() >= DAILY_BUDGET_USD:
        raise BudgetExceeded(f"daily spend cap reached (${DAILY_BUDGET_USD:.2f})")
    fallback = model in FALLBACK_MODELS
    if loop:
        kwargs["cache_control"] = CACHE
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks(system) if isinstance(system, str) else system,
        thinking={"type": "adaptive"},
        output_config={**kwargs.pop("output_config", {}), "effort": effort or EFFORT},
        extra_headers=FALLBACK_HEADERS if fallback else None,
        extra_body=FALLBACK_BODY if fallback else None,
        **kwargs,
    )
    _record_spend(message_cost(msg)[1])
    if usage is not None:
        usage.add(msg)
    return msg


def structured(usage: Usage | None, *, system: str, user: str, schema: dict, model: str = MODEL,
               effort: str | None = None, max_tokens: int = 16000) -> dict:
    """One call that must return JSON matching `schema`."""
    msg = create(usage, model=model, effort=effort, max_tokens=max_tokens, system=system,
                 messages=[{"role": "user", "content": user}],
                 output_config={"format": {"type": "json_schema", "schema": schema}})
    if msg.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)
