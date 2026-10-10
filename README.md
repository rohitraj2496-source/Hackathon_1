# Haq (हक़)

**Haq finds the government schemes a whole family is entitled to, and how much money they are missing each year.**

It is built for people who can't read. Haq asks short questions in Hindi by voice, researches central and
Uttar Pradesh schemes on official government websites, checks every eligibility rule against an official
page, and reads the result aloud. Each result is a large card showing the scheme, the ₹ per year, which family
member it is for, the documents needed, where to apply, and a link to the official source.

Scope for the hackathon: **central government schemes and Uttar Pradesh state schemes only.** The goal is to
cover these well rather than cover everything.

---

## Quick start

```bash
# 1. Python 3.10–3.13 (neatlogs does not support 3.14 yet)
uv venv -p 3.12 .venv            # or: python3.12 -m venv .venv
uv pip install -p .venv -r requirements.txt

# 2. Keys
cp .env.example .env             # then fill in ANTHROPIC_API_KEY and NEATLOGS_API_KEY

# 3. Run the app
.venv/bin/uvicorn app:app --port 8000
# open http://localhost:8000  (use Chrome/Edge for the Hindi mic; Safari/Firefox fall back to the text box)
```

Demo of the recovery path: `SIMULATE_FAILURE=1 .venv/bin/uvicorn app:app --port 8000` makes the first lookup of
an official page fail on purpose. You can then watch Haq retry with backoff and fall back to another official
source. The recovery appears in the progress bar ("🔁 … बार दूसरी सरकारी साइट से जाँचा"), in the run state,
and in the neatlogs trace.

## Running the evals

```bash
.venv/bin/python run_evals.py                  # all 20 households, 3 in parallel
.venv/bin/python run_evals.py --only h02,h09   # a subset
SIMULATE_FAILURE=1 .venv/bin/python run_evals.py
```

The script runs Haq on each household in `evals/families.json`, giving it the profile directly (no voice and
no interview). It prints precision, recall, F1, overall accuracy, average cost and average time, and saves
everything to `evals/results-<timestamp>.json`. That file includes per-household predictions, misses, false
positives, the verified source URLs, dropped schemes with reasons, conflicts and recoveries. On each run it also
prints the change from the previous results file, so you can compare before and after a change.

### How scoring works

Scoring compares schemes per household.

| Outcome | Rule |
|---|---|
| **TP** | An expected scheme that Haq verified. If the item has an `any_of` list, any scheme in that list counts (for example, UP allows only one social pension per person, so a 74-year-old widow can be given either the widow pension or the old-age pension). |
| **FN** | An expected scheme that Haq did not verify. |
| **FP** | A scheme Haq verified that is neither expected nor listed in `acceptable_extra`. |

- **precision** = matched predictions / (matched + FP)
- **recall** = TP / (TP + FN)
- **accuracy** = TP / (TP + FP + FN), a Jaccard score across all households
- **cost** is computed from token usage (Claude Opus 5.5 rates, including cache reads and writes) plus web-search requests

`acceptable_extra` holds schemes that are plausible but optional: insurance and contributory products
(PMJJBY, PMSBY, PM-SYM, e-Shram, PMFBY), and schemes whose eligibility depends on facts the profile doesn't
contain. Haq is not penalised for predicting these, and not penalised for missing them.

### The eval set: `evals/families.json`

There are 20 households across UP: small farmers, young and elderly widows, students (school, college, OBC and
SC), elderly couples, a 70+ member, members with disabilities, construction, brick-kiln and daily-wage workers,
artisans (a tailor and a potter), a street vendor, mixed joint families, and some negative cases:

- an income-tax-paying farmer, where PM-KISAN is excluded
- a family with 3 children, where Kanya Sumangala is excluded
- a pregnancy with a second child, where PMMVY does not apply
- a divorced (not widowed) mother, where the widow pension does not apply

Every expected scheme includes `official_source_url` and `rule_basis`, and is marked
**`"needs_human_check": true`**. These answers were written from the official portals (pmkisan.gov.in,
sspy-up.gov.in, mksy.up.gov.in, pmuy.gov.in, shadianudan.upsdc.gov.in, …). Several portals are JavaScript-only
or have expired certificates, so please spot-check the items before trusting the numbers.

---

## How the agent works

```
INTERVIEW ──► PLAN ──► RESEARCH ─► VERIFY ──► WRITE
 (Hindi,      (candidate   (one agent loop per    (cards JSON +
  voice)       schemes per   scheme × member,       spoken Hindi
               member)       in parallel)           summary)
                               │
                               └─ RECOVER: retry + backoff → other official URL
```

