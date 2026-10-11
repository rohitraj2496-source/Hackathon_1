"""Phase 2: real end-to-end runs through the real app server, with a hard total spend cap.

    .venv/bin/python scripts/live_test.py --cap 2.00

Each scenario gets a fresh app server whose HAQ_BUDGET_USD is the remaining budget minus a safety
margin for calls already in flight, so the process refuses further model calls before the cap.
Total spend is read from every server (/api/debug/spend) and checked before each scenario.
Writes docs/stress/live-results.json.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STATE = os.path.join(ROOT, "data", "live-test-state.json")
OUT = os.path.join(ROOT, "docs", "stress", "live-results.json")
MARGIN_PER_LOOP = 0.05      # worst-case spend of one in-flight research call after the cap trips

spent_total = 0.0
results = []


def start_server(port, budget, extra_env=None):
    env = {**os.environ, "HAQ_STATE_FILE": STATE, "HAQ_BUDGET_USD": f"{budget:.4f}", **(extra_env or {})}
    p = subprocess.Popen([os.path.join(ROOT, ".venv/bin/uvicorn"), "app:app", "--host", "127.0.0.1", "--port", str(port)],
                         cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=open(f"/tmp/haq-live-{port}.log", "w"),
                         start_new_session=True)
    for _ in range(80):
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
            return p
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"server on {port} did not start")


def stop_server(p, port):
    global spent_total
    try:
        spent = httpx.get(f"http://127.0.0.1:{port}/api/debug/spend", timeout=5).json()["spent_usd"]
    except Exception:
        spent = None
    os.killpg(p.pid, signal.SIGTERM)
    p.wait(timeout=20)
    if spent is not None:
        spent_total += spent
    return spent


def run_family(port, name, lang, builder=None, text=None, answers=None, timeout=900):
    base = f"http://127.0.0.1:{port}"
    c = httpx.Client(timeout=120)
    t0 = time.time()
    rec = {"scenario": name, "lang": lang, "error": None}
    try:
        hid = c.post(f"{base}/api/households", json={"lang": lang}).json()["id"]
        rec["household_id"] = hid
        r = c.post(f"{base}/api/households/{hid}/intake", json={"lang": lang, **({"builder": builder} if builder else {"text": text})})
        r.raise_for_status()
        r = r.json()
        if r.get("need_more"):
            rec["error"] = "intake: family not understood"
            return rec
        rec["followups_asked"] = [(f["id"], f["question"]) for f in r["followups"]]
        if r["followups"]:
            chosen = {f["id"]: (answers or {}).get(f["id"], f["options"][0]["value"]) for f in r["followups"]}
            rec["followup_answers"] = chosen
            c.post(f"{base}/api/households/{hid}/answers", json={"lang": lang, "answers": chosen}).raise_for_status()
        while time.time() - t0 < timeout:
            d = c.get(f"{base}/api/households/{hid}?lang={lang}").json()
            run = d["run"]
            if run and run["status"] in ("done", "failed"):
                break
            time.sleep(3)
        rec["seconds"] = round(time.time() - t0, 1)
        run, res = d["run"], d["result"]
        rec["status"] = run["status"] if run else "no-run"
        rec["run_error"] = run.get("error") if run else None
        rec["cost_usd"] = run["cost_usd"] if run else 0
        rec["neatlogs"] = {"session_id": hid, "trace_ids": [t["trace_id"] for t in (run or {}).get("traces", [])]}
        rec["recovery_events"] = [e for e in (run or {}).get("events", []) if e["type"] in ("recovered", "source_failed")]
        if res:
            money = [x for x in res["cards"] if x["category"] != "protection"]
            prot = [x for x in res["cards"] if x["category"] == "protection"]
            rec["headline"] = {"up_to": res["owed_up_to_inr_per_year"], "confirmed": res["total_missing_inr_per_year"],
                               "after_checks": res["likely_extra_inr_per_year"]}
            rec["confirmed"] = [f"{x['name']} ({x['member']})" for x in money if x["verification"] == "confirmed"]
            rec["check_needed"] = [f"{x['name']} ({x['member']}): {', '.join(x['check_needed'])}" for x in money
                                   if x["verification"] != "confirmed"]
            rec["protection"] = [f"{x['name']} ({x['member']})" for x in prot]
            rec["links"] = sorted({u for x in res["cards"] for u in (x["official_url"], x["apply_url"]) if u and u.startswith("http")})
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
        rec["seconds"] = round(time.time() - t0, 1)
    return rec


FAMILY_1 = {"members": [{"role": "mother", "tags": ["widow"]}, {"role": "father", "tags": ["farmer"]},
                        {"role": "daughter", "tags": ["student"]}], "income": "low"}
ANSWERS_1 = {"ration_card": "eligible_household", "land": "yes", "area": "rural", "house": "kutcha", "lpg": "yes"}
TEXT_2 = ("I live in a village in Sitapur district with my wife and my father. My father is 72 years old and disabled, "
          "he has a 60 percent disability certificate. I am 38 and work as a daily wage labourer, my wife is 34 and "
          "looks after the home. We earn about 6000 rupees a month. We have a ration card.")
ANSWERS_2 = {"house": "kutcha", "lpg": "no", "land": "no", "area": "rural"}
TEXT_3 = "मैं 74 साल की विधवा हूँ, गाँव में अकेली रहती हूँ, अंत्योदय राशन कार्ड है, कच्चा घर है, गैस नहीं है।"


def guarded(cap, est, label):
    if spent_total + est > cap:
        print(f"STOP before {label}: spent ${spent_total:.3f} + estimated ${est:.2f} would exceed ${cap:.2f}")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=2.0)
    args = ap.parse_args()
    cap = args.cap
    plan = [
        ("1-hindi-builder", 0.30, 8020, {}, [dict(name="1-hindi-builder", lang="hi", builder=FAMILY_1, answers=ANSWERS_1)]),
        ("2-english-typed-disabled-grandfather", 0.35, 8020, {}, [dict(name="2-english-typed", lang="en", text=TEXT_2, answers=ANSWERS_2)]),
        ("3-hindi-builder-SIMULATE_FAILURE", 0.60, 8021, {"SIMULATE_FAILURE": "1", "HAQ_NO_CACHE": "1"},
         [dict(name="3-simulate-failure", lang="hi", builder=FAMILY_1, answers=ANSWERS_1)]),
        ("4-three-concurrent", 0.70, 8020, {}, [
            dict(name="4a-concurrent-builder-en", lang="en", builder=FAMILY_1, answers=ANSWERS_1),
            dict(name="4b-concurrent-typed-en", lang="en", text=TEXT_2, answers=ANSWERS_2),
            dict(name="4c-concurrent-typed-hi", lang="hi", text=TEXT_3)]),
    ]
    for label, est, port, env, fams in plan:
        if not guarded(cap, est, label):
            break
        budget = max(0.0, cap - spent_total - MARGIN_PER_LOOP * 4 * len(fams))
        print(f"\n== {label}: server cap ${budget:.3f} (spent so far ${spent_total:.3f})", flush=True)
        p = start_server(port, budget, env)
        try:
            with ThreadPoolExecutor(len(fams)) as pool:
                recs = list(pool.map(lambda f: run_family(port, **f), fams))
        finally:
            spent = stop_server(p, port)
        for r in recs:
            r["group"] = label
            results.append(r)
            print(json.dumps({k: r.get(k) for k in ("scenario", "status", "error", "run_error", "seconds", "cost_usd", "headline",
                                                    "confirmed", "check_needed", "protection", "neatlogs")},
                             ensure_ascii=False, indent=1))
            if r.get("recovery_events"):
                print("   recovery:", [(e["type"], e.get("scheme_id"), e.get("requested"), e.get("served_by")) for e in r["recovery_events"]])
        print(f"   server spend for {label}: ${spent}  | total so far ${spent_total:.4f} of ${cap:.2f}", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"cap_usd": cap, "spent_usd": round(spent_total, 4), "runs": results}, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"\nTOTAL SPENT ${spent_total:.4f} (cap ${cap:.2f}). Saved {OUT}")


if __name__ == "__main__":
    main()
