"""Does the app stop quickly on SIGTERM while a run is mid-research? (no model or web calls)

    .venv/bin/python scripts/test_shutdown.py

Starts the real app with uvicorn, replaces the research step with one that blocks for 120 s (like a slow
model call or government site), starts a run, sends SIGTERM and measures how long the process takes to exit.
After a restart the interrupted run must resume (status still 'running', not 'failed').
"""
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8051
LIMIT_S = 10

SERVER = textwrap.dedent(f"""
    import os, sys, time, threading
    sys.path.insert(0, {ROOT!r}); os.chdir({ROOT!r})
    import app as appmod
    from haq import agent
    def slow_research(profile, cands, usage, hid, rid, abort=None):
        for _ in range(1200):                 # 120 s, like a stuck model call / slow government site
            time.sleep(0.1)
        return {{}}
    agent.research_scheme = slow_research
    agent.plan = lambda profile, usage, hid: [{{"scheme_id": "pm_kisan", "member": "self", "why": "", "key": "pm_kisan:self"}},
                                              {{"scheme_id": "pmsby", "member": "self", "why": "", "key": "pmsby:self"}}]
    import uvicorn
    uvicorn.run(appmod.app, host="127.0.0.1", port={PORT}, log_level="warning", timeout_graceful_shutdown=5)
""")


def start(state):
    env = {**os.environ, "NEATLOGS_API_KEY": "", "ANTHROPIC_API_KEY": "stub-no-calls", "HAQ_STATE_FILE": state}
    p = subprocess.Popen([os.path.join(ROOT, ".venv/bin/python"), "-c", SERVER], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    for _ in range(80):
        try:
            httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1)
            return p
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("server did not start: " + p.stderr.read().decode()[-500:])


def main():
    state = os.path.join(tempfile.mkdtemp(prefix="haq-stop-"), "state.json")
    p = start(state)
    base = f"http://127.0.0.1:{PORT}"
    hid = httpx.post(f"{base}/api/households", json={"lang": "en"}).json()["id"]
    b = {"members": [{"role": "father", "tags": ["farmer"]}], "income": "low"}
    r = httpx.post(f"{base}/api/households/{hid}/intake", json={"lang": "en", "builder": b}).json()
    if r.get("followups"):
        httpx.post(f"{base}/api/households/{hid}/answers",
                   json={"lang": "en", "answers": {f["id"]: f["options"][0]["value"] for f in r["followups"]}})
    time.sleep(2)                                   # research is now blocked inside the worker threads
    t0 = time.time()
    p.send_signal(signal.SIGTERM)
    try:
        p.wait(timeout=60)
        took = time.time() - t0
    except subprocess.TimeoutExpired:
        took = None
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
    ok_stop = took is not None and took < LIMIT_S
    print(("PASS" if ok_stop else "FAIL") + f" SIGTERM -> exit in {took:.1f}s" if took is not None
          else f"FAIL SIGTERM -> still running after 60s (killed)", f"(limit {LIMIT_S}s)")
    import json
    run = json.load(open(state))["households"][hid]["runs"][-1]
    ok_state = run["status"] == "running"
    print(("PASS" if ok_state else "FAIL") + f" interrupted run left resumable: status={run['status']!r} error={run.get('error')!r}")
    return 0 if ok_stop and ok_state else 1


if __name__ == "__main__":
    sys.exit(main())
