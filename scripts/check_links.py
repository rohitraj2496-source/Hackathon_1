"""Check every URL Haq can show a family: catalog official/rules/fallback URLs, cached scheme rules,
saved results (official source + where-to-apply), evals/families.json sources, the stub's demo cards
and links in static/index.html.

    .venv/bin/python scripts/check_links.py [--json out.json]

Real GET with a browser user-agent, 15s timeout, 1 retry, redirects followed. No model calls.
Status: OK | redirect (lands on another URL, still loads) | 404 | timeout | blocked (403/401/429,
connection refused, DNS failure) | tls_error | error (other HTTP status).
"""
import argparse
import glob
import json
import os
import re
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("NEATLOGS_API_KEY", "")
from haq import catalog  # noqa: E402

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Mobile Safari/537.36")


def collect() -> dict[str, set[str]]:
    urls: dict[str, set[str]] = {}

    def add(u, src):
        if isinstance(u, str) and u.startswith("http"):
            urls.setdefault(u.strip(), set()).add(src)

    for s in catalog.SCHEMES:
        for k in ("official_urls", "rules_docs", "fallback_urls"):
            for u in s.get(k, []):
                add(catalog.display_link(u, s["id"]), f"catalog:{s['id']}:{k}")
        add(s.get("display_url"), f"catalog:{s['id']}:display_url")
    for p in glob.glob(os.path.join(ROOT, "data/cache/rules/*.json")):
        r = json.load(open(p, encoding="utf-8"))
        add(r.get("official_url"), f"rules-cache:{r['scheme_id']}")
        add(r.get("apply_url"), f"rules-cache:{r['scheme_id']}:apply")
        for rule in r.get("rules", []):
            add(rule.get("official_url"), f"rules-cache:{r['scheme_id']}:rule")
    for p in glob.glob(os.path.join(ROOT, "data/*state*.json")):
        try:
            hh = json.load(open(p, encoding="utf-8")).get("households", {})
        except Exception:
            continue
        for h in hh.values():
            for run in h.get("runs", []):
                for c in ((run.get("result") or {}).get("cards") or []):
                    # what the results screen shows (after the display-link fixes)
                    add(catalog.display_link(c.get("official_url"), c["scheme_id"]), f"results-screen:{c['scheme_id']}")
                    add(catalog.display_link(c.get("apply_url"), c["scheme_id"]), f"results-screen:{c['scheme_id']}:apply")
    fam = json.load(open(os.path.join(ROOT, "evals/families.json"), encoding="utf-8"))
    for h in fam["households"]:
        for e in h["expected"]:
            # evidence URL (where the rule was read) is kept as-is; browser_url is what a person should open
            add(e.get("browser_url") or e.get("official_source_url"), f"evals:{h['id']}:{e['scheme_id']}")
    for p in ["static/index.html", "scripts/ui_stub_server.py"]:
        for u in re.findall(r"https?://[^\s\"'<>)]+", open(os.path.join(ROOT, p), encoding="utf-8").read()):
            if "fonts.g" in u or "w3.org" in u or "127.0.0.1" in u:
                continue
            add(u.rstrip(".,;"), p)
    return urls


def _client(verify=True, legacy=False):
    ctx = ssl.create_default_context()
    if legacy:
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return httpx.Client(timeout=15.0, follow_redirects=True, verify=ctx,
                        headers={"User-Agent": UA, "Accept-Language": "hi,en;q=0.8"})


