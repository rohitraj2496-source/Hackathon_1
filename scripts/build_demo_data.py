"""Package real recorded runs into demo/recorded_runs.json for the public DEMO mode.

    .venv/bin/python scripts/build_demo_data.py

Reads local state files (data/ is gitignored, so the server cannot see them) and writes a committed bundle:
the family profile, the recorded result (with any English translation already made), and the recorded
step events. Live runs keep their real events; eval runs ran before step events existed, so their steps
are rebuilt from that run's own research and recovery records. No model calls.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("NEATLOGS_API_KEY", "")
from haq import catalog  # noqa: E402

USD_TO_INR = 88

# (state file, household id, recording id, languages offered, emoji, title hi, title en, source)
PICKS = [
    ("data/live-test-state.json", "8936735b31", "widow-farmer-student-hi", ["hi"], "👩‍🌾",
     "माँ विधवा, पापा किसान (2 एकड़), बेटी पढ़ती है — छूकर बताया", None, "live"),
    ("data/live-test-state.json", "2021a924e6", "widow-farmer-student-en", ["en"], "👩‍🌾",
     None, "Widowed mother, farmer father, student daughter — tap builder", "live"),
    ("data/live-test-state.json", "3860bdfa10", "disabled-grandfather-en", ["en"], "🧓",
     None, "Village family with a 72-year-old disabled grandfather — typed in English", "live"),
    ("data/live-test-state.json", "b850d82182", "website-failure-recovery-hi", ["hi"], "🔁",
     "सरकारी वेबसाइट जानबूझकर फेल की गई — दूसरे सरकारी स्रोत से जाँच देखिए", None, "live"),
    ("data/live-test-state.json", "aa820aab3e", "elderly-widow-hi", ["hi"], "👵",
     "74 साल की विधवा, गाँव में अकेली, अंत्योदय कार्ड — बोलकर बताया", None, "live"),
    ("data/eval-state.json", "12497bc458", "construction-worker-h05-hi", ["hi"], "👷",
     "गाज़ियाबाद: भवन निर्माण मज़दूर, पत्नी गर्भवती, राशन कार्ड नहीं", None, "eval"),
    ("data/eval-state.json", "ba03985258", "obc-students-h06-hi", ["hi"], "🎓",
     "वाराणसी: दुकानदार परिवार, बेटी B.A. में, बेटा कक्षा 10 में", None, "eval"),
    ("data/eval-state.json", "2e47367fca", "tailor-two-daughters-h10-hi", ["hi"], "🧵",
     "मुरादाबाद: दर्ज़ी, दो बेटियाँ (कक्षा 9 और 5)", None, "eval"),
]
REPLAY_SECONDS = 18.0
MAX_REPLAY_PAUSE = 2.5   # seconds; a long real pause (e.g. planning) would look stuck in a replay
MAX_GAP = 20.0     # seconds; longer silences between two recorded steps are idle time


def _dedupe(events):
    """A resumed run logs some steps twice; keep the last state of each step, in time order."""
    seen, out = set(), []
    for e in reversed(events):
        key = (e["type"], e.get("scheme_id"), e.get("requested"))
        if e["type"] in ("recovered", "source_failed") or key not in seen:
            seen.add(key)
            out.append(e)
    return list(reversed(out))


def _rebuilt_events(run):
    """Steps of an eval run, rebuilt from its recorded research and recovery logs (no events were logged)."""
    research = run["research"]
    schemes = sorted({r["scheme_id"] for r in research.values()})
    prot = [s for s in schemes if s in catalog.PROTECTION]
    ev = [{"type": "understood"}, {"type": "planned", "schemes": len(schemes) - len(prot), "protection": len(prot)}]
    for sid in schemes:
        recs = [r for r in research.values() if r["scheme_id"] == sid]
        ev.append({"type": "checking", "scheme_id": sid, "from_cache": any(r.get("rules_from_cache") for r in recs)})
        for rl in run.get("recovery_log", []):
            if str(rl.get("scheme", "")).split(":")[0] == sid:
                ev.append({"type": "recovered" if rl.get("ok") else "source_failed", "scheme_id": sid,
                           "fell_back": rl.get("served_by") not in (None, rl.get("requested"))})
        statuses = {r.get("status") for r in recs}
        ev.append({"type": "scheme_done", "scheme_id": sid,
                   "outcome": "confirmed" if "verified" in statuses else "likely" if "likely" in statuses else "not_eligible"})
    ev += [{"type": "writing"}, {"type": "done"}]
    step = REPLAY_SECONDS / max(len(ev) - 1, 1)
    for i, e in enumerate(ev):
        e["at"] = round(i * step, 2)
    return ev


def main():
    out = []
    states = {}
    for path, hid, rid, langs, emoji, title_hi, title_en, source in PICKS:
        states.setdefault(path, json.load(open(os.path.join(ROOT, path), encoding="utf-8"))["households"])
        h = states[path][hid]
        run = h["runs"][-1]
        if source == "live":
            evs = _dedupe(run["events"])
            # active time only: a run paused between attempts (stopped at a spend cap, then resumed) has an
            # idle gap that is neither work nor worth replaying
            active, last = [0.0], evs[0]["t"]
            for e in evs[1:]:
                active.append(active[-1] + min(e["t"] - last, MAX_GAP))
                last = e["t"]
            scale = min(1.0, REPLAY_SECONDS / max(active[-1], 0.001))
            events = [{**{k: v for k, v in e.items() if k != "t"}, "at": round(a * scale, 2)} for e, a in zip(evs, active)]
            seconds = round(active[-1] + min(evs[0]["t"] - run["started_at"], MAX_GAP))
        else:
            events = _rebuilt_events(run)
            seconds = round((run.get("finished_at") or 0) - run["started_at"])
        # same order and relative pacing, but no single pause longer than MAX_REPLAY_PAUSE
        at, prev_raw = 0.0, events[0]["at"]
        for e in events:
            at += min(e["at"] - prev_raw, MAX_REPLAY_PAUSE)
            prev_raw, e["at"] = e["at"], round(at, 2)
        result = {k: v for k, v in run["result"].items() if k != "dropped_by_rules"}
        out.append({
            "id": rid, "langs": langs, "emoji": emoji,
            "title": {"hi": title_hi or title_en, "en": title_en or title_hi},
            "source": source,                      # live = real end-to-end run; eval = real eval-suite run
            "steps": "recorded" if source == "live" else "rebuilt from the run's research log",
            "recorded_seconds": seconds,
            "cost_inr": round(run["usage"]["cost_usd"] * USD_TO_INR, 1),
            "profile": h["profile"], "result": result, "events": events,
        })
    os.makedirs(os.path.join(ROOT, "demo"), exist_ok=True)
    path = os.path.join(ROOT, "demo", "recorded_runs.json")
    json.dump({"note": "Real Haq runs replayed in DEMO mode. Built by scripts/build_demo_data.py. "
                       "No API keys, trace IDs or server errors are included.",
               "usd_to_inr": USD_TO_INR, "recordings": out}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {path}: {len(out)} recordings")
    for r in out:
        print(f"  {r['id']:32} {r['langs']} {r['source']:4} events={len(r['events']):2} "
              f"replay={r['events'][-1]['at']}s real={r['recorded_seconds']}s ₹{r['cost_inr']}")


if __name__ == "__main__":
    main()
