# Haq — Test Report (2026-10-11)

This report covers two phases of testing:

- **Phase 1** was free. It checked every link the app can show and stress-tested the UI against the stub server, with no model or web-search calls.
- **Phase 2** made real Anthropic API calls through the real app server, under a hard total cap of $2.

Raw data:

| File | Contents |
|---|---|
| `docs/stress/links.txt` and `links.json` | link check results |
| `docs/stress/report.json` | UI stress test results |
| `docs/stress/live-results.json` | real API runs |
| `docs/stress/live-results-links.json` | links on the real results screens |

Scripts: `scripts/check_links.py`, `scripts/stress_ui.py`, `scripts/live_test.py` and `scripts/ui_stub_server.py`.

---

## Phase 1A — Links (free)

**What was checked:** every URL the app can show. That covers the catalog (official, rules-document and fallback URLs), the cached scheme rules, cards in saved results (after the display-link fixes), the evals source URLs, and links in `static/index.html` and the stub.

**How each URL was checked:**

1. A real GET request with a browser user-agent, a 15-second timeout, one retry, and redirects followed.
2. If that failed, the URL was re-checked in **real Chrome**.
3. Every myScheme page was also rendered. myScheme returns HTTP 200 for any URL, even when the page shows "Page not found".

**What was broken (as a family's browser sees it) and what replaced it.** Each replacement is an official page that was verified in Chrome by its title and text.

| Broken URL | Problem | Replaced by |
|---|---|---|
| pmjay.gov.in | times out | beneficiary.nha.gov.in |
| nsap.nic.in | DNS failure | nsap.dord.gov.in |
| pmayg.nic.in | DNS failure | pmayg.dord.gov.in |
| abhyuday.up.gov.in | connection refused | samajkalyan.up.gov.in (the UP Social Welfare department, which runs Abhyudaya; the page does not name the scheme) |
| old.financialservices.gov.in/…PMJJBY | DNS failure | financialservices.gov.in/pradhan-mantri-jeevan-jyoti-bima-yojana-pmjjby |
| financialservices.gov.in/beta/…pmsby | certificate name mismatch | financialservices.gov.in/pradhan-mantri-suraksha-bima-yojana-pmsby |
| pmkmy.gov.in | certificate name mismatch | pmkisan.gov.in |
| sspy-up.gov.in | certificate warning in browsers | per scheme: mahilakalyan.up.nic.in (widow), divyangjan.upsdc.gov.in (disability), samajkalyan.up.gov.in (old age) |
| myscheme …/ab-pmjay, …/abpmjayvv | "Page not found" | beneficiary.nha.gov.in |
| myscheme …/oaps-up | "Page not found" | samajkalyan.up.gov.in |
| myscheme …/pmkmy | "Page not found" | pmkisan.gov.in |
| myscheme …/pmsym | "Page not found" | maandhan.in |
| myscheme …/mksy | **wrong scheme** (Mukhyamantri *Kisan Sahay* Yojana) | mksy.up.gov.in |
| myscheme …/pmvs | **wrong scheme** (PM-*Vidyalaxmi*) | pmvishwakarma.gov.in |

**Result:** 60 of 60 links load in Chrome.

Thirteen links still fail Python's strict TLS check. They are all missing an intermediate certificate (one has the legacy-renegotiation problem). Browsers handle these, so families are not affected.

**How the fixes are applied:**

- **Display:** `catalog.display_link()` maps known-broken URLs on every card. It also covers results saved earlier.
- **Fetching:** dead hosts were removed from the fetch lists.
- **Cache:** the cached rules were rewritten.
- **Evals:** `evals/families.json` keeps each evidence URL, because that is where the rule text was read. 13 items gained a `browser_url`. Expected answers did not change; the file was verified identical apart from the added fields.

## Phase 1B — UI stress (free)

**Setup:** Playwright with real Chrome, against the stub server, in both languages, at widths of 360, 390 and 768 px.

**What was covered:**

- inputs: empty, gibberish, emoji only, 2,000 characters, Hinglish, numbers only
- microphone permission denied
- speech API missing
- double and triple taps on every button
- "Continue" with no family members
- a sweep for buttons that do nothing
- a hit-test that every visible button is tappable, i.e. not covered by another element
- switching language mid-run and on results
- the back button and refresh during the working screen
- the server killed mid-run, then restarted
- slow 3G, and going offline then back online
- 25 concurrent sessions

**What broke and was fixed:**

| Found | Fix |
|---|---|
| Gibberish, emoji-only and numbers-only text was accepted with **no family**, and the app went on to ask follow-up questions (18 cases) | The intake step returns `need_more`, and the UI asks again or offers the tap builder |
| Empty typed input did nothing, with no message | A hint is shown |
| "Continue" with no members did nothing (dead button) | A hint is shown |
| With the server killed mid-run, the working screen froze silently | A "Connection lost — reconnecting…" notice appears, and the screen resumes when the server is back |
| The headline 🔊 button was **covered by the headline text**: taps hit the text and nothing was read aloud | Fixed with `z-index` and padding. The test now hit-tests every button |
| "Have a question?" without the speech API jumped to the *start* typing screen and sent the question as a new family | It has its own typed fallback on the results screen |
| A blocked microphone fell through to "didn't catch that" | The UI switches to typing and shows a message |
| Double or triple taps could send twice, and could skip a follow-up question | One request per action. A tap answers exactly one question |
| Requests failing while offline showed a generic error | An "offline" message is shown |
| A long text was sent to the model in full | Text is capped at 3,000 characters on the server |
| 25 concurrent sessions took about 33 s each, because the state file was re-parsed on every poll | The state is parsed once per process. Sessions now take 17–23 s |

**Final run:** last complete run 65/65 scenarios clean, 0 issues, 25/25 concurrent sessions (17.5–22.9 s). A re-run covering the new one-time and pension display is pending and will be added here.

## Phase 2 — Real API (hard cap $2)

**Setup:** the real app server was driven over HTTP, making the same calls the browser makes. Each scenario got a fresh server whose `HAQ_BUDGET_USD` was set to the remaining budget minus a safety margin. That server refuses any model call once the cap is reached. Every model call is counted, including intake extraction and translation.

**Total spent: $1.52 of $2.00.**

| # | Run | Status | Time | Cost | neatlogs trace ID (session) |
|---|---|---|---|---|---|
| 1 | Hindi tap builder: mother is a widow, father is a farmer, daughter is a student, low income | ✅ done | 48 s | $0.245 | `7ad95bd365bfdb0f4c49652228f19c2d` (`8936735b31`) |
| 2 | English typed family with a disabled 72-year-old grandfather | ✅ done | 75 s | $0.243 | `86f478b4537648b5e25dd329456e6391` (`3860bdfa10`) |
| 3 | Same as run 1 with `SIMULATE_FAILURE=1` and the cache off | ✅ done | 88 s | $0.457 | `28204345122d65f99265fd532cb580c2` (`b850d82182`) |
| 4a | Concurrent: tap builder (English) | stopped at its server cap, then **resumed → ✅ done** | 39 s + 19 s | $0.182 + resume | `f26e7f92c01357d7969673ff0dd3995f`, `28f03054bdf0a11cd098e6244f1b575d` (`2021a924e6`) |
| 4b | Concurrent: typed (English) | stopped at its server cap, then **resumed → ✅ done** | 45 s + 46 s | $0.207 + resume | `dbc896599795be0b097f18b9231887c6`, `83c01b7d25f3cd36d20ad44ae35929a2` (`df30875aaf`) |
| 4c | Concurrent: typed (Hindi), a widow aged 74 | ✅ done | 33 s | $0.119 | `8a345750c8713575224289c188bca376` (`aa820aab3e`) |

The two resumed runs cost $0.061 together, because the rules cache meant very little work was redone.

**Schemes found** (as returned by each run):

- **Run 1.**
  - Confirmed: PM-KISAN (father), Kanya Sumangala (daughter), PMFBY (father), e-Shram (mother, father).
  - Check needed: PMAY-G (area, house), widow pension (income limit), Ujjwala (income limit, LPG), PM-JAY (income limit).
  - Protection: PMSBY, PMJJBY.
- **Run 2.**
  - Confirmed: PMAY-G, Ayushman Vay Vandana (father), PM-SYM, e-Shram.
  - Check needed: old-age pension, disability pension, PM-KISAN, Ujjwala, PM-JAY.
  - Protection: PMSBY, PMJJBY.
- **Run 3.**
  - Confirmed: PM-KISAN, Kanya Sumangala, UP scholarship (daughter), PMFBY, PM-SYM.
  - Check needed: PMAY-G, widow pension, Ujjwala, e-Shram.
- **Run 4c.**
  - Confirmed: PMAY-G, Ujjwala, Ayushman Vay Vandana.
  - Check needed: widow pension, old-age pension, PM-JAY.

**Links on the real results screens:** 24 of 24 load in Chrome (`docs/stress/live-results-links.json`).

### What the real runs exposed, and the fixes

1. **One-time grants were counted as money per year** (this broke the "honest headline" rule).
   - PMAY-G's ₹1.2 lakh house grant, Ujjwala's ₹2,050 gas connection and Kanya Sumangala's stage payments were all added to "/year". Run 1 showed "up to **₹1,52,050/year**".
   - **Fix:** `catalog.ONE_TIME` sets these schemes apart. They appear as a separate line ("+ ₹X one-time help (not every year)"), and each card says "one-time".
   - Run 1 now reads: **up to ₹18,000/year** (₹6,000 confirmed and ₹12,000 after checks), plus ₹1,34,050 of one-time help.
2. **The same person was counted for two pensions** (run 4c: widow pension plus old-age pension).
   - In UP a person gets one social pension at a time.
   - **Fix:** only one pension is counted per person, and the card explains why.
3. **PM-KISAN was shown for a landless labourer** (run 2), with "check income limit" only.
   - **Fix:** any eligibility fact that is still unknown, such as land, is now added to "check needed", including in results saved earlier.
4. **The simulated failure (run 3) hit PM-JAY.** The retry and fallback both ran, but every official PM-JAY page is JavaScript-only, so nothing was readable and PM-JAY was correctly dropped rather than shown unverified.
   - Root cause found: **pib.gov.in returns 403 to the fetcher's bot user-agent** but serves browsers normally.
   - **Fix:** after a 401, 403 or 429, the fetcher retries once with a browser user-agent, and records that in the recovery log. A readable official PIB release was added as a PM-JAY fallback.
   - **Verified for free** at fetch level (no model calls). The same simulated failure now recovers: NHA (forced failure) → NHA (JavaScript-only) → beneficiary portal (JavaScript-only) → PIB (403, then retried with a browser user-agent ✓).
   - Other run-3 lookups recovered in the real run, e.g. PM-KISAN went from myScheme (JavaScript-only) to pmkisan.gov.in ✓.
   - A real re-run of scenario 3 (about $0.46 with the cache off) was **not** done, because it would have pushed the total past $2.
5. **Concurrency.** Three real runs at once produced no rate-limit errors and no shared-state errors.
   - Two runs hit their server's spending cap (my safety margin was conservative). They failed cleanly with "resume to retry" and later resumed to completion. That also tests resuming in the real API path.

## Still open

- **PMMVY suggested without a pregnancy.** In run 4b, PMMVY (the maternity scheme) was shown as "check needed" for a wife whose pregnancy was never mentioned. Pregnancy should become an unknown fact that is flagged, or the scheme should not be planned.
- **Results vary between runs of the same family.** Run 2 and resumed run 4b show slightly different scheme sets. This is model non-determinism.
- **Scenario 3 has not been re-run.** The fixed recovery path is proven at fetch level only.
- **Abhyudaya link.** The fallback is the department homepage, not a scheme page. abhyuday.up.gov.in is down.
- **UP pension portal.** sspy-up.gov.in, the real application portal, shows a certificate warning in browsers. Families are sent to the department pages instead.
- **Expected answers.** Every expected answer in the eval set is still marked `needs_human_check`.
- **Scale.** The state file is a single JSON file rewritten on every change. That is fine for a demo but not for production.
