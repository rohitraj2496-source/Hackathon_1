"""Environment, tracing and the shared Anthropic client.

Import this module before anything that talks to Claude: it loads .env,
initialises neatlogs, and wraps the Anthropic client so every LLM call
becomes an LLM span.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # must run before neatlogs.init() so NEATLOGS_API_KEY is visible

import neatlogs  # noqa: E402

WORKFLOW_NAME = os.environ.get("HAQ_WORKFLOW_NAME", "haq")

neatlogs.init(
    api_key=os.environ.get("NEATLOGS_API_KEY"),
    workflow_name=WORKFLOW_NAME,
    tags=["haq", "schemes", "uttar-pradesh"],
    # The web server handles SIGTERM itself (fast flush in app.py's shutdown). neatlogs' own handler would
    # run a 30 s shutdown and then exit Python while research threads are mid-request.
    register_shutdown_handlers=os.environ.get("HAQ_SERVER") != "1",
)

from anthropic import Anthropic  # noqa: E402


def trace_ref(span, name: str, session_id: str | None = None, **extra) -> dict:
    """IDs to find a run in the neatlogs dashboard: OpenTelemetry trace/span id (hex), span name,
    workflow and session. Stored with every run so results link straight to their traces."""
    ctx = span.get_span_context()
    return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x"),
            "name": name, "workflow": WORKFLOW_NAME, "session_id": session_id, **extra}

# Sonnet only where judgment matters (eligibility verification); Haiku for interview, planning, formatting.
VERIFY_MODEL = os.environ.get("HAQ_VERIFY_MODEL", os.environ.get("HAQ_MODEL", "claude-sonnet-5-5"))
FAST_MODEL = os.environ.get("HAQ_FAST_MODEL", "claude-haiku-5-5")
MODEL = VERIFY_MODEL  # back-compat name
EFFORT = os.environ.get("HAQ_EFFORT", "medium")
SIMULATE_FAILURE = os.environ.get("SIMULATE_FAILURE") == "1"
STATE_FILE = os.environ.get("HAQ_STATE_FILE", "data/state.json")

# Server-side refusal fallback: if a request is declined, the API re-runs it on
# a fallback model inside the same call. Passed through extra_* so the neatlogs
# wrapper still instruments the plain messages.create path.
FALLBACK_HEADERS = {"anthropic-beta": "server-side-fallback-2026-07-01"}
FALLBACK_BODY = {"fallbacks": "default"}
# Haiku has no server-side refusal fallback; only send the parameter to models that accept it.
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1")

# Bounded so one stalled request cannot hold a research loop for long (the SDK default is 10 min x retries).
client = neatlogs.wrap(Anthropic(max_retries=3, timeout=180.0))

# USD per million tokens (cache write = 1.25x input). Web search is billed per request.
PRICES = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    # Haiku 5.5 list price for prompts <= 100K tokens. Cache rates assumed at the usual 0.1x / 1.25x of input.
    "claude-haiku-5-5": {"in": 0.10, "out": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}
WEB_SEARCH_USD = 10.0 / 1000
