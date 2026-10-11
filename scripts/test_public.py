"""Local tests for the public-deployment features, against the stub server (no model or web calls).

    .venv/bin/python scripts/test_public.py

Covers: /health, DEMO replay (API + browser, both languages), LIVE passcode gate (missing / wrong / tampered
token / brute force), per-IP live-run rate limit, daily budget fallback (before a run and mid-run), the
daily cap inside llm.create, and that no response ever carries keys, traces or server error text.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8031
BASE = f"http://127.0.0.1:{PORT}"
PASS = "test-pass-123"
results: list[tuple[str, bool, str]] = []
seen_bodies: list[str] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  — {detail}" if detail else ""))


def server(extra=None):
    tmp = tempfile.mkdtemp(prefix="haq-pub-")
    env = {**os.environ, "PORT": str(PORT), "STUB_SPEED": "4", "STUB_STATE_FILE": os.path.join(tmp, "state.json"),
           "HAQ_PUBLIC": "1", "HAQ_LIVE_PASSCODE": PASS, "HAQ_DAILY_BUDGET_USD": "1.00", "HAQ_LIVE_RUNS_PER_HOUR": "2",
           **(extra or {})}
    p = subprocess.Popen([os.path.join(ROOT, ".venv/bin/python"), "scripts/ui_stub_server.py"], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(80):
        try:
            httpx.get(BASE + "/health", timeout=1)
            return p, tmp
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("server did not start")


def stop(p):
    os.killpg(p.pid, signal.SIGKILL)
    p.wait()


def req(method, path, token=None, **kw):
    headers = {"X-Haq-Live": token} if token else {}
    r = httpx.request(method, BASE + path, headers=headers, timeout=15, **kw)
    seen_bodies.append(r.text)
    return r


BUILDER = {"members": [{"role": "mother", "tags": ["widow"]}, {"role": "father", "tags": ["farmer"]}], "income": "low"}


def live_run(token, ip_note=""):
    """Create -> builder intake -> answer follow-ups. Returns the final response of the start step."""
    hid = req("POST", "/api/households", token, json={"lang": "en"}).json()["id"]
    r = req("POST", f"/api/households/{hid}/intake", token, json={"lang": "en", "builder": BUILDER})
    body = r.json()
    if r.status_code != 200 or not body.get("followups"):
        return hid, r
    ans = {f["id"]: f["options"][0]["value"] for f in body["followups"]}
    return hid, req("POST", f"/api/households/{hid}/answers", token, json={"lang": "en", "answers": ans})


def main():
    # ------------------------------------------------------------ server 1: normal public config
    p, tmp = server()
    try:
        r = req("GET", "/health")
        check("/health returns ok without model calls", r.status_code == 200 and r.json() == {"status": "ok"}, r.text)

        cfg = req("GET", "/api/config").json()
        check("config: live needs a passcode", cfg["live"]["needs_passcode"] and cfg["live"]["available"], json.dumps(cfg["live"]))
        check("config: demo recordings listed (no profiles/results)", len(cfg["demo"]) >= 5 and all("profile" not in d and "result" not in d for d in cfg["demo"]),
              f"{len(cfg['demo'])} recordings")

        # ---- DEMO
        rid = next(d["id"] for d in cfg["demo"] if "hi" in d["langs"] and d["source"] == "live")
        did = req("POST", f"/api/demo/{rid}").json()["id"]
        counts, done = [], None
        for _ in range(60):
            d = req("GET", f"/api/households/{did}?lang=hi").json()
            counts.append(len(d["run"]["events"]))
            if d["result"]:
                done = d
                break
            time.sleep(0.5)
        check("demo: steps replay over time (live animation)", len(set(counts)) > 3 and counts == sorted(counts), f"event counts {counts[:6]}…{counts[-1]}")
        check("demo: finishes with the recorded result", bool(done and done["result"]["cards"]), f"{len(done['result']['cards']) if done else 0} cards")
        check("demo: labelled as a demo (title + source)", bool(done and done["demo"] and done["demo"]["title"]["hi"]), json.dumps(done["demo"], ensure_ascii=False)[:90] if done else "")
        en = req("GET", f"/api/households/{did}?lang=en").json()
        check("demo: Hindi-only recording viewed in English -> Hindi text + note (no translation call)",
              en["result"]["lang_note"] == "recorded_in_hindi_only", str(en["result"]["lang_note"]))
        rid_en = next(d["id"] for d in cfg["demo"] if "en" in d["langs"])
        did_en = req("POST", f"/api/demo/{rid_en}").json()["id"]
        time.sleep(19.5)
        en2 = req("GET", f"/api/households/{did_en}?lang=en").json()
        check("demo: English recording shows its recorded English translation", bool(en2["result"]) and en2["result"]["lang_note"] is None,
              (en2["result"] or {}).get("summary", "")[:70])
        check("demo: unknown recording -> 404", req("POST", "/api/demo/nope").status_code == 404)
        check("demo: no live calls allowed on a demo id", req("POST", f"/api/households/{did}/intake", json={"lang": "hi", "text": "x"}).status_code in (401, 404))

        # ---- PASSCODE GATE
        r = req("POST", "/api/households", json={"lang": "hi"})
        check("live without token -> 401 passcode", r.status_code == 401 and r.json() == {"error": "passcode"}, r.text)
        r = req("POST", "/api/live/unlock", json={"passcode": "wrong"})
        check("wrong passcode -> 401", r.status_code == 401 and r.json()["error"] == "passcode", r.text)
        r = req("POST", "/api/households", "9999999999.deadbeef", json={"lang": "hi"})
        check("forged token -> 401", r.status_code == 401, r.text)
        r = req("POST", "/api/live/unlock", json={"passcode": PASS})
        token = r.json().get("token")
        check("right passcode -> signed token", r.status_code == 200 and token and "." in token, f"expires_in={r.json().get('expires_in')}")
        exp, sig = token.split(".")
        r = req("POST", "/api/households", f"{int(exp) + 999}.{sig}", json={"lang": "hi"})
        check("token with edited expiry -> 401", r.status_code == 401, r.text)

        # ---- RATE LIMIT (2 live runs per hour per IP)
        codes = []
        for _ in range(3):
            _, r = live_run(token)
            codes.append(r.status_code if r.status_code != 200 else "ok")
        check("live runs per IP: 2 allowed, 3rd -> 429 rate_limit", codes[:2] == ["ok", "ok"] and codes[2] == 429, str(codes))
        # brute force on the passcode (5 per 15 min; 2 attempts used above)
        bf = [req("POST", "/api/live/unlock", json={"passcode": f"guess{i}"}).status_code for i in range(5)]
        check("passcode brute force -> 429 after 5 attempts", 429 in bf, str(bf))

        # ---- BUDGET: daily cap already used up
        spend = os.path.join(tmp, "spend-by-day.json")
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5.5 * 3600))
        json.dump({today: 1.00}, open(spend, "w"))
        cfg = req("GET", "/api/config").json()
        check("budget used up -> config says live unavailable (budget)", cfg["live"] == {"available": False, "needs_passcode": True, "reason": "budget"}, json.dumps(cfg["live"]))
        r = req("POST", "/api/households", token, json={"lang": "hi"})
        check("budget used up -> new live check refused 402 budget", r.status_code == 402 and r.json() == {"error": "budget"}, r.text)
        check("budget used up -> demo still works", req("POST", f"/api/demo/{rid}").status_code == 200)
    finally:
        stop(p)

    # ------------------------------------------------------------ server 2: the cap trips mid-run
    p, tmp = server({"STUB_FAIL_BUDGET": "1", "HAQ_LIVE_RUNS_PER_HOUR": "5"})
    try:
        token = req("POST", "/api/live/unlock", json={"passcode": PASS}).json()["token"]
        hid, r = live_run(token)
        d = None
        for _ in range(30):
            d = req("GET", f"/api/households/{hid}?lang=hi").json()
            if d["run"] and d["run"]["status"] == "failed":
                break
            time.sleep(0.3)
        check("cap trips mid-run -> run reports error_code budget (no error text)",
              d["run"]["error_code"] == "budget" and "error" not in d["run"], json.dumps(d["run"])[:120])
        browser_checks(token)
    finally:
        stop(p)

    # ------------------------------------------------------------ the daily cap inside llm.create (offline)
    out = subprocess.run([os.path.join(ROOT, ".venv/bin/python"), "-c", """
