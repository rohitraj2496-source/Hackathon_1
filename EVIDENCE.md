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
| Cost per household | $0.93 (≈ ₹82) | **$0.22 (≈ ₹20)** |
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

The **neatlogs trace IDs (OpenTelemetry trace ids) were not recorded at run time**, so they are not listed here.
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

## 5. Caveats

- **Expected answers are unchecked.** Every expected answer is still marked `needs_human_check: true` and has not
  been spot-checked by a person.
- **Not every household is covered.** Only the 9 baseline-error households were re-run. h08 and h11–h20 have not
  been run on the current code (estimated at about $0.22 each).
- **Some figures are assumptions.** Haiku's cache prices (0.1x / 1.25x of input) and the ₹88/USD rate are assumed.
- **Times are not perfectly comparable.** The two h09 runs used 1 worker, while the baseline and the batch of 8
  used 4 workers.
