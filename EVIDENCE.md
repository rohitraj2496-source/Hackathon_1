# Evidence: Haq before vs after

This file shows what changed between the first eval run (the baseline) and the current code, and the evidence
behind each change. Every number below comes from the committed results files in `evals/`. No expected answer in
`evals/families.json` has been changed since it was created in
[`893473d`](https://github.com/rohitraj2496-source/Hackathon_1/commit/893473de9dda7fca0b87d8f9e44382bc841218c2).

| Run | Results file | Households | Setup |
|---|---|---|---|
| **Baseline** | `evals/results-20261010-160806.json` | h01–h10 | Sonnet 5.5 for every step, no cache, 4 workers |
| After: smoke test, warm cache | `evals/results-20261010-171541.json` | h09 | current code, 1 worker |
| After: warm cache | `evals/results-20261010-171810.json` | h01–h07, h10 | current code, 4 workers |
| After: cold cache | `evals/results-20261010-172025.json` | h09 | current code, `HAQ_NO_CACHE=1`, 1 worker |

## 1. Before vs after

These are the **9 households that had a wrong or missed scheme in the baseline**: h01–h07, h09 and h10. h08 was
fully correct in the baseline and was not re-run. The "after" column uses the warm-cache h09 run and the batch of
8. Rupee amounts use an assumed rate of ₹88 per US dollar.

| Metric | Baseline | After |
|---|---|---|
| Accuracy (TP / (TP + FP + FN)) | 0.50 | **0.86** |
| Precision | 0.71 | **0.97** |
| Recall | 0.64 | **0.89** |
| Wrong schemes (FP) | 8 | **1** |
| Missed schemes (FN) | 10 | **3** |
| Cost per household | $0.93 (≈ ₹82) | **$0.22 (≈ ₹20)** average; ₹20–40 per family in test runs, depending on family size and cache |
| Total cost for 9 households | $8.35 (≈ ₹735) | **$2.00 (≈ ₹176)** |
| Time per household | 147 s | **59 s** |

Per household:

| Household | Baseline: wrong / missed | After: wrong / missed | After: cost |
|---|---|---|---|
| h01 | nfsa_ration, up_shadi_anudan / up_scholarship | — / — | $0.270 |
| h02 | up_shadi_anudan / up_widow_pension, pmjay, pmay_g | — / — | $0.239 |
| h03 | nfsa_ration / — | — / — | $0.073 |
| h04 | nfsa_ration / — | — / — | $0.185 |
| h05 | — / up_bocw, nfsa_ration | pm_vishwakarma / up_bocw, pmuy | $0.205 |
| h06 | nfsa_ration / up_scholarship | — / up_kanya_sumangala | $0.337 |
| h07 | — / nfsa_ration, pmay_g | — / — | $0.353 |
| h09 | nfsa_ration / — | — / — | $0.112 |
| h10 | nfsa_ration / up_scholarship | — / — | $0.226 |

Known remaining errors:

- **h05, wrong scheme:** PM Vishwakarma for a construction worker. This is arguably defensible, because masons
  are one of the scheme's trades, but it is not in the expected list.
- **h05, missed schemes:** UP BOCW and Ujjwala.
- **h06, missed scheme:** Kanya Sumangala.

## 2. Likely eligible vs confirmed

A scheme is labelled **"Likely eligible — confirm income limit"** when its core eligibility (who the scheme is
for) is confirmed on an official page but the income limit is not. Likely schemes are shown on the cards with that
label and are not counted in the confirmed ₹ total.

| Group | Number of predictions | Expected answer | Optional extra | Wrong |
|---|---|---|---|---|
| Likely eligible | 15 | 13 | 2 | **0** |
| Confirmed | 44 | 15 | 28 (mostly the PMSBY, PMJJBY, PM-SYM and e-Shram insurance and pension products) | 1 (h05 PM Vishwakarma) |

| Metric (same 9 households) | All predictions | Confirmed only |
|---|---|---|
| Accuracy | 0.86 | 0.52 |
| Precision | 0.97 | 0.94 |
| Recall | 0.89 | 0.54 |

The likely group is mostly the widow and old-age pensions, PM-JAY, UP scholarships and the ration card. For these
schemes the official portals confirm who qualifies but do not publish the income limit.

## 3. Warm vs cold cache (h09, same household)

| | Warm cache | Cold cache (`HAQ_NO_CACHE=1`) |
|---|---|---|
| Cost | **$0.112** (≈ ₹10) | $0.241 (≈ ₹21) |
| Time | 47 s | 122 s |
| Score | 4/4, 0 wrong | 4/4, 0 wrong |
| Sonnet calls / cost | 6 / $0.111 | 14 / $0.240 |
| Haiku calls / cost | 2 / $0.001 | 2 / $0.001 |
| Web searches | 0 | 3 |
| Sonnet tokens read from cache / written to cache | 5,656 / 18,018 | 200,637 / 27,646 |

What this shows:

- **Haiku structured outputs work.** The interview, plan and summary steps all returned valid structured output.
- **Prompt caching works on both models.** In the cold run, the Haiku plan step read 2,646 cached tokens that the
  warm run had written a few minutes earlier.
- **Where the warm-cache rules came from.** The warm cache holds rules for 19 schemes. They were imported, with no
  new API calls, from baseline lookups that had already been paid for (`python -m haq.cache seed`).

## 4. Fixes, commits and the evidence for each

### About the neatlogs trace identifiers

The **neatlogs trace IDs (OpenTelemetry trace ids) were not recorded at run time for the runs below**, so they are
not listed here. Runs from commit [`6eea250`](https://github.com/rohitraj2496-source/Hackathon_1/commit/6eea2509b40f980a6df660f5db029b22c7936eda) onward record them: see `households[].neatlogs.trace_id` in the
results files.
Each bug below is identified instead by three things, which together are enough to find the trace in the neatlogs
dashboard:

- the **trace name**, for example `eval:h03`, in workflow `haq-evals`
- the **span name**, for example `research:nfsa_ration:household`
- the **session id**, which is the household id

| Run | Session ids (household ids) |
|---|---|
| Baseline | h01 `1d89d89faa`, h02 `f7de572297`, h03 `eee3110444`, h04 `531b815edb`, h05 `656e07dcc6`, h06 `819b1ae51c`, h07 `cf70fbe6c8`, h08 `b45c4ae89e`, h09 `f4980ec823`, h10 `391532689f` |
| Aborted re-run, before fixes 6–7 | h01 `b0a76752da`, h02 `0dc8661720`, h03 `9621321743`, h04 `0a706b5470` |
| Manual test household (workflow `haq`) | `1039c7bd51` |

### Accuracy fixes

| # | Fix | Commit | Evidence (neatlogs trace / span / session) |
|---|---|---|---|
| 1 | Don't recommend a ration card to families that already hold one | [`658fe54`](https://github.com/rohitraj2496-source/Hackathon_1/commit/658fe5471f83970aa72a3b5b973c04fdf76a834d) | `eval:h01`, `eval:h03`, `eval:h04`, `eval:h06`, `eval:h09`, `eval:h10`. Span `research:nfsa_ration:household` ended in `record_verified` even though the profile already had an Antyodaya or eligible-household card. This caused 6 of the 8 baseline wrong schemes. Sessions are the baseline ids above. |
| 2 | Marriage grants only when a marriage is actually coming up | [`bddd5d9`](https://github.com/rohitraj2496-source/Hackathon_1/commit/bddd5d9921cba320f156cc74ee776b920680f192) | `eval:h01` (`1d89d89faa`) and `eval:h02` (`f7de572297`). Span `research:up_shadi_anudan:daughter` recorded the scheme for girls aged 12 and 7. The same bug appeared in the manual test `1039c7bd51` (daughter aged 13). |
| 3 | "Likely eligible — confirm income limit" instead of dropping the scheme | [`5baa497`](https://github.com/rohitraj2496-source/Hackathon_1/commit/5baa497f20a3adc52b65900e1652a09dd7dc32c8) | `eval:h02` (`f7de572297`): `research:up_widow_pension:self` was dropped although sspy-up.gov.in confirmed "widow, 18+". `eval:h06` (`819b1ae51c`) and `eval:h10` (`391532689f`): `research:up_scholarship:*` was dropped because the income limit appeared only on buddy4study. |
| 4 | Read official rule PDFs and the legacy-TLS state portals | [`30fbc1f`](https://github.com/rohitraj2496-source/Hackathon_1/commit/30fbc1f7bf0e83dd8c521ac5fcf156f2a8d269b8) | `eval:h01`, `eval:h06`, `eval:h10`: the `fetch_url_with_retry` spans for scholarship.up.gov.in failed 3 out of 3 times with `SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED`. This caused all 4 scholarship misses. `eval:h02` and `eval:h07` (`cf70fbe6c8`): `research:pmay_g:household` found only the portal home page, while the rules are in the guidelines PDF. |
| 5 | Actually record conflicts when non-government sources are read | [`6b33c05`](https://github.com/rohitraj2496-source/Hackathon_1/commit/6b33c05af8d6d35f64e17f402a3ad8ea04f5348e) | The baseline logged 0 conflicts. Meanwhile `eval:h06` relied on buddy4study, `eval:h07` on kotak811 and bajajfinserv, and `eval:h02` on private sites for PM-JAY. After the fix, 8 unofficial claims were logged and none were used as a rule. |
| 6 | Tolerate stringified tool arrays; stop hung runs after a fatal API error | [`d0acca4`](https://github.com/rohitraj2496-source/Hackathon_1/commit/d0acca40ac86b96d7c25d1007c7f71a4f66d64c9) | Aborted re-run, `eval:h03` (`9621321743`): `research:ayushman_vay_vandana:self` raised `TypeError: string indices must be integers`. Aborted re-run, `eval:h01`, `eval:h02`, `eval:h04` (`b0a76752da`, `0dc8661720`, `0a706b5470`): runs stayed `running` for 30+ minutes because a `CancelledError` escaped `except Exception`. This commit contains both fixes. |
| 7 | Bound every network wait (API client timeout, fetch deadline) | [`c4f4f2e`](https://github.com/rohitraj2496-source/Hackathon_1/commit/c4f4f2efe12f8f55bee38c4567039ff63370fefb) | Same aborted re-run, `eval:h01`, `eval:h02`, `eval:h04`: research spans stayed open for 30+ minutes. Neither the API client nor page downloads had a total time limit. |
| — | Don't save failed lookups, so a resume retries them | [`4e86960`](https://github.com/rohitraj2496-source/Hackathon_1/commit/4e8696050afa474788a837f47544d44ecc9eb524) | Manual test `1039c7bd51` (workflow `haq`): 4 candidates were saved as "dropped" with a billing error as the reason. |

### Cost fixes

The evidence for these is the baseline token profile (results file `20261010-160806`):

- **$4.92 of the $9.23 (53%) was cache writes** of web-search results.
- There were **121 scheme lookups for only 24 distinct schemes**. PMSBY was looked up 19 times and PMJJBY 15 times.

| # | Change | Commit |
|---|---|---|
| C1 | Cache official pages (7 days) and verified scheme rules (30 days) on disk | [`0138493`](https://github.com/rohitraj2496-source/Hackathon_1/commit/0138493ca10acfad6e25333ff5a3d0a2b8f7c890) |
| C2 | Haiku for the interview, plan, summary and follow-ups; Sonnet only for verification | [`9c0ecf2`](https://github.com/rohitraj2496-source/Hackathon_1/commit/9c0ecf27199f6ab612c30a63abec34cf2e266546) |
| C3 | At most 2 web searches per scheme; stop once an official page confirms the rules | [`52498bf`](https://github.com/rohitraj2496-source/Hackathon_1/commit/52498bf2c082d0d33ffe16b44204eec4a857ae48) |
| C4 | Prompt caching for the system prompt and scheme rules | [`bc74be2`](https://github.com/rohitraj2496-source/Hackathon_1/commit/bc74be23cffc31f93b9873cf07f86de6c98677ae) |
| C5 | One research loop per scheme that decides all of a family's members together. Evidence: `eval:h01` and `eval:h04` ran PMSBY and PMJJBY loops separately for each of 3–4 members. | [`2ebc2d4`](https://github.com/rohitraj2496-source/Hackathon_1/commit/2ebc2d48de468418902c45bdb7f82826cc48ce35) |
| C6 | Low Sonnet effort when it only has to apply fully confirmed cached rules | [`fb5d8f0`](https://github.com/rohitraj2496-source/Hackathon_1/commit/fb5d8f0a89bb837cc0735b39cd30778d06421995) |
| C7 | Report usage and cost per model | [`3b0ec4c`](https://github.com/rohitraj2496-source/Hackathon_1/commit/3b0ec4cb3baaa6927e54287c01e7277afd5e16dd) |

The baseline results are in [`52fbe91`](https://github.com/rohitraj2496-source/Hackathon_1/commit/52fbe910c6e9f955cdfec25a8a5a588bf5b71f45)
and the after results are in [`5faa21b`](https://github.com/rohitraj2496-source/Hackathon_1/commit/5faa21b80b556584c0ff75e33bd81aa31445e22c).

## Business plan (made with cfo.ai)

The plan is a 24-month forecast, from Nov 2026 (month 1) to Oct 2028 (month 24), built in cfo.ai. Every number below is read from the exported workbooks in [`docs/businessplan/`](docs/businessplan/) (see its [README](docs/businessplan/README.md)). All three scenarios start with ₹25,00,000 of cash.

**Business rule.** Citizens never pay (the citizen price is ₹0) and Haq never takes a cut of any benefit (the benefit commission rate is 0, marked "hard business rule"). Haq is paid by CSC operators, CSR programmes and employers.

### Scenarios

| | Main | Conservative | Growth |
|---|---|---|---|
| Sustained break-even month | **Month 16 (Feb 2028)** | **None within 24 months** (cash first goes negative in month 11, Sep 2027) | **Month 10 (Aug 2027)** |
| Minimum cash | ₹8,10,268 (month 11) | **−₹24,67,217** | ₹14,00,843 |
| Additional funding needed | ₹0 | **₹24,67,217** | ₹0 |
| Funding needed to keep a ₹10 lakh safety reserve | ₹1,89,732 | **₹34,67,217** | ₹0 |
| Extra CSC acquisition spend (above the marketing budget) | ₹12,27,536 | ₹50,000 | ₹1,22,10,692 |
| CSC growth / churn per month | 20% / 5% | 10% / 7% | 30% / 3% |
| CSR district contracts by month 24 | 8 | 4 (half-sized) | 16 |
| Employer workers by month 24 | 50,000 | 25,000 | 1,00,000 |
| AI cost reaches ₹4 per check from | month 10 | month 25 (outside the forecast, so it stays at ₹10) | month 6 |

### Gross margin per check (unit economics by customer type)

In this table, a "check" is one family search. "Margin" is the contribution after AI cost, hosting (₹0.01 per check) and the 2% collection fee.

| Customer | Price | Revenue per check | Margin at ₹20 AI cost (**measured**, uncached) | Margin at ₹10 AI cost (**measured**, cached) | Margin at ₹4 AI cost (**target**, not measured) |
|---|---|---|---|---|---|
| **CSC** operator | ₹1,499/month for 100 checks, then ₹15 per extra check | ₹18.74 (at 80 checks a month) | **−8.7%** (−₹1.64) | 44.6% (₹8.36), CAC payback 3.0 months | 76.7% (₹14.36), CAC payback 1.7 months |
| **CSR** district | ₹5,00,000 per district per year for 25,000 checks | ₹20.00 | **−2.0%** (−₹0.40) | 48.0% (₹9.60) | 78.0% (₹15.60) |
| **Employer** | ₹50 per worker per year (1 check per worker) | ₹50.00 | 58.0% (₹29) | 78.0% (₹39) | 90.0% (₹45) |

- **CSC price used:** ₹1,499 per month in **all three scenarios**. This was checked in the exports: CSC revenue ÷ operators = ₹1,499 in every month of every scenario. The plan assumes 80 checks per operator against 100 included, so no extra-check revenue is booked.
- **CSC break-even AI cost:** CSC is profitable only while the AI cost stays below ₹18.35 per check on average, or ₹14.68 with the full check allowance used.
- **Break-even month by AI cost (Main):**
  - At ₹4: month 16, 13 or 5.
  - At ₹10: month 24, 17 or 11.
  - At **₹20: never** within the forecast.
  - The three values in each row are for 100 / 300 / 1,000 **CSC operators at month 12**.

### Where the per-check costs come from

**Measured cost: ₹20–40 per family in test runs, depending on family size and cache** (one-person families with a warm cache measured about ₹10). The plan's per-check costs of ₹20 (uncached) and ₹10 (cached) are **MEASURED** from neatlogs-traced runs, and the plan marks them MEASURED. **₹4 per check is a TARGET**, not yet measured.

The runs recorded in this repo, converted at ₹88/$:

| Run | Cost | neatlogs trace / session |
|---|---|---|
| One-person family, uncached | **₹21.2** | session `0d677a7b06` |
| One-person family, cached | **₹9.8** and **₹10.4** | sessions `cca0218304`; trace `8a345750c8713575224289c188bca376` |
| Three-member families, cached | ₹21.4 to ₹21.6 (8-household average ₹20.8) | traces `7ad95bd365bfdb0f4c49652228f19c2d`, `86f478b4537648b5e25dd329456e6391` |
| Three-member family, uncached | **₹40.2** | trace `28204345122d65f99265fd532cb580c2` |

So the plan's flat ₹20 and ₹10 match **one-person** households. It was ₹20–40 per family in test runs, depending on family size and cache (see the risks below).

### Key risky assumptions

1. **AI cost falls to ₹4 per check from month 10.** This is a target. At ₹20 per check, the low end of the ₹20–40 per family in test runs, depending on family size and cache, the plan never breaks even, and CSC and CSR checks lose money. The Conservative case, which stays at ₹10, needs ₹24.7 lakh of extra funding.
2. **The plan's flat ₹20 and ₹10 assume a one-person household.** It was ₹20–40 per family in test runs, depending on family size and cache: three-member families measured ₹21 (cached) to ₹40 (uncached). The plan sheet also notes these numbers are user-reported and not independently audited.
3. **100% annual renewal** for CSR and employer contracts, paid **upfront with no collection delay**.
4. **CSC growth of 20% a month gross with 5% churn**, from 50 operators at launch (month 4) to 818 by month 24. Growth needs ₹1.22 crore of extra acquisition spend at ₹2,000 per operator.
5. **CSR contracts at ₹5 lakh per district per year**, used fully (25,000 checks), ramping from 1 to 8 districts. **Employer contracts** grow from 10,000 to 50,000 workers at ₹50 per worker. None of these are signed.
6. **A lean team.** One developer from month 1, a field lead from month 6, and founder pay from month 7. The whole ₹50,000 monthly marketing budget is assumed to offset CSC acquisition cost.

## 5. Caveats

- **Expected answers are unchecked.** Every expected answer is still marked `needs_human_check: true` and has not
  been spot-checked by a person.
- **Not every household is covered.** Only the 9 baseline-error households were re-run. h08 and h11–h20 have not
  been run on the current code (estimated at about $0.22 each).
- **Some figures are assumptions.** Haiku's cache prices (0.1x / 1.25x of input) and the ₹88/USD rate are assumed.
- **Times are not perfectly comparable.** The two h09 runs used 1 worker, while the baseline and the batch of 8
  used 4 workers.
