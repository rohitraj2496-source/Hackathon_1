"""Thin helpers around the traced Anthropic client: one call site, cost accounting."""
import json
import threading

from anthropic.types import Message

from .config import (EFFORT, FALLBACK_BODY, FALLBACK_HEADERS, MODEL, PRICES,
                     WEB_SEARCH_USD, client)


class Usage:
    """Thread-safe token/cost accumulator for one run."""

    FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
              "cache_creation_input_tokens", "web_search_requests")

    def __init__(self, initial: dict | None = None):
        self._lock = threading.Lock()
        self.totals = {k: 0 for k in self.FIELDS}
        self.totals["cost_usd"] = 0.0
        if initial:
            self.totals.update({k: initial.get(k, v) for k, v in self.totals.items()})

    def add(self, msg: Message) -> None:
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
        cost += searches * WEB_SEARCH_USD
        with self._lock:
            for k, v in vals.items():
                self.totals[k] += v
            self.totals["cost_usd"] = round(self.totals["cost_usd"] + cost, 6)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.totals)


def create(usage: Usage | None, *, effort: str | None = None, max_tokens: int = 16000, **kwargs) -> Message:
    """messages.create with Haq defaults: adaptive thinking, effort, caching, refusal fallback."""
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={**kwargs.pop("output_config", {}), "effort": effort or EFFORT},
        cache_control={"type": "ephemeral"},
        extra_headers=FALLBACK_HEADERS,
        extra_body=FALLBACK_BODY,
        **kwargs,
    )
    if usage is not None:
        usage.add(msg)
    return msg


def structured(usage: Usage | None, *, system: str, user: str, schema: dict,
               effort: str | None = None, max_tokens: int = 16000) -> dict:
    """One call that must return JSON matching `schema`."""
    msg = create(usage, effort=effort, max_tokens=max_tokens, system=system,
                 messages=[{"role": "user", "content": user}],
                 output_config={"format": {"type": "json_schema", "schema": schema}})
    if msg.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)