import os, tempfile, types
os.environ.update(NEATLOGS_API_KEY="", HAQ_STATE_FILE=os.path.join(tempfile.mkdtemp(), "s.json"), HAQ_DAILY_BUDGET_USD="0.01")
from haq import llm
fake = lambda: types.SimpleNamespace(model="claude-sonnet-5-5", stop_reason="end_turn", content=[], usage=types.SimpleNamespace(
    input_tokens=1000, output_tokens=1000, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None))
llm.client = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: fake()))
llm.create(None, system="s", messages=[])
try:
    llm.create(None, system="s", messages=[]); print("NOT BLOCKED")
except llm.BudgetExceeded as e:
    print("BLOCKED", llm.daily_spent_usd())
"""], cwd=ROOT, capture_output=True, text=True)
    check("llm.create refuses calls once the daily cap is spent (persisted per IST day)", "BLOCKED" in out.stdout, out.stdout.strip()[-60:])

    # ------------------------------------------------------------ nothing secret ever reached the browser
    leaks = [w for w in ("sk-ant", "trace_id", "neatlogs", "Traceback", "BudgetExceeded", "ANTHROPIC", "live-secret")
             if any(w in b for b in seen_bodies)]
    check(f"no keys / traces / server errors in {len(seen_bodies)} responses", not leaks, str(leaks))

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def browser_checks(token):
    """Real Chrome: demo replay with banner in both languages, passcode screen, friendly budget message."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", headless=True)
        for lang in ("hi", "en"):
            ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.goto(BASE + "/?new")
            pg.click(f"[data-pick='{lang}']")
            pg.wait_for_selector("#s-home.on")
            n = pg.locator("#demoList .demo-card").count()
            pg.locator("#demoList .demo-card").first.click()
            pg.wait_for_selector("#s-work.on")
            pg.wait_for_timeout(4000)
            banner = pg.inner_text("#demoBanner")
            steps = pg.locator("#steps .step").count()
            pg.wait_for_selector("#s-results.on", timeout=30000)
            ask_hidden = pg.evaluate("() => document.querySelector('#askBtn').classList.contains('hidden')")
            check(f"browser demo ({lang}): {n} recordings, banner, animated steps, results, no 'ask' in demo",
                  n >= 2 and ("डेमो" in banner or "Demo" in banner) and steps >= 3 and ask_hidden and not errs,
                  f"banner={banner[:40]!r} steps={steps} errors={errs[:2]}")
            # live button -> passcode screen
            pg.click("#restart")
            pg.wait_for_selector("#s-home.on")
            pg.click("#toLive")
            pg.wait_for_selector("#s-pass.on")
            pg.fill("#passBox", "wrong")
            pg.click("#passGo")
            pg.wait_for_selector("#passErr:not(.hidden)")
            check(f"browser passcode ({lang}): wrong passcode shows a friendly message", True, pg.inner_text("#passErr"))
            pg.fill("#passBox", PASS)
            pg.click("#passGo")
            pg.wait_for_selector("#s-start.on")
            # this server trips the budget mid-run -> friendly message back on home
            pg.click("#toBuilder")
            pg.locator("#roleChips .chip").first.click()
            pg.click("#builderGo")
            for _ in range(40):
                scr = pg.evaluate("() => document.querySelector('.screen.on').id")
                if scr == "s-follow":
                    pg.locator("#qOptions .option").first.click()
                if scr == "s-home":
                    break
                pg.wait_for_timeout(400)
            note = pg.inner_text("#liveNote") if pg.evaluate("() => !document.querySelector('#liveNote').classList.contains('hidden')") else ""
            check(f"browser budget fallback ({lang}): back to demos with a friendly message",
                  scr == "s-home" and ("सीमा" in note or "used up" in note), note[:80])
            ctx.close()
        b.close()


if __name__ == "__main__":
    sys.exit(main())
