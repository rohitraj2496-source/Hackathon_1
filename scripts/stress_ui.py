"""Stress-test the Haq web UI against the stub server (no model or web calls).

    .venv/bin/python scripts/stress_ui.py            # report -> docs/stress/report.json, failures -> docs/stress/*.png

Uses Playwright with the locally installed Google Chrome. Starts (and kills/restarts) its own stub server.
Every scenario records: JS console errors, page errors, 4xx/5xx responses, hangs (expected screen or message
not reached in time), horizontal overflow / clipped text / tap targets < 44px, and buttons that do nothing.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "stress")
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"
STATE = os.path.join(tempfile.mkdtemp(prefix="haq-stress-"), "state.json")
WIDTHS = [360, 390, 768]
LANGS = ["hi", "en"]
ISSUES: list[dict] = []
PASSES: list[str] = []
server = None


# ------------------------------------------------------------------ stub server lifecycle
def start_server(speed="3"):
    global server
    env = {**os.environ, "STUB_STATE_FILE": STATE, "STUB_SPEED": speed, "PORT": str(PORT),
           # one test machine plays every visitor: lift the per-IP and capacity limits (test_public.py tests them)
           "HAQ_LIVE_RUNS_PER_HOUR": "100000", "HAQ_MODEL_CALLS_PER_HOUR": "100000", "HAQ_MAX_CONCURRENT_RUNS": "1000"}
    server = subprocess.Popen([os.path.join(ROOT, ".venv/bin/python"), "scripts/ui_stub_server.py"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        try:
            httpx.get(BASE + "/", timeout=1)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("stub server did not start")


def kill_server():
    if server and server.poll() is None:
        os.killpg(server.pid, signal.SIGKILL)
        server.wait()


# ------------------------------------------------------------------ helpers
def issue(scenario, kind, detail, page=None):
    entry = {"scenario": scenario, "kind": kind, "detail": detail}
    if page is not None:
        name = f"{len(ISSUES) + 1:02d}-{scenario}-{kind}".replace(" ", "_").replace("/", "_")[:90] + ".png"
        try:
            page.screenshot(path=os.path.join(OUT, name), full_page=True)
            entry["screenshot"] = f"docs/stress/{name}"
        except Exception:
            pass
    ISSUES.append(entry)


INIT = """
window.__speaks = 0;
try { const s = window.speechSynthesis.speak.bind(window.speechSynthesis);
      window.speechSynthesis.speak = (u) => { window.__speaks++; try { s(u); } catch (e) {} }; } catch (e) {}
