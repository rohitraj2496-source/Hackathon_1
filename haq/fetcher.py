"""Fetch official government pages with retry, backoff and official fallbacks.

Government portals are often slow, time out, or serve expired TLS
certificates. `fetch_official` retries each URL with exponential backoff, then
walks the scheme's other official URLs. Every attempt is recorded so the
recovery path is visible in the run log and in neatlogs traces.

SIMULATE_FAILURE=1 makes the very first lookup of the process fail on purpose.
"""
import html
import re
import threading
import time

import httpx
import neatlogs

from . import catalog
from .config import SIMULATE_FAILURE

MAX_ATTEMPTS = 3
BASE_DELAY = 1.0
TIMEOUT = 12.0
MAX_CHARS = 12000
UA = "Mozilla/5.0 (HaqBot; +https://github.com/rohitraj2496-source/Hackathon_1) welfare-eligibility-research"

_sim_lock = threading.Lock()
_sim_fired = False


class LookupFailed(Exception):
    pass


def _maybe_simulate_failure(url: str) -> None:
    global _sim_fired
    if not SIMULATE_FAILURE:
        return
    with _sim_lock:
        if _sim_fired:
            return
        _sim_fired = True
    raise LookupFailed(f"SIMULATED_FAILURE: forced failure for first official lookup ({url})")


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()


def _get(url: str, verify: bool) -> str:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True, verify=verify,
                      headers={"User-Agent": UA, "Accept-Language": "hi,en;q=0.8"}) as http:
        resp = http.get(url)
        resp.raise_for_status()
        if not catalog.is_official(str(resp.url)):
            raise LookupFailed(f"redirected off official domain to {resp.url}")
        return _html_to_text(resp.text)


@neatlogs.span(kind="TOOL", tool_name="fetch_url_with_retry")
def _fetch_one(url: str, log: list) -> str:
    """Retry one URL with exponential backoff. Raises LookupFailed after MAX_ATTEMPTS."""
    verify = True
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            _maybe_simulate_failure(url)
            text = _get(url, verify)
            if len(text) < 1000:
                raise LookupFailed("page returned almost no text (JS-only page or error page)")
            log.append({"url": url, "attempt": attempt, "ok": True, "insecure_tls": not verify})
            return text
        except httpx.ConnectError as e:
            last = e
            # Several state portals serve expired certificates. The content is public
            # and read-only, so retry once without TLS verification and record it.
            if verify and "CERTIFICATE" in str(e).upper():
                verify = False
                log.append({"url": url, "attempt": attempt, "ok": False,
                            "error": "tls_certificate_invalid -> retrying without verification"})
                continue
            log.append({"url": url, "attempt": attempt, "ok": False, "error": f"connect: {e}"[:200]})
        except (httpx.HTTPError, LookupFailed) as e:
            last = e
            log.append({"url": url, "attempt": attempt, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]})
            if isinstance(e, LookupFailed) and "almost no text" in str(e):
                break  # retrying a JS-only page will not help
        if attempt < MAX_ATTEMPTS:
            time.sleep(BASE_DELAY * 2 ** (attempt - 1))
    raise LookupFailed(str(last))


@neatlogs.span(kind="TOOL", tool_name="fetch_official_page")
def fetch_official(url: str, scheme_id: str | None = None, query: str | None = None) -> dict:
    """Fetch `url`, falling back to the scheme's other official URLs.

    Returns {ok, url, text, attempts, fell_back}. Non-official URLs are refused.
    """
    if not catalog.is_official(url):
        return {"ok": False, "url": url, "text": "", "attempts": [],
                "error": "refused: not an official government domain (.gov.in / .nic.in)"}

    candidates = [url] + [u for u in catalog.all_official_urls(scheme_id or "") if u != url]
    attempts: list = []
    for i, u in enumerate(candidates):
        try:
            text = _fetch_one(u, attempts)
        except LookupFailed:
            continue
        return {"ok": True, "url": u, "fell_back": i > 0, "attempts": attempts,
                "text": _focus(text, query)}
    return {"ok": False, "url": url, "text": "", "attempts": attempts,
            "error": "all official sources failed after retries"}


def _focus(text: str, query: str | None) -> str:
    """Trim long pages, keeping the windows around query terms."""
    if len(text) <= MAX_CHARS or not query:
        return text[:MAX_CHARS]
    terms = [t for t in re.split(r"[\s,]+", query) if len(t) >= 3]
    spans = []
    for t in terms:
        for m in re.finditer(re.escape(t), text, flags=re.I):
            spans.append((max(0, m.start() - 600), m.end() + 900))
    if not spans:
        return text[:MAX_CHARS]
    spans.sort()
    merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out = " … ".join(text[s:e] for s, e in merged)
    return (text[:2000] + " … " + out)[:MAX_CHARS]
