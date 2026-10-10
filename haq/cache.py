"""On-disk cache for official pages and verified scheme rules.

- pages/: text of official pages/PDFs, keyed by URL (default TTL 7 days). A repeat fetch costs nothing.
- rules/: the eligibility rules of a scheme as confirmed on official pages by an earlier lookup
  (default TTL 30 days). The next lookup of that scheme, for any member of any family, starts from
  these rules instead of searching the web again. Rules are scheme-level; nothing about the family
  is stored here.

Set HAQ_NO_CACHE=1 to bypass both (e.g. to demo SIMULATE_FAILURE on a cold start).
"""
import hashlib
import json
import os
import sys
import time

CACHE_DIR = os.environ.get("HAQ_CACHE_DIR", "data/cache")
PAGE_TTL_S = float(os.environ.get("HAQ_PAGE_CACHE_DAYS", "7")) * 86400
RULES_TTL_S = float(os.environ.get("HAQ_RULES_CACHE_DAYS", "30")) * 86400
DISABLED = os.environ.get("HAQ_NO_CACHE") == "1"
MAX_RULES = 12


def _path(kind: str, key: str) -> str:
    name = hashlib.sha256(key.encode()).hexdigest()[:32] if kind == "pages" else key
    return os.path.join(CACHE_DIR, kind, f"{name}.json")


def _read(path: str, ttl: float) -> dict | None:
    if DISABLED or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            entry = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return entry if time.time() - entry.get("cached_at", 0) <= ttl else None


def _write(path: str, entry: dict) -> None:
    if DISABLED:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({**entry, "cached_at": time.time()}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------- pages ----------------
def get_page(url: str) -> str | None:
    entry = _read(_path("pages", url), PAGE_TTL_S)
    return entry["text"] if entry else None


def put_page(url: str, text: str) -> None:
    _write(_path("pages", url), {"url": url, "text": text})


# ---------------- scheme rules ----------------
def get_rules(scheme_id: str) -> dict | None:
    return _read(_path("rules", scheme_id), RULES_TTL_S)


def put_rules(record: dict, source: str) -> None:
    """Store the scheme-level part of an accepted record_verified call."""
    rules, seen = [], set()
    for r in record.get("rules_checked", []):
        if r.get("rule") and r.get("official_url") and r["rule"] not in seen:
            seen.add(r["rule"])
            rules.append({"rule": r["rule"], "official_url": r["official_url"]})
    if not rules:
        return
    likely = record.get("verification") == "likely"
    existing = get_rules(record["scheme_id"])
    # One record per scheme (merging lookups piles up near-duplicate rules and inflates every prompt).
    # A fully confirmed record is never replaced by a "likely" one.
    if existing and likely and not existing.get("unconfirmed_rules"):
        return
    _write(_path("rules", record["scheme_id"]), {
        "scheme_id": record["scheme_id"],
        "scheme_name_hi": record.get("scheme_name_hi", ""),
        "official_url": record["official_url"],
        "rules": rules[:MAX_RULES],
        # an income limit stays "unconfirmed" until some lookup confirms it
        "unconfirmed_rules": record.get("unconfirmed_rules", []) if likely else [],
        "benefit_example_hi": record.get("benefit_hi", ""),
        "documents_hi": record.get("documents_hi", []),
        "where_to_apply_hi": record.get("where_to_apply_hi", ""),
        "apply_url": record.get("apply_url", ""),
        "source": source,
    })


def seed_from_state(paths: list[str]) -> int:
    """Import rules from verified records already in state files (lookups already paid for)."""
    n = 0
    for p in paths:
        with open(p, encoding="utf-8") as f:
            households = json.load(f).get("households", {})
        for hid, h in households.items():
            for run in h.get("runs", []):
                for rec in run.get("research", {}).values():
                    if rec.get("status") in ("verified", "likely") and rec.get("rules_checked"):
                        rec.setdefault("verification", "confirmed" if rec["status"] == "verified" else "likely")
                        put_rules(rec, source=f"seed:{os.path.basename(p)}:{hid}:{run['id']}")
                        n += 1
    return n


if __name__ == "__main__":
    # python -m haq.cache seed data/eval-state.json data/test-state.json
    if len(sys.argv) >= 3 and sys.argv[1] == "seed":
        print(f"imported {seed_from_state(sys.argv[2:])} verified records")
        print("schemes cached:", sorted(f[:-5] for f in os.listdir(os.path.join(CACHE_DIR, "rules"))))
    else:
        print(__doc__)