"""
NO_SPEECH_API = "delete window.SpeechRecognition; delete window.webkitSpeechRecognition;"


class Session:
    """One browser context + page with error/network recorders."""

    def __init__(self, browser, scenario, lang="hi", width=390, extra_init=None, permissions=None):
        self.scenario = scenario
        self.ctx = browser.new_context(viewport={"width": width, "height": 844 if width < 700 else 1024},
                                       is_mobile=width < 700, has_touch=True, permissions=permissions or [])
        self.ctx.add_init_script(INIT + (extra_init or ""))
        self.ctx.add_init_script(f"try {{ localStorage.setItem('haq_lang', '{lang}'); }} catch (e) {{}}")
        self.page = self.ctx.new_page()
        self.errors, self.bad = [], []
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("response", lambda r: self.bad.append(f"{r.status} {r.request.method} {r.url}")
                     if r.status >= 400 else None)
        self.page.goto(BASE, wait_until="domcontentloaded")
        # home screen (watch a recorded run / check your own family): these tests drive the live flow
        if self.wait_screen("s-home", 5000):
            self.page.click("#toLive")

    def screen(self):
        return self.page.evaluate("() => (document.querySelector('.screen.on') || {}).id || ''")

    def wait_screen(self, ids, timeout=15000):
        ids = [ids] if isinstance(ids, str) else ids
        try:
            self.page.wait_for_function("ids => ids.includes((document.querySelector('.screen.on')||{}).id)",
                                        arg=ids, timeout=timeout)
            return True
        except Exception:
            return False

    def visible(self, sel):
        return self.page.evaluate("s => { const e = document.querySelector(s); return !!e && e.offsetParent !== null "
                                  "&& !e.classList.contains('hidden') && e.textContent.trim().length > 0; }", sel)

    def layout(self, label):
        r = self.page.evaluate("""() => {
          const vis = (el) => el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
          const small = [...document.querySelectorAll('.screen.on button, .screen.on a, #toggle button')].filter(vis)
            .filter(el => { const b = el.getBoundingClientRect(); return b.width < 44 || b.height < 44; })
            .map(el => (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 25));
          const clipped = [...document.querySelectorAll('.screen.on *')].filter(vis).filter(el =>
            el.children.length === 0 && el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible')
            .map(el => el.textContent.trim().slice(0, 25));
          const overflowing = [...document.querySelectorAll('.screen.on button, .screen.on .chip')].filter(vis)
            .filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.textContent.trim().slice(0, 25));
          // a button is only usable if a tap at its centre reaches it (nothing drawn on top of it)
          const covered = [...document.querySelectorAll('.screen.on button, #toggle button')].filter(vis).filter(el => {
            const b = el.getBoundingClientRect(); if (b.bottom < 0 || b.top > window.innerHeight) return false;
            const top = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
            return top && top !== el && !el.contains(top);
          }).map(el => (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 25));
          const blank = !document.querySelector('.screen.on') || document.querySelector('.screen.on').innerText.trim().length < 5;
          return { overflowX: document.documentElement.scrollWidth > window.innerWidth, small, clipped, overflowing, covered, blank };
        }""")
        for k in ("small", "clipped", "overflowing", "covered"):
            if r[k]:
                issue(self.scenario, f"layout-{k}", f"{label}: {r[k]}", self.page)
        if r["overflowX"]:
            issue(self.scenario, "layout-overflowX", label, self.page)
        if r["blank"]:
            issue(self.scenario, "blank-screen", label, self.page)

    def close(self, expect_bad=(), expect_net_errors=False):
        errs = [e for e in self.errors if "favicon" not in e
                # Chrome logs failed requests itself when the server is down / we are offline on purpose
                and not (expect_net_errors and ("net::ERR_" in e or "Failed to fetch" in e))]
        # ignore failures we caused on purpose (offline / killed server)
        bad = [b for b in self.bad if not any(x in b for x in expect_bad)]
        if errs:
            issue(self.scenario, "console-error", errs[:5])
        if bad:
            issue(self.scenario, "http-error", bad[:5])
        self.ctx.close()
        return not errs and not bad


def type_and_submit(s, text):
    if s.screen() != "s-type":
        s.page.click("#toType")
    s.page.fill("#typeBox", text)
    s.page.click("#typeGo")


def finish_followups(s, timeout=15000):
    """Answer any follow-ups by tapping the first option until the working screen appears."""
    end = time.time() + timeout / 1000
    while time.time() < end:
        scr = s.screen()
        if scr in ("s-work", "s-results"):
            return True
        if scr == "s-follow":
            try:
                s.page.locator("#qOptions .option").first.click(timeout=2000)
            except Exception:
                pass
        time.sleep(0.3)
    return False


def builder_family(s, lang):
    if s.screen() != "s-builder":
        s.page.click("#toBuilder")
    s.page.evaluate("() => document.querySelectorAll('#members .x').forEach(x => x.click())")   # start clean
    labels = {"hi": ["माँ", "पापा", "बेटी"], "en": ["Mother", "Father", "Daughter"]}[lang]
    for lab in labels:
        s.page.locator("#roleChips .chip", has_text=lab).first.click()
    tags = {"hi": ["विधवा", "किसान", "पढ़ाई"], "en": ["Widow", "Farmer", "Student"]}[lang]
    for i, t in enumerate(tags):
        s.page.locator("#members .member").nth(i).locator(".chip", has_text=t).click()


def to_results(s, scenario, label):
    if not finish_followups(s):
        issue(scenario, "hang", f"{label}: never reached the working screen (stuck on {s.screen()})", s.page)
        return False
    if not s.wait_screen("s-results", 30000):
        issue(scenario, "hang", f"{label}: working screen never finished (stuck on {s.screen()})", s.page)
        return False
    return True


# ------------------------------------------------------------------ scenarios
INPUTS = {
    "empty": "",
    "gibberish": "asdkjh qwe zzzpq lorem xx",
    "emoji-only": "👨‍👩‍👧😀🙏🌾",
    "2000-chars": ("मेरे पापा किसान हैं और माँ विधवा पेंशन के बारे में पूछना चाहती हैं। " * 40)[:2000],
    "hinglish": "mere papa kisan hain, 2 acre zameen hai, maa vidhwa hai, ek beti padhti hai",
    "numbers-only": "1234 5678 90",
}


def s_inputs(b):
    for lang in LANGS:
        for width in WIDTHS:
            for name, text in INPUTS.items():
                sc = f"input-{name}-{lang}-{width}"
                s = Session(b, sc, lang, width)
                s.wait_screen("s-start")
                type_and_submit(s, text)
                time.sleep(1.2)
                scr = s.screen()
                msg = s.visible("#startErr") or s.visible("#typeErr")
                if name in ("empty", "gibberish", "emoji-only", "numbers-only"):
                    # must not pretend to understand; must tell the person what to do
                    if scr in ("s-follow", "s-work", "s-results"):
                        issue(sc, "accepted-nonsense", f"moved on to {scr} without a family", s.page)
                    elif not msg:
                        issue(sc, "silent", f"no message shown (screen {scr})", s.page)
                else:
                    if not finish_followups(s):
                        issue(sc, "hang", f"valid input did not reach working (screen {scr}, msg={msg})", s.page)
                if width == 390:
                    s.layout(sc)
                if s.close(expect_bad=("/intake",) if name == "empty" else ()):
                    PASSES.append(sc)


def s_speech(b):
    for lang in LANGS:
        sc = f"mic-denied-{lang}"
        s = Session(b, sc, lang, 390, permissions=[])
        s.wait_screen("s-start")
        s.page.click("#mic")
        time.sleep(2.5)
        if not (s.screen() == "s-type" or s.visible("#heard")):
            issue(sc, "no-fallback", f"mic denied: nothing guides the user (screen {s.screen()})", s.page)
        if s.close():
            PASSES.append(sc)
        sc = f"no-speech-api-{lang}"
        s = Session(b, sc, lang, 390, extra_init=NO_SPEECH_API)
        s.wait_screen("s-start")
        s.page.click("#mic")
        time.sleep(0.8)
        if s.screen() != "s-type":
            issue(sc, "no-fallback", f"speech API missing: mic did not open typing (screen {s.screen()})", s.page)
        else:
            type_and_submit(s, INPUTS["hinglish"])
            if not finish_followups(s):
                issue(sc, "hang", "typing fallback did not continue", s.page)
        if s.close():
            PASSES.append(sc)


def s_rapid_taps(b):
    for lang in LANGS:
        sc = f"rapid-taps-{lang}"
        s = Session(b, sc, lang, 390)
        s.wait_screen("s-start")
        posted = []
        s.page.on("request", lambda r: posted.append((r.url, r.post_data)) if r.method == "POST" else None)
        # triple-tap start buttons
        s.page.click("#toBuilder", click_count=3)
        if s.screen() != "s-builder":
            issue(sc, "rapid", f"triple tap on 'or tap' -> {s.screen()}", s.page)
        # Next with no members
        s.page.click("#builderGo", force=True)
        time.sleep(0.4)
        if s.screen() != "s-builder":
            issue(sc, "no-members", f"Next with no members moved to {s.screen()}", s.page)
        elif not s.visible("#builderHint"):
            issue(sc, "no-members", "Next with no members: no hint shown (button does nothing)", s.page)
        builder_family(s, lang)
        s.page.click("#builderGo", click_count=3)
        if not s.wait_screen(["s-follow", "s-work"], 8000):
            issue(sc, "hang", "after builder Continue", s.page)
        intakes = [u for u, _ in posted if u.endswith("/intake")]
        if len(intakes) > 1:
            issue(sc, "double-submit", f"builder Continue sent {len(intakes)} intake requests", s.page)
        # triple-tap every follow-up option
        asked = 0
        while s.screen() == "s-follow" and asked < 3:
            asked += 1
            s.page.locator("#qOptions .option").first.click(click_count=3)
            time.sleep(0.5)
        answers = [d for u, d in posted if u.endswith("/answers")]
        if len(answers) > 1:
            issue(sc, "double-submit", f"follow-up answers sent {len(answers)} times", s.page)
        if answers:
            sent = json.loads(answers[0])["answers"]
            if len(sent) < asked:
                issue(sc, "skipped-question", f"triple tap answered {len(sent)} of {asked} questions: {sent}", s.page)
        if not s.wait_screen("s-results", 30000):
            issue(sc, "hang", "did not reach results", s.page)
        else:
            time.sleep(0.5)
            s.layout(sc + "-results")
            for sel in ["#sayHeadline", ".scheme .apply", ".scheme .speak"]:
                try:
                    s.page.locator(sel).first.click(click_count=3, timeout=5000)
                except Exception as e:
                    issue(sc, "untappable", f"{sel}: {str(e).splitlines()[-2][:120]}", s.page)
            if s.page.evaluate("() => window.__speaks") == 0:
                issue(sc, "dead-button", "🔊 buttons never spoke", s.page)
        if s.close():
            PASSES.append(sc)


def s_dead_buttons(b):
    """Every visible button on every screen must do something (screen change, DOM change, request or speech)."""
    for lang in LANGS:
        for target in ["s-start", "s-builder", "s-follow", "s-results"]:
            sc = f"dead-buttons-{target}-{lang}"
            probe = Session(b, sc, lang, 390)
            n = _reach(probe, target, lang)
            if n:
                probe.layout(f"{sc}-{target}")
            ids = probe.page.evaluate("""() => [...document.querySelectorAll('.screen.on button, #toggle button')]
                .filter(e => e.offsetParent !== null).map((e, i) => i)""")
            probe.close()
            for i in ids:
                s = Session(b, sc, lang, 390)
                if not _reach(s, target, lang):
                    s.close(); continue
                label = s.page.evaluate("i => { const e = [...document.querySelectorAll('.screen.on button, #toggle button')]"
                                        ".filter(e => e.offsetParent !== null)[i]; return e ? (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0,30) : null }", i)
                if label is None:
                    s.close(); continue
                before = s.page.evaluate("""() => { window.__mut = 0; new MutationObserver(m => window.__mut += m.length)
                    .observe(document.body, {subtree: true, childList: true, attributes: true, characterData: true});
                    return { screen: (document.querySelector('.screen.on')||{}).id, speaks: window.__speaks }; }""")
                reqs = []
                s.page.on("request", lambda r: reqs.append(r.url))
                s.page.evaluate("i => [...document.querySelectorAll('.screen.on button, #toggle button')]"
                                ".filter(e => e.offsetParent !== null)[i].click()", i)
                time.sleep(0.6)
                after = s.page.evaluate("() => ({ screen: (document.querySelector('.screen.on')||{}).id, speaks: window.__speaks, mut: window.__mut })")
                if after["screen"] == before["screen"] and after["speaks"] == before["speaks"] and after["mut"] == 0 and not reqs:
                    issue(sc, "dead-button", f"'{label}' did nothing on {target}", s.page)
                s.close(expect_bad=("/intake",))
            PASSES.append(sc)


def _reach(s, target, lang):
    s.wait_screen("s-start")
    if target == "s-start":
        return True
    if target == "s-builder":
        s.page.click("#toBuilder"); return s.wait_screen("s-builder")
    builder_family(s, lang)
    s.page.click("#builderGo")
    if target == "s-follow":
        return s.wait_screen("s-follow", 8000)
    return to_results(s, s.scenario, "reach results")


def s_ask_without_speech(b):
    for lang in LANGS:
        sc = f"ask-no-speech-api-{lang}"
        s = Session(b, sc, lang, 390, extra_init=NO_SPEECH_API)
        s.wait_screen("s-start")
        builder_family(s, lang); s.page.click("#builderGo")
        if to_results(s, sc, "reach results"):
            s.page.click("#askBtn")
            time.sleep(0.5)
            if s.screen() != "s-results" or not s.visible("#askSend"):
                issue(sc, "ask-fallback", f"'have a question' without speech API -> screen {s.screen()}, no text box", s.page)
            else:
                s.page.fill("#askText", "kya meri maa ko pension milegi?")
                s.page.click("#askSend")
                try:
                    s.page.wait_for_function("() => !document.querySelector('#answer').classList.contains('hidden')", timeout=8000)
                except Exception:
                    issue(sc, "ask-fallback", "typed question got no answer", s.page)
        if s.close():
            PASSES.append(sc)


def s_language_switch(b):
    for lang in LANGS:
        other = "en" if lang == "hi" else "hi"
        sc = f"lang-switch-{lang}"
        s = Session(b, sc, lang, 390)
        s.wait_screen("s-start")
        builder_family(s, lang)
        s.page.click("#builderGo")
        if s.wait_screen("s-follow", 8000):
            s.page.click(f"#toggle button[data-lang='{other}']")
            time.sleep(0.8)
            q = s.page.inner_text("#qText")
            is_hi = any("ऀ" <= ch <= "ॿ" for ch in q)
            if is_hi != (other == "hi"):
                issue(sc, "lang-switch", f"follow-up stayed in old language: {q!r}", s.page)
        finish_followups(s)
        s.page.click(f"#toggle button[data-lang='{lang}']")    # switch mid-run
        time.sleep(0.5)
        steps = s.page.inner_text("#steps") if s.screen() == "s-work" else ""
        if s.screen() == "s-work" and steps and (any("ऀ" <= ch <= "ॿ" for ch in steps) != (lang == "hi")):
            issue(sc, "lang-switch", f"working steps not re-rendered: {steps[:60]!r}", s.page)
        if not s.wait_screen("s-results", 30000):
            issue(sc, "hang", "results never shown after language switch", s.page)
        else:
            s.page.click(f"#toggle button[data-lang='{other}']")    # on results
            time.sleep(1.5)
            head = s.page.inner_text("#headB")
            if any("ऀ" <= ch <= "ॿ" for ch in head) != (other == "hi"):
                issue(sc, "lang-switch", f"results headline stayed in old language: {head!r}", s.page)
            s.layout(sc + "-results")
        if s.close():
            PASSES.append(sc)


def s_back_refresh(b):
    for lang in LANGS:
        sc = f"refresh-during-work-{lang}"
        httpx.post(BASE + "/stub/reset")                          # hold the fake run on the working screen
        s = Session(b, sc, lang, 390)
        builder_family(s, lang); s.page.click("#builderGo"); finish_followups(s)
        s.wait_screen("s-work", 8000)
        s.page.reload(wait_until="domcontentloaded")
        if not s.wait_screen(["s-work", "s-results"], 8000):
            issue(sc, "refresh", f"after refresh landed on {s.screen()}", s.page)
        httpx.post(BASE + "/stub/release")
        if not s.wait_screen("s-results", 30000):
            issue(sc, "hang", f"refresh during work: no results (screen {s.screen()})", s.page)
        if s.close():
            PASSES.append(sc)

        sc = f"back-during-work-{lang}"
        httpx.post(BASE + "/stub/reset")
        s = Session(b, sc, lang, 390)
        builder_family(s, lang); s.page.click("#builderGo"); finish_followups(s)
        s.wait_screen("s-work", 8000)
        s.page.go_back(wait_until="domcontentloaded")
        time.sleep(0.8)
        if s.page.url.startswith(BASE) and s.screen() not in ("s-work", "s-results"):
            issue(sc, "back", f"back button left the run: now on {s.screen()}", s.page)
        if not s.page.url.startswith(BASE):
            s.page.go_forward(wait_until="domcontentloaded")
        httpx.post(BASE + "/stub/release")
        if not s.wait_screen("s-results", 30000):
            issue(sc, "hang", f"back during work: no results (screen {s.screen()} url {s.page.url})", s.page)
        if s.close():
            PASSES.append(sc)


def s_server_kill(b):
    for lang in LANGS:
        sc = f"server-killed-{lang}"
        httpx.post(BASE + "/stub/reset")
        s = Session(b, sc, lang, 390)
        builder_family(s, lang); s.page.click("#builderGo"); finish_followups(s)
        s.wait_screen("s-work", 8000)
        kill_server()
        time.sleep(4)
        if not s.visible("#conn"):
            issue(sc, "silent-disconnect", "server down: no 'reconnecting' notice on the working screen", s.page)
        start_server()
        httpx.post(BASE + "/stub/release")
        if not s.wait_screen("s-results", 40000):
            issue(sc, "hang", f"after server restart: no results (screen {s.screen()})", s.page)
        elif s.visible("#conn"):
            issue(sc, "stale-notice", "reconnecting notice still shown on results", s.page)
        if s.close(expect_bad=("127.0.0.1",), expect_net_errors=True):
            PASSES.append(sc)


def s_network(b):
    for lang in LANGS:
        sc = f"slow-3g-{lang}"
        s = Session(b, sc, lang, 390)
        cdp = s.ctx.new_cdp_session(s.page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 400,
                                                      "downloadThroughput": 400 * 1024 / 8, "uploadThroughput": 400 * 1024 / 8})
        s.page.reload(wait_until="domcontentloaded")
        s.wait_screen("s-start", 20000)
        builder_family(s, lang); s.page.click("#builderGo")
        if not to_results(s, sc, "slow 3G"):
            pass
        if s.close():
            PASSES.append(sc)

        sc = f"offline-{lang}"
        s = Session(b, sc, lang, 390)
        s.wait_screen("s-start")
        s.ctx.set_offline(True)
        builder_family(s, lang); s.page.click("#builderGo")
        time.sleep(1.5)
        if not (s.visible("#startErr") or s.visible("#builderHint") or s.visible("#conn")):
            issue(sc, "offline", f"offline submit: no message (screen {s.screen()})", s.page)
        s.ctx.set_offline(False)
        if s.screen() != "s-builder":            # recover: try again
            builder_family(s, lang)
        s.page.click("#builderGo")
        if not to_results(s, sc, "after coming back online"):
            pass
        if s.close(expect_bad=("127.0.0.1",), expect_net_errors=True):
            PASSES.append(sc)


async def _one_session(client, i):
    t = time.time()
    hid = (await client.post(f"{BASE}/api/households", json={"lang": "hi" if i % 2 else "en"})).json()["id"]
    b = {"members": [{"role": "mother", "tags": ["widow"]}, {"role": "father", "tags": ["farmer"]}], "income": "low"}
    r = (await client.post(f"{BASE}/api/households/{hid}/intake", json={"lang": "en", "builder": b})).json()
    if r["followups"]:
        await client.post(f"{BASE}/api/households/{hid}/answers",
                          json={"lang": "en", "answers": {f["id"]: f["options"][0]["value"] for f in r["followups"]}})
    for _ in range(240):
        d = (await client.get(f"{BASE}/api/households/{hid}?lang={'hi' if i % 2 else 'en'}")).json()
        if d["run"] and d["run"]["status"] in ("done", "failed"):
            return {"ok": d["run"]["status"] == "done" and bool(d["result"]), "secs": round(time.time() - t, 1),
                    "status": d["run"]["status"]}
        await asyncio.sleep(0.5)
    return {"ok": False, "secs": round(time.time() - t, 1), "status": "timeout"}


def s_concurrency():
    sc = "concurrent-25"
    httpx.post(BASE + "/stub/release")

    async def go():
        async with httpx.AsyncClient(timeout=30) as c:
            return await asyncio.gather(*[_one_session(c, i) for i in range(25)], return_exceptions=True)
    res = asyncio.run(go())
    bad = [r for r in res if isinstance(r, Exception) or not r["ok"]]
    secs = [r["secs"] for r in res if isinstance(r, dict)]
    summary = f"{25 - len(bad)}/25 completed; time min/max {min(secs or [0])}s/{max(secs or [0])}s"
    if bad:
        issue(sc, "concurrency", f"{summary}; failures: {[str(x)[:80] for x in bad[:5]]}")
    else:
        PASSES.append(f"{sc}: {summary}")
    return summary


# ------------------------------------------------------------------ main
def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".png"):
            os.remove(os.path.join(OUT, f))
    start_server()
    t0 = time.time()
    conc = None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            for fn in (s_inputs, s_speech, s_rapid_taps, s_dead_buttons, s_ask_without_speech, s_language_switch, s_back_refresh,
                       s_server_kill, s_network):
                try:
                    fn(b)
                except Exception as e:
                    issue(fn.__name__, "test-crash", f"{type(e).__name__}: {str(e)[:300]}")
            b.close()
        conc = s_concurrency()
    finally:
        kill_server()
    report = {"seconds": round(time.time() - t0), "issues": ISSUES, "passed": PASSES, "concurrency": conc}
    json.dump(report, open(os.path.join(OUT, "report.json"), "w"), indent=1, ensure_ascii=False)
    print(f"\n{len(PASSES)} scenarios clean, {len(ISSUES)} issues ({report['seconds']}s)")
    by = {}
    for i in ISSUES:
        by.setdefault(i["kind"], []).append(i)
    for k, v in by.items():
        print(f"\n[{k}] x{len(v)}")
        for i in v[:6]:
            print(f"   {i['scenario']}: {str(i['detail'])[:160]}")
    print("\nconcurrency:", conc)
    return 1 if ISSUES else 0


if __name__ == "__main__":
    sys.exit(main())
