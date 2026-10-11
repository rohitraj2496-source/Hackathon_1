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

## UI screenshots (no API calls)

Phone-size (390×844) screenshots of every screen in Hindi and English are in
[`docs/screenshots/`](docs/screenshots/), along with an automated layout report (`layout-report.json`). The
report checks for horizontal overflow, clipped text, off-screen buttons, and tap targets under 44px. To
regenerate the screenshots, run against the stub server, which fakes the agent (including a website failure
and its recovery) and makes no model or web calls:

```bash
.venv/bin/python scripts/ui_stub_server.py &                 # http://127.0.0.1:8001
npm install --prefix /tmp/haq-shots puppeteer-core@23.11.1   # uses your installed Chrome
NODE_PATH=/tmp/haq-shots/node_modules node scripts/screenshots.js
```

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
- **cost** is computed from token usage (per-model rates in `haq/config.py`, including cache reads and writes) plus web-search requests

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
   with a reason. This is enforced: when web search returned non-government pages, the finishing tool must
   list each one it looked at with a verdict (`agrees`, `conflicts` or `not_on_official_source`). Conflicts go
   to `conflicts`, and claims found only off-government go to `unofficial_claims`. Neither is ever used as a
   confirmed rule.
5. **Recover** (`haq/fetcher.py`) retries each official URL 3 times with exponential backoff. Old state
   portals get one adaptation each, recorded in the log: legacy TLS renegotiation (scholarship.up.gov.in), and
   no certificate check for expired certificates (sspy-up.gov.in). Both are safe here because the pages are
   public and only read. If the URL still fails, Haq moves on to the scheme's official rule documents (PDF
   guidelines or niyamawali, whose text is extracted with pypdf) and then to its other official URLs. Every
   attempt is recorded in `recovery_log`. With `SIMULATE_FAILURE=1` the first lookup fails on purpose.
6. **Write** (`agent.write`) builds the card JSON and the headline total, then has Claude write a short spoken
   Hindi summary. Schemes the family already receives are shown but left out of the total. Health and
   insurance cover is shown on its own card but not added to the ₹/year figure.

**Follow-ups:** the browser remembers the household ID, so a family that comes back sees its results. They can
ask a question by voice. If they report a change, such as a new baby, a death or new land, Haq updates the
profile and runs the search again.

## Cache (cost control)

`haq/cache.py` keeps two on-disk caches under `data/cache/` (gitignored):

- **pages/**: the text of every official page or PDF Haq has fetched, kept for 7 days
  (`HAQ_PAGE_CACHE_DAYS`). A repeat fetch costs nothing and takes milliseconds.
- **rules/**: each scheme's eligibility rules as confirmed on official pages, with their source URLs, kept
  for 30 days (`HAQ_RULES_CACHE_DAYS`). The next lookup of that scheme, for any member of any family, starts
  from these rules and does not search the web again. Its cited official URLs count as already read. Only
  scheme-level rules are stored, never family data. A confirmed record is never replaced by a "likely" one.

Research runs one loop per scheme for each family, and that loop decides every planned member of the family
together (for example, PMSBY for the father, mother and son in one loop, not three). `python -m haq.cache seed data/eval-state.json`
imports rules from runs that have already been paid for. Set `HAQ_NO_CACHE=1` to bypass both caches, for
example to demo `SIMULATE_FAILURE` on a cold start.

**Prompt caching.** Each research request sends its system prompt as two cached blocks. The first holds the
shared instructions; because tools render before system, the tools are cached together with them, and this
block is shared by every scheme. The second holds the scheme's catalog note and cached official rules, and is
shared by every member and every family checked for that scheme. The family profile goes last, after both
breakpoints. Top-level automatic caching covers the growing tool loop. One-shot calls (interview, plan,
summary) cache only their system prompt.

**Models.** Sonnet is used only for eligibility verification (`HAQ_VERIFY_MODEL`). Haiku handles the
interview, planning, the summary and follow-ups (`HAQ_FAST_MODEL`). Each scheme lookup gets at most 2 web
searches, and none when cached rules exist. The lookup stops as soon as an official page confirms the
rules. Sonnet runs at `low` effort when it only has to apply fully confirmed cached rules, and at
`medium` when it has to research, or when an income limit is still unconfirmed.

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

All spans for one family share `session_id = household id`.

**Trace IDs are saved with every result.**

- Each run records `traces` in the state file and in the API response (`GET /api/households/{id}` → `run.traces`).
  Each entry holds the OpenTelemetry `trace_id` and `span_id` (hex), the span name, the workflow and the
  `session_id`. A resumed run adds one entry per attempt.
- Interview turns and follow-ups carry a `trace` entry on their message.
- In eval results, every household is its own root trace. Its IDs are in `households[].neatlogs`, along with the
  run traces inside it. The suite trace id is at the top level, under `neatlogs.suite_trace_id`. Eval runs are traced under the workflow name
`haq-evals`, with one `eval:<id>` root per household.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required |
| `NEATLOGS_API_KEY` | — | required for traces to be exported |
| `HAQ_VERIFY_MODEL` | `claude-sonnet-5-5` | eligibility verification (the research loops). `HAQ_MODEL` is still accepted |
| `HAQ_FAST_MODEL` | `claude-haiku-5-5` | interview, planning, spoken summary, follow-ups |
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