def check(url: str) -> dict:
    last = None
    for attempt in (1, 2):                      # 1 retry
        try:
            with _client() as c:
                r = c.get(url)
            final = str(r.url)
            if r.status_code == 404:
                return {"status": "404", "code": 404, "final": final}
            if r.status_code in (401, 403, 429):
                last = {"status": "blocked", "code": r.status_code, "final": final}
                continue
            if r.status_code >= 400:
                last = {"status": "error", "code": r.status_code, "final": final}
                continue
            moved = final.rstrip("/").lower() != url.rstrip("/").lower()
            return {"status": "redirect" if moved else "OK", "code": r.status_code, "final": final}
        except httpx.TimeoutException:
            last = {"status": "timeout", "code": None, "final": None}
        except httpx.ConnectError as e:
            msg = str(e)
            if "CERTIFICATE" in msg.upper() or "SSL" in msg.upper():
                last = {"status": "tls_error", "code": None, "final": None, "detail": msg[:120]}
            else:
                last = {"status": "blocked", "code": None, "final": None, "detail": msg[:120]}
        except httpx.HTTPError as e:
            last = {"status": "error", "code": None, "final": None, "detail": f"{type(e).__name__}: {e}"[:120]}
    # A real browser tolerates some old TLS setups that strict Python refuses; record whether it loads that way.
    if last and last["status"] == "tls_error":
        try:
            with _client(verify=False, legacy=True) as c:
                r = c.get(url)
            last["loads_with_lenient_tls"] = r.status_code < 400
        except Exception:
            last["loads_with_lenient_tls"] = False
    return last


def browser_check(urls: list[str]) -> dict[str, dict]:
    """What a family's browser sees: load in real Chrome; myScheme pages must not render 'Page not found'."""
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        for u in urls:
            ctx = b.new_context(user_agent=UA)
            page = ctx.new_page()
            res = {"browser": "FAIL", "detail": ""}
            for _ in (1, 2):
                try:
                    r = page.goto(u, timeout=15000, wait_until="domcontentloaded")
                    if "myscheme.gov.in/schemes/" in u:
                        try:
                            page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                    title = page.title()
                    if "not found" in title.lower() or page.url.rstrip("/").endswith("/404"):
                        res = {"browser": "FAIL", "detail": f"renders 'Page not found' ({page.url})"}
                    elif r and r.status >= 400 and "pdf" not in (r.headers.get("content-type") or ""):
                        res = {"browser": "FAIL", "detail": f"HTTP {r.status}: {title[:50]}"}
                    else:
                        res = {"browser": "OK", "detail": title[:60]}
                    break
                except Exception as e:
                    res = {"browser": "FAIL", "detail": str(e).splitlines()[0][:100]}
            out[u] = res
            ctx.close()
        b.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--no-browser", action="store_true", help="skip the real-Chrome re-check")
    args = ap.parse_args()
    urls = collect()
    with ThreadPoolExecutor(12) as pool:
        results = dict(zip(urls, pool.map(check, urls)))
    if not args.no_browser:
        recheck = [u for u, r in results.items() if r["status"] != "OK" or "myscheme.gov.in/schemes/" in u]
        for u, br in browser_check(recheck).items():
            results[u].update(br)
    for u, r in results.items():
        r["final_verdict"] = r.get("browser", "OK" if r["status"] in ("OK", "redirect") else "FAIL")
    rows = sorted(({"url": u, **r, "sources": sorted(urls[u])} for u, r in results.items()),
                  key=lambda r: (r["final_verdict"] == "OK", r["status"] == "OK", r["status"], r["url"]))
    for r in rows:
        print(f"{r['final_verdict']:5} {r['status']:9} {str(r.get('code') or ''):4} {r['url']}"
              + (f"  [browser: {r.get('detail', '')}]" if "browser" in r else "")
              + (f"  -> {r['final']}" if r["status"] == "redirect" else "")
              + (f"  [{r.get('detail', '')}]" if r.get("detail") and "browser" not in r else "")
              + (f"  (lenient TLS: {'loads' if r.get('loads_with_lenient_tls') else 'no'})" if "loads_with_lenient_tls" in r else ""))
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("final (as a family's browser sees it):",
          {v: sum(1 for r in rows if r["final_verdict"] == v) for v in ("OK", "FAIL")})
    print("\n", counts, f"total {len(rows)}")
    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        json.dump(rows, open(args.json, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
