"""Environment, tracing and the shared Anthropic client.

Import this module before anything that talks to Claude: it loads .env,
initialises neatlogs, and wraps the Anthropic client so every LLM call
becomes an LLM span.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # must run before neatlogs.init() so NEATLOGS_API_KEY is visible

import neatlogs  # noqa: E402

neatlogs.init(
    api_key=os.environ.get("NEATLOGS_API_KEY"),
    workflow_name=os.environ.get("HAQ_WORKFLOW_NAME", "haq"),
    tags=["haq", "schemes", "uttar-pradesh"],
)

from anthropic import Anthropic  # noqa: E402

MODEL = os.environ.get("HAQ_MODEL", "claude-sonnet-5-5")
EFFORT = os.environ.get("HAQ_EFFORT", "medium")
SIMULATE_FAILURE = os.environ.get("SIMULATE_FAILURE") == "1"
STATE_FILE = os.environ.get("HAQ_STATE_FILE", "data/state.json")

# Server-side refusal fallback: if a request is declined, the API re-runs it on
# a fallback model inside the same call. Passed through extra_* so the neatlogs
# wrapper still instruments the plain messages.create path.
FALLBACK_HEADERS = {"anthropic-beta": "server-side-fallback-2026-07-01"}
FALLBACK_BODY = {"fallbacks": "default"}

# Bounded so one stalled request cannot hold a research loop for long (the SDK default is 10 min x retries).
client = neatlogs.wrap(Anthropic(max_retries=3, timeout=180.0))

# USD per million tokens (cache write = 1.25x input). Web search is billed per request.
PRICES = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}
WEB_SEARCH_USD = 10.0 / 1000