1. **Interview** (`agent.interview_turn`) asks one short Hindi question at a time and builds a structured
   household profile: members, ages, gender, occupation, land, income, ration card, house type, gas
   connection, and widow, disability, student and pregnancy status. It **never asks about caste** and only
   records it if the family offers it. It stops once it has enough information, usually after 6–10 questions.
2. **Plan** (`agent.plan`) lists candidate schemes for each member from the catalog in `haq/catalog.py`, which
   holds 25 central and UP schemes with their official starting URLs. Haq can also add a relevant scheme that
   is missing from the catalog.
3. **Research** (`agent.research_one`) runs a separate Claude tool-use loop for each candidate, with these tools:
   - `web_search`, a server tool that prefers `*.gov.in`, `*.nic.in` and `myscheme.gov.in`
   - `fetch_official_page`, a client tool that refuses non-official domains
   - `log_conflict`
   - `record_verified` or `drop_scheme`, one of which ends the loop
4. **Verify.** `record_verified` is checked in code, not just by the prompt. The call is rejected unless every
   rule in `rules_checked` cites an official URL that the agent actually read in that loop, either fetched
   directly or returned in its own search results. Anything that can't be confirmed officially is dropped. When
   an unofficial source disagrees with an official one, the official source wins and the conflict is logged
   with a reason.
5. **Recover** (`haq/fetcher.py`) retries each official URL 3 times with exponential backoff. If the TLS
   certificate has expired (sspy-up.gov.in, for example), it retries once without certificate checks, which is
   read-only and public, and records that it did. If the URL still fails, it moves on to the scheme's other
   official URLs. Every attempt is recorded in `recovery_log`. With `SIMULATE_FAILURE=1` the first lookup fails
   on purpose.
6. **Write** (`agent.write`) builds the card JSON and the headline total, then has Claude write a short spoken
   Hindi summary. Schemes the family already receives are shown but left out of the total. Health and
   insurance cover is shown on its own card but not added to the ₹/year figure.

**Follow-ups:** the browser remembers the household ID, so a family that comes back sees its results. They can
ask a question by voice. If they report a change, such as a new baby, a death or new land, Haq updates the
profile and runs the search again.

## State and resume

`data/state.json` (or `HAQ_STATE_FILE`) holds every household's profile, interview transcript and runs. Each
run records its stage, candidates, per-scheme research records, conflicts, recovery log, usage and cost, and
result. The file is rewritten atomically after every step. If the process crashes, the next server start
resumes any run still marked `running`, skipping schemes that were already researched. You can also resume
manually with `POST /api/households/{id}/run`. The evals use a separate `data/eval-state.json`.

## Tracing (neatlogs)

`haq/config.py` calls `neatlogs.init()` and wraps the Anthropic client with `neatlogs.wrap()`, so **every LLM
call** is an LLM span. Agent steps are spans as well:

| Span | Kind |
|---|---|
| `haq_run` | WORKFLOW |
| `interview_turn` | AGENT |
| `plan` | CHAIN |
| `research:<scheme>:<member>` | AGENT |
| `write` | CHAIN |
| `followup` | AGENT |
| `tool:<name>` for each tool call | TOOL |
| `fetch_official_page` / `fetch_url_with_retry` for every fetch attempt | TOOL |

All spans for one family share `session_id = household id`. Eval runs are traced under the workflow name
`haq-evals`, with one `eval:<id>` root per household.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required |
| `NEATLOGS_API_KEY` | — | required for traces to be exported |
| `HAQ_MODEL` | `claude-opus-5-5` | Claude model |
| `HAQ_EFFORT` | `medium` | default effort (the interview and summary use `low`) |
| `SIMULATE_FAILURE` | off | `1` makes the first official lookup fail |
| `HAQ_STATE_FILE` | `data/state.json` | where profiles and runs are stored |

Requests enable Anthropic's server-side refusal fallback (`fallbacks: "default"`). If a request is declined,
it is retried on a fallback model inside the same call.

## Project layout

```
app.py              FastAPI server (API + static frontend, resumes crashed runs)
static/index.html   single-page, voice-first Hindi UI
haq/agent.py        interview, plan, research/verify loops, write, follow-ups, orchestrator
haq/fetcher.py      official-page fetch with retry/backoff/fallback + SIMULATE_FAILURE
haq/catalog.py      central + UP scheme catalog and official-domain check
haq/state.py        JSON-file persistence
haq/llm.py          Claude call helper + cost accounting
haq/config.py       .env, neatlogs init, wrapped Anthropic client, prices
evals/families.json 20 UP test households with official-source expected answers
run_evals.py        eval runner and scorer
```

> Haq gives guidance, not a legal decision. Final eligibility is decided by the department when the family
> applies.
