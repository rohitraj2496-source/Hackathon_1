"""Run Haq on the 20 test households and score it against evals/families.json.

Usage:
  .venv/bin/python run_evals.py                 # all households, 3 at a time
  .venv/bin/python run_evals.py --only h01,h09  # a subset
  .venv/bin/python run_evals.py --workers 5

Scoring (household x scheme level):
  - expected item satisfied if Haq verified its scheme_id (or any id in its any_of)  -> TP, else FN
  - predicted scheme not expected and not in acceptable_extra                       -> FP
  precision = matched predictions / (matched + FP), recall = TP / (TP + FN),
  accuracy  = TP / (TP + FP + FN)  (Jaccard over all households)
"""
import argparse
import contextvars
import glob
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("HAQ_STATE_FILE", "data/eval-state.json")
os.environ.setdefault("HAQ_WORKFLOW_NAME", "haq-evals")

from haq import config  # noqa: E402,F401  (loads .env + neatlogs first)

import neatlogs  # noqa: E402

from haq import agent, catalog, state  # noqa: E402

FAMILIES = "evals/families.json"


def score(household: dict, predicted: set[str]) -> dict:
    groups = [set(item.get("any_of") or [item["scheme_id"]]) for item in household["expected"]]
    expected_ids = set().union(*groups) if groups else set()
    acceptable = set(household["acceptable_extra"])
    tp_items = [sorted(g) for g in groups if g & predicted]
    fn_items = [sorted(g) for g in groups if not g & predicted]
    matched = predicted & expected_ids
    fp = sorted(predicted - expected_ids - acceptable)
    return {"tp": len(tp_items), "fn": len(fn_items), "fp": len(fp), "matched_predictions": len(matched),
            "missed": fn_items, "false_positives": fp, "ignored_extras": sorted(predicted & acceptable - expected_ids)}


def run_one(household: dict) -> dict:
    hid = state.new_household(household["profile"], source=f"eval:{household['id']}")
    t0 = time.time()
    err = None
    try:
        with neatlogs.trace(f"eval:{household['id']}", kind="WORKFLOW", session_id=hid, eval_case=household["id"]):
            run = agent.run(hid)
    except Exception as e:  # keep scoring the rest; a crash counts as predicting nothing
        err = f"{type(e).__name__}: {e}"
        run = state.latest_run(hid)
    elapsed = time.time() - t0
    cards = (run or {}).get("result", {}) or {}
    cards = cards.get("cards", [])
    predicted = {catalog.canonical_id(c["scheme_id"]) for c in cards}
    confirmed = {catalog.canonical_id(c["scheme_id"]) for c in cards if c.get("verification", "confirmed") == "confirmed"}
    research = (run or {}).get("research", {})
    return {
        "id": household["id"], "description": household["description"], "household_state_id": hid,
        "error": err, "seconds": round(elapsed, 1), "cost_usd": (run or {}).get("usage", {}).get("cost_usd", 0.0),
        "usage": (run or {}).get("usage"),
        "predicted": sorted(predicted),
        "expected": [item.get("any_of") or [item["scheme_id"]] for item in household["expected"]],
        "predicted_likely": sorted(predicted - confirmed),
        "score": score(household, predicted),
        "score_confirmed_only": score(household, confirmed),
        "total_missing_inr_per_year": ((run or {}).get("result") or {}).get("total_missing_inr_per_year"),
        "verified_sources": {c["scheme_id"]: c["official_url"] for c in cards},
        "likely_unconfirmed_rules": {c["scheme_id"]: c.get("unconfirmed_rules", []) for c in cards
                                     if c.get("verification") == "likely"},
        "dropped": {k: r.get("reason") for k, r in research.items() if r.get("status") == "dropped"},
        "conflicts": (run or {}).get("conflicts", []),
        "unofficial_claims": (run or {}).get("unofficial_claims", []),
        "recoveries": len((run or {}).get("recovery_log", [])),
    }


def summarize(rows: list[dict], key: str = "score") -> dict:
    tp = sum(r[key]["tp"] for r in rows)
    fn = sum(r[key]["fn"] for r in rows)
    fp = sum(r[key]["fp"] for r in rows)
    matched = sum(r[key]["matched_predictions"] for r in rows)
    n = len(rows) or 1
    precision = matched / (matched + fp) if matched + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "households": len(rows), "errors": sum(1 for r in rows if r["error"]),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "accuracy": round(tp / (tp + fp + fn), 4) if tp + fp + fn else 1.0,
        "avg_cost_usd": round(sum(r["cost_usd"] for r in rows) / n, 4),
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / n, 1),
        "recoveries": sum(r["recoveries"] for r in rows),
        "conflicts_logged": sum(len(r["conflicts"]) for r in rows),
        "likely_predictions": sum(len(r.get("predicted_likely", [])) for r in rows),
        "unofficial_claims_logged": sum(len(r.get("unofficial_claims", [])) for r in rows),
    }


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated household ids")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    data = json.load(open(FAMILIES, encoding="utf-8"))
    households = data["households"]
    if args.only:
        keep = set(args.only.split(","))
        households = [h for h in households if h["id"] in keep]

    previous = sorted(glob.glob("evals/results-*.json"))
    rows = []
    print(f"Running Haq on {len(households)} households (model={config.MODEL}, effort={config.EFFORT}, "
          f"simulate_failure={config.SIMULATE_FAILURE})\n")
    with neatlogs.trace("eval_suite", kind="WORKFLOW", households=len(households)):
        with ThreadPoolExecutor(args.workers) as pool:
            futs = [pool.submit(contextvars.copy_context().run, run_one, h) for h in households]
            for fut in as_completed(futs):
                r = fut.result()
                rows.append(r)
                s = r["score"]
                print(f"  {r['id']}: tp={s['tp']} fp={s['fp']} fn={s['fn']}  {r['seconds']:>6.1f}s  ${r['cost_usd']:.3f}"
                      + (f"  ERROR {r['error']}" if r["error"] else "")
                      + (f"  missed={s['missed']}" if s["missed"] else "")
                      + (f"  fp={s['false_positives']}" if s["false_positives"] else ""))
    rows.sort(key=lambda r: r["id"])
    summary = summarize(rows)
    # Same metrics counting only schemes confirmed end-to-end (likely-eligible cards excluded)
    summary["confirmed_only"] = {k: v for k, v in summarize(rows, "score_confirmed_only").items()
                                 if k in ("tp", "fp", "fn", "precision", "recall", "f1", "accuracy")}

    ts = time.strftime("%Y%m%d-%H%M%S")
    out = {
        "timestamp": ts, "git_commit": _git_commit(),
        "config": {"model": config.MODEL, "effort": config.EFFORT, "simulate_failure": config.SIMULATE_FAILURE,
                   "only": args.only},
        "summary": summary, "households": rows,
    }
    path = f"evals/results-{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== Summary ===")
    for k in ("precision", "recall", "f1", "accuracy", "avg_cost_usd", "total_cost_usd", "avg_seconds",
              "recoveries", "conflicts_logged", "unofficial_claims_logged", "likely_predictions", "errors"):
        print(f"  {k:<18} {summary[k]}")
    print(f"  confirmed_only     {summary['confirmed_only']}")
    if previous:
        prev = json.load(open(previous[-1], encoding="utf-8"))["summary"]
        print(f"\n=== Change vs {previous[-1]} ===")
        for k in ("precision", "recall", "accuracy", "avg_cost_usd", "avg_seconds"):
            print(f"  {k:<18} {prev.get(k)} -> {summary[k]}")
    print(f"\nSaved {path}")
    neatlogs.flush()
    neatlogs.shutdown()
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
