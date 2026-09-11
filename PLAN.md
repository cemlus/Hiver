# Hiver SDE Intern Assignment — Final Build Plan (v3)

> v3 (2026-09-11). Adds: current codebase state after Phase 0, the environment repair and Gemini
> changes that made the smoke test pass, a migration procedure from `/mnt/c` to the Linux
> filesystem, and plan deviations/lessons learned. Phases 1–12 are otherwise the approved v2 plan.

## Context
Hiver's take-home asks for an AI support agent for **one brand** from the Kaggle *Customer Support on Twitter* dataset. The agent must (1) classify intent into a taxonomy derived from the data, (2) draft a reply grounded in the brand's historical replies, (3) decide auto-handle vs escalate with a stated reason. The graded part is the **proof**: a hand-labelled golden set (150–250), an eval harness with an LLM judge validated against human grades, ≥2 baselines, top-5 failure analysis, a "What is misleading about my headline number?" section, and a 10–15 item decision log. The README must reproduce headline results in **<15 min**. Submission: repo link + report via the Notion form in the brief.

The user is moving the project from the Windows drive (`/mnt/c/Users/HP/Desktop/Projects/Hiver`) into the WSL Linux filesystem. `/mnt/c` made the venv install take 28.5 minutes and live LLM calls take 50–80 s to start. This document is the single hand-off: what exists, how to move it, and what's left to build.

**User constraints (binding):**
- Provider-agnostic LLM layer (LiteLLM). Current provider: **Gemini**, chosen by the user. 3–4 day timeline; Phase 0 used Day 1.
- **LangGraph orchestrates; business logic stays framework-independent Python.** No LangGraph imports in `src/core`.
- **PostgreSQL / Redis / Slack / other integrations are optional adapters** that can never block the evaluation pipeline.
- **Clustering is an exploratory aid only.** The human-authored codebook is the source of truth for intents.
- **LLM silver labels and heuristic outcome labels are weak supervision**, stored and named as such, never ground truth.
- **Strict train / dev / frozen-golden separation**, enforced in code and tests.
- **Typed `SupportRequest`, `AgentState`, `AgentOutput` contracts come before any agent code.**
- Work **phase by phase**. After each phase, explain what was built and check in before starting the next.

**Guiding rule:** ~30% effort on the agent, ~70% on data, evaluation and writing. Keep code plain and explainable, because the user will be asked to modify it live.

---

## 1. Current state (verified 2026-09-10/11, before migration)

**Phase 0 is complete. All exit criteria are met.**

| Check | Result |
|---|---|
| `uv sync --locked --dry-run` | "Would make no changes" (env == `uv.lock`) |
| `import openai` / `import litellm` | 2.54.0 / 1.100.1 (match lock) |
| `python -m src.llm "Reply with the single word: ok"` | `[gemini/gemini-2.5-flash] ok` (82 s live, mostly startup) |
| Judge via `build_deps('eval').judge_llm` | `[gemini/gemini-3.5-flash] ok` (50 s live) |
| Same smoke with `LLM_OFFLINE=1` | `ok` in 1 s from cache, no network |
| `pytest` | **11/11 pass** |
| Raw data | `data/raw/twcs.csv` present, 493 MB |

Git: `git init -b main` done, `core.filemode=false`, `core.autocrlf=input`. **No commits yet.** Everything is untracked.

### 1.1 Codebase inventory (what each file does)

| File | Contents |
|---|---|
| `pyproject.toml` | Python `>=3.11,<3.13`. Core deps: pandas, pyarrow, numpy, scikit-learn, sentence-transformers, torch, litellm, langgraph, pydantic≥2.7, pyyaml, python-dotenv, tqdm, matplotlib, pytest. Extras: `integrations` (psycopg, redis, slack_sdk, fastapi, uvicorn, langsmith), `data` (kaggle). CPU-only torch via a `[tool.uv.sources]` + `pytorch-cpu` index (non-macOS). `[tool.pytest.ini_options] pythonpath=["."]`, `testpaths=["tests"]`. No build-system (uv "virtual" project). |
| `uv.lock` | 138 packages resolved. Key pins: litellm 1.100.1, openai 2.54.0, langgraph 1.2.11, pydantic 2.13.5, torch 2.14.0+cpu, sentence-transformers 6.0.1, transformers 5.17.0, pandas 3.0.5, scikit-learn 1.9.0, pytest 9.1.1. |
| `.python-version` | `3.11` (uv-managed CPython 3.11.15). |
| `config.yaml` | `brand: null`, `seed: 42`, `codebook_version: v1`. `models.agent = {name: gemini/gemini-2.5-flash, temperature: 0, max_tokens: 1024}`. `models.judge = {name: gemini/gemini-3.5-flash, temperature: null, max_tokens: 4096}` (comment: switch to `gemini/gemini-2.5-pro` once billing is enabled). `embedding_model: sentence-transformers/all-MiniLM-L6-v2`. `data.{raw_csv, records, split_date: null}`, `retrieval.k: 5`, `thresholds.{intent_confidence: 0.6, retrieval_similarity: 0.5}` (placeholders), `cache.path: data/cache/llm_cache.sqlite`, `results_store.path: results/runtime_outputs.jsonl`, `integrations: {store: jsonl, cache: sqlite, escalation_sink: none}`. |
| `.env` (gitignored) | Defines `GEMINI_API_KEY` (plus `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` lines and `LLM_OFFLINE=0`). |
| `.env.example` | Commented key templates, `LLM_OFFLINE=0`, commented `KAGGLE_USERNAME/KAGGLE_KEY`. |
| `.gitignore` | `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ipynb_checkpoints/`, `.env`, `data/raw/*` (except `.gitkeep`), `*.pdf`. |
| `Makefile` | `setup` (uv sync), `test`, `llm-smoke`, `data` (kaggle download via `uv run --extra data --env-file .env`); `sample taxonomy index eval report` are stubs. `make` is not installed; every target is one command you can run directly. |
| `README.md` | Overview, quickstart, provider switching, repo map, phase checklist (Phase 0 ticked), citations. |
| `DECISIONS.md` | 6 `[P0]` entries: LiteLLM; schema-in-prompt JSON; cache-everything + committed cache; ports & adapters; uv + lock + CPU torch; local embeddings. |
| `src/config.py` | `load_config(path=None)` (lru-cached; loads `.env`, then `config.yaml`), `resolve(rel)` → absolute path, `ROOT`. |
| `src/ports/protocols.py` | `LLMClient` (`model`, `complete(prompt, *, system=None, schema=None) -> str \| T`), `Cache` (`get/set(meta=)`), `ResultStore.save(record)`, `EscalationSink.notify(output)`. |
| `src/ports/defaults.py` | `SQLiteCache` (thread-locked, table `cache(key, value, meta, created_at)`, `__len__`), `JsonlResultStore`, `NullSink`, `LogSink`. Stdlib only. |
| `src/ports/factory.py` | `Deps(profile, agent_llm, judge_llm, store, sink)`. `build_deps(profile="eval"\|"runtime", config=None)`: eval → SQLite cache, `store=None`, `NullSink` regardless of config. runtime → honours `integrations` via `_optional(module, attr, fallback, cfg)`, which lazy-imports `src.integrations.*` and falls back with a warning on any error. Warns if judge == agent model. |
| `src/llm/client.py` | `LiteLLMClient(model, cache, *, temperature=None, max_tokens=1024)`. `complete()`: schema → JSON-schema instructions appended to the prompt, validated with pydantic via outermost `{...}` (tolerates fences), one cached retry, else `LLMOutputError`. `_cached_call`: key = `cache_key(model, system, prompt, {max_tokens, temperature})` (sha256). `LLM_OFFLINE=1` → `CacheMissError` on a miss. `_call`: **lazy `import litellm`**, `num_retries=3`, temperature only sent if not None. |
| `src/llm/__main__.py` | Smoke: `python -m src.llm "prompt"` → prints `[model] reply` using `build_deps("eval").agent_llm`. |
| `src/{contracts,core,orchestration,integrations,dataprep,eval}/__init__.py` | Docstrings stating each package's role and its rules (e.g. core must not import langgraph). |
| `tests/test_llm_client.py` | 7 tests with a scripted fake `_call`: cache hit, cache persists across instances, per-model keys, offline serve/miss, fenced-JSON parse, retry once, fail after retry. |
| `tests/test_ports.py` | 4 tests: eval profile ignores integrations, runtime falls back when adapters are missing, judge==agent warns, importing the LLM layer loads no optional/heavy modules (incl. litellm), checked in a subprocess. |
| `data/cache/llm_cache.sqlite` | 2 rows (the smoke prompt for `gemini-2.5-flash` and for `gemini-3.5-flash`). Will be committed. |
| Empty dirs with `.gitkeep` | `data/{raw,processed,golden,cache}`, `prompts/`, `results/`, `notebooks/`. |

### 1.2 What happened on the way to a passing smoke test (for the record / DECISIONS.md)
1. **Interrupted `uv sync`** (stopped mid-install) left `openai` half-copied, so `ModuleNotFoundError: No module named 'openai._utils'`. A later interrupted sync then wiped `site-packages` entirely. **Fix:** `uv sync --locked` (recreated the env exactly from the lock; `pyproject.toml`/`uv.lock` untouched).
2. **Gemini 1.5 models are retired.** `gemini-1.5-flash` returned 404 NOT_FOUND. **Fix:** agent → `gemini/gemini-2.5-flash`.
3. **Pro models have free-tier limit 0.** `gemini-2.5-pro`, `gemini-pro-latest`, `gemini-3.1-pro-preview` all return 429 RESOURCE_EXHAUSTED. **Fix:** judge → `gemini/gemini-3.5-flash` (works on the free tier, different model from the agent). Upgrade to `gemini-2.5-pro` when billing is enabled.
4. The key is valid; 40 models support `generateContent`.
5. **Incomplete move and a second half-installed venv (2026-09-11).** The Linux copy landed at `/home/siddhant/Hiver`. It had 11 half-installed dists (pandas, scipy, pydantic, …), yet `uv sync --locked --dry-run` still said "Would make no changes", because it compares metadata, not files. The copy had also skipped `.gitignore`, `DECISIONS.md` and the brief PDF, and carried an empty LLM cache. **Fix:** copied the missing files and the 2-row cache from `/mnt/c`, then ran `rm -rf .venv && uv sync --locked` (0.6 s from the local uv cache). Baseline re-verified: 11/11 tests, offline replay of both smoke rows.

### 1.2b Phase 0 audit (2026-09-11), all fixed with tests (11 → 16)
- **C1** An exported `LLM_OFFLINE=1` made all 7 LLM-client tests fail. Fix: an autouse fixture in `tests/conftest.py`.
- **C2** Empty replies were cached forever (Gemini thinking can use all of `max_tokens`). Fix: `LLMEmptyReplyError`, never cached, plus a per-role `reasoning_effort` in config, which is part of the cache key only when set.
- **C3** The retry prompt embedded pydantic's versioned help URL, so cache keys depended on the pydantic version. Fix: `_describe()`.
- **C4** LiteLLM's default timeout is 6000 s. Fix: a per-role `timeout` (agent 60 s, judge 120 s).
- **C5, C7** `uv sync --locked` in the README and Makefile; `load_config()` returns a deep copy.
- **C6 (not applied)** `.gitignore` entries for `results/runtime_outputs.jsonl` and `*.sqlite-journal` were added, then reverted on disk. The `.gitignore` is kept as it is. Revisit before Phase 8/12, when the runtime profile starts writing that file.

### 1.3 Deviations from the v2 plan (intentional)
- `pyproject.toml` + `uv.lock` + extras instead of `requirements.txt` / `requirements-optional.txt`. **Phase 11:** also export `requirements.txt` (`uv export --no-hashes > requirements.txt`) for pip users.
- `config.yaml` models are nested per role (`name`, `temperature`, `max_tokens`). `temperature: null` = don't send it (some models reject it).
- Added `src/config.py` and `results_store.path`.
- Judge is Flash-tier, same vendor as the agent → weaker judge and possible family-level bias. Record this in the report's "misleading" section, and switch to a Pro judge if billing is enabled.

### 1.4 Gotchas learned (read before running commands)
- **Never interrupt `uv sync`.** Installs aren't atomic. Repair any broken env with `rm -rf .venv && uv sync --locked`.
- **`uv sync --locked --dry-run` can't see a half-installed venv**: it checks metadata, not files. After any interrupted install, run the import check: `uv run python -c "import pandas, scipy, pydantic, litellm, openai, torch, sentence_transformers, langgraph, sklearn"`.
- **LiteLLM's default request timeout is 6000 s.** Every call uses `models.<role>.timeout` instead.
- **Empty replies raise `LLMEmptyReplyError`** and are never cached. If one appears, raise `max_tokens` or set `models.<role>.reasoning_effort` (e.g. `low` / `disable`).
- **zsh is the shell:** `$var:foo` applies zsh modifiers, so use `${var}`; unmatched globs abort the command, so use `find`; `PIPESTATUS` is bash-only (zsh uses `$pipestatus`).
- **LiteLLM errors** print help banners after the real exception, so `tail` hides the cause. Grep for `Error|Exception`. **Redact keys**: Gemini errors can include `key=` in URLs.
- **Gemini 2.5 Flash spends "thinking" tokens from `max_tokens`** (observed `thoughtsTokenCount`). Don't set `max_tokens` very low.
- LiteLLM fetches a remote price map at import, and the fetch timed out here. Try `LITELLM_LOCAL_MODEL_COST_MAP=True` in `.env` (untested).
- **Free-tier rate limits** will bind in Phase 6 (weak labels) and Phase 9 (judge). See the limiter task in Phase 5b.

---

## 2. Migration to the Linux filesystem (do first, ~30 min)

**Done 2026-09-11 → `/home/siddhant/Hiver`** (not `~/projects/hiver`; read that path below as `~/Hiver`). The first copy was incomplete; see §1.2 item 5. Result: `uv sync --locked` in 0.6 s, and a live smoke call in 5.5 s end to end (was 50–80 s on `/mnt/c`), so `LITELLM_LOCAL_MODEL_COST_MAP` isn't needed. The commands below are kept for the record.

```bash
# 1. Copy everything except the venv and caches (.git, .env, twcs.csv, llm cache all come along)
mkdir -p ~/projects
rsync -a --info=progress2 --exclude .venv --exclude .pytest_cache --exclude __pycache__ \
  "/mnt/c/Users/HP/Desktop/Projects/Hiver/" ~/projects/hiver/
cd ~/projects/hiver

# 2. Normalise permissions (drvfs showed every file as 777) and track exec bits properly again
chmod -R u=rwX,go=rX . && chmod 600 .env
git config core.filemode true

# 3. Rebuild the venv from the lockfile (uv cache is on the same FS → hardlinks, fast)
uv sync --locked

# 4. Verify
uv run pytest -q                                                           # 11 passed
LLM_OFFLINE=1 uv run python -m src.llm "Reply with the single word: ok"    # ok, from cache in ~1 s
uv run python -m src.llm "Reply with the single word: yes"                 # live Gemini call
uv sync --locked --dry-run                                                 # Would make no changes

# 5. Carry over planning context for the next Claude Code session
cp ~/.claude/plans/i-want-you-to-mellow-hollerith.md ~/projects/hiver/PLAN.md
mkdir -p ~/.claude/projects/-home-siddhant-projects-hiver/memory
cp ~/.claude/projects/-mnt-c-Users-HP-Desktop-Projects-Hiver/memory/*.md \
   ~/.claude/projects/-home-siddhant-projects-hiver/memory/
```
Then:
- Start Claude Code from `~/projects/hiver`.
- Make the **Phase 0 commit**. Check that `.env`, `*.pdf` and `data/raw/*` are ignored, and that `uv.lock` and `llm_cache.sqlite` are included.
- Delete the `/mnt/c` copy **only after step 4 passes**. That frees about 2 GB (1.5 GB venv + 493 MB CSV).

**Migration exit criteria:** step 4 all green; `uv sync` takes minutes, not half an hour; live smoke startup drops well below the 50–80 s seen on `/mnt/c`.

---

## 3. Architecture

```
                 ┌───────────────────────────────────────────────┐
                 │  src/contracts/   (pydantic types — Phase 4)   │
                 │  SupportRequest · AgentState · AgentOutput ·    │
                 │  IntentPrediction · RetrievedExample ·          │
                 │  EscalationDecision · GoldenExample · enums     │
                 └───────────────────────────────────────────────┘
                        ▲ used by everything below
┌──────────────────────┐ ┌──────────────────────────┐ ┌──────────────────────┐
│ src/core/  (pure Py) │ │ src/orchestration/       │ │ src/eval/            │
│ preprocess, rules,   │◄│ LangGraph StateGraph;    │◄│ run_eval, metrics,   │
│ classify, retrieve,  │ │ nodes = thin wrappers    │ │ judge, agreement,    │
│ draft, validate,     │ │ around core functions    │ │ baselines (no graph) │
│ decide_escalation    │ └──────────────────────────┘ └──────────────────────┘
└──────────────────────┘            │
        ▲ injected deps             ▼ optional side effects only
┌──────────────────────┐ ┌──────────────────────────────────────────────┐
│ src/ports/ Protocols │ │ src/integrations/ (optional, lazy-imported)   │
│ LLMClient, Cache,    │◄│ PostgresResultStore · RedisCache ·            │
│ ResultStore,         │ │ SlackEscalationSink · FastAPI endpoint ·      │
│ EscalationSink       │ │ LangSmith tracing                             │
│ + local defaults     │ └──────────────────────────────────────────────┘
│ (SQLite, JSONL, Null)│   Eval profile ALWAYS uses local defaults.  [BUILT]
└──────────────────────┘   src/llm/client.py = LiteLLMClient          [BUILT]
```

**LangGraph workflow (Phase 8):**
```
START → preprocess → rule_screen ──(hard rule: SAFETY_LEGAL / SECURITY)──► handoff ──────────────┐
                          │                                                                        ▼
                          └──► classify → retrieve → draft → validate_reply ──(fail, retry<1)──► draft
                                                                   │ (pass, or retry exhausted)
                                                                   ▼
                                                          decide_escalation → finalize → END
```
Each node is ~5 lines: read fields from `AgentState`, call one `core.*` function, return a partial state update.

## 4. Data splits (enforced from Phase 2 onward)

| Split | Source | Size | Labels | Allowed uses | Forbidden |
|---|---|---|---|---|---|
| `train` | threads before `split_date` | ~5–10k records | **weak only** | taxonomy exploration, codebook examples, few-shot examples, retrieval KB, weak labels, baseline training | reporting any metric |
| `dev` | after `split_date`, disjoint threads | 40 | human | prompt/threshold tuning, weak-label quality estimates, judge rubric calibration | final reported numbers |
| `golden` | after `split_date`, disjoint threads | 200 | human | final evaluation only; frozen + hashed | tuning, few-shot, KB, codebook examples |
| `unused` | rest of the post-split pool | — | none | nothing | everything |

Enforcement:
- Splits are assigned per `thread_id` in `src/dataprep/splits.py`, and all access goes through `loaders.load(split)`.
- The index builder asserts `split == "train"`.
- `data/golden/golden.lock` holds the golden set's SHA-256, and `run_eval` refuses to run on a mismatch.
- `tests/test_split_integrity.py` checks thread disjointness, time ordering, that the KB shares nothing with dev ∪ golden, that few-shot IDs are all from train, and flags near-duplicate texts across splits (cosine > 0.95).

## 5. Remaining schedule

| Day | Phases |
|---|---|
| Day 1 (done) | Phase 0 + env repair + Gemini switch |
| Day 2 | Migration, Phases 1, 2, 3 |
| Day 3 | Phases 4, 5, 5b, 6 |
| Day 4 | Phases 7, 8, 9 |
| Day 5 (buffer) | Phases 10, 11; Phase 12 only if 11 passes |

---

## 6. Phases

### Phase 0 — Setup, ports, provider-agnostic LLM layer ✅ DONE
See §1. Exit criteria met: real prompt works; the second call hits the cache; the provider is one config line; importing the LLM layer loads no optional packages.

### Phase 1 — EDA & brand selection ✅ DONE (2026-09-11): brand = **XboxSupport**
**Outcome.** Details are in `results/eda.md`, `results/brand_validation.md` and the `[P1]`
entries in `DECISIONS.md`.

**Deviations from the plan**
- The analysis is plain scripts (`scripts/eda.py`, `scripts/validate_brand.py`), not a notebook.
  No Jupyter dependencies were added.
- The CSV is read with pandas' C engine, not pyarrow: 106,891 tweets contain quoted newlines.

**Verified dataset facts**
- `response_tweet_id` holds comma-separated IDs in 222,426 tweets, so threads are trees.
- 99.7% of tweets fall in the last 90 days (Oct–Nov 2017).
- 0.1% of tweets are orphans (their parent isn't in the dataset).

**XboxSupport sizing**

| | Count |
|---|---|
| Brand tweets | 24,557 |
| Usable exchanges | 18,549 (13,006 first contacts) |
| Threads | 12,703 |
| Exchanges with a substantive reply | 4,413 |
| Confirmed public fixes | about 80–100 |

Noise: 99.4% of replies carry an agent sign-off (`^XS`), 31% are split replies, 26% are canned
DM templates, and 21.5% are DM deflections.

**Carry forward into later phases**
- **Phase 2:**
  - Merge split replies (the brand continuing itself within 15 min) and strip `^XX` sign-offs.
  - Drop non-English, fewer-than-3-word, "DM sent" and duplicate customer tweets.
  - Split per thread; the time split falls inside Oct–Nov 2017.
  - Port `build_exchanges` / `clean_waterfall` from `scripts/validate_brand.py` rather than
    rewriting them.
- **Phase 3:**
  - Add a "vague / needs more info" intent and explicit follow-up rules.
  - Merge purchase, codes and subscription if they turn out too thin.
  - The topic and draft-intent sizes in `results/brand_validation.md` are exploratory only.
- **Phase 5:** the stratified 80 must top up rare intents to about 10 each (bans, codes and
  subscriptions get about 3 each in a random 120).
- **Phases 6/7:** outcome labels are too sparse for evaluation. Use them only to nudge retrieval
  re-ranking.
- `LITELLM_LOCAL_MODEL_COST_MAP` isn't needed: a live call takes 5.5 s after the move.

_The original Phase 1 plan, kept for the record:_

**Known facts about `twcs.csv`:**
- 493 MB, header `tweet_id,author_id,inbound,created_at,text,response_tweet_id,in_response_to_tweet_id`.
- `created_at` looks like `Tue Oct 31 22:10:47 +0000 2017` (format `%a %b %d %H:%M:%S %z %Y`).
- Brands have handle `author_id`s (e.g. `sprintcare`); customers have numeric IDs; `inbound=True` means a customer tweet.
- Mentions are anonymised (`@115712`).
- `response_tweet_id` may hold comma-separated IDs. Verify this.

**Steps** (`notebooks/01_eda.ipynb`; add `ipykernel` to the `data` extra):
1. Load with the pyarrow engine. Count outbound tweets per brand (top 15).
2. For 3–4 candidates (e.g. `SpotifyCares`, `AppleSupport`, `AmazonHelp`, `Uber_Support`), measure:
   - volume and date range
   - **% pure "DM us" deflection replies**
   - % replies with concrete troubleshooting
   - % English, thread length, % customer follow-ups
3. Hand-read about 50 threads of the leading candidate. Catalogue the noise: handles, URLs, sign-offs like `^JK`, emoji, split tweets, non-English.
4. Optional quick win: add `LITELLM_LOCAL_MODEL_COST_MAP=True` to `.env`/`.env.example`, then measure live smoke latency before and after.

**Exit:** brand chosen and written into `config.yaml`; 5+ data-quality issues named; deflection rate known. **Decision log:** brand rationale.

### Phase 2 — Ingestion, cleaning, splits, weak outcome labels ✅ DONE (2026-09-11)
**Outcome.** Details are in `results/phase2_data_report.md`, `results/reconstruction_samples.md`
and the `[P2]` entries in `DECISIONS.md`.

- **Code:** `src/dataprep/{text,raw,exchanges,weak_signals,splits,loaders,build}.py`, run with
  `python -m src.dataprep.build`. The Phase 1 scripts now import the shared patterns and loaders,
  and their outputs were verified byte-identical.
- **Data:** `records.parquet` holds 18,712 exchanges: train 12,792, holdout 5,803 (5,798
  eval-eligible) and excluded 117. `split_date` is 2017-11-15. 36 reconstructed samples were
  inspected by hand across two rounds.

**Deviations from the plan**
- File names: `weak_signals.py` instead of `weak_outcomes.py`, and `exchanges.py` + `build.py`
  instead of `ingest.py`.
- Split values are `train` / `holdout` / `excluded`. Dev and golden are written in Phase 5.
- Weak outcomes are `resolved` / `unresolved` / `acknowledged` / `deflected` / `unknown`, plus
  `outcome_confidence`. The plan had positive / deflected / unresolved / unknown.

**Carry forward into later phases**
- **Phase 3:** build the codebook from train only. Include a "vague / needs more info" intent and
  follow-up rules, and read `context` for follow-ups.
- **Phase 5:** sample dev and golden by thread from `loaders.eval_pool()`.
- **Phase 7:** retrieve from `loaders.retrieval_corpus()`. The `substantive` label is only about
  60% precise, so re-rank and dedupe templates.
- **Phase 9:** slice reply-quality metrics by `reply_template_in_train`.

_The original Phase 2 plan, kept for the record:_

### Phase 2 — Ingestion, cleaning, splits, weak outcome labels (~3h)
`src/dataprep/ingest.py`, `splits.py`, `weak_outcomes.py`, `loaders.py`; `make sample`.
1. Filter to the brand's threads and rebuild the chains via `in_response_to_tweet_id` / `response_tweet_id`.
2. **Unit of prediction:** an inbound customer tweet that received a brand reply, with ≤2 prior turns of context. Flag `is_followup`.
3. **Cleaning:**
   - replace handles with `@user` and URLs with `<URL>`
   - strip sign-offs and normalise whitespace
   - drop non-English, empty and exact-duplicate tweets
4. Assign splits per §4 (per `thread_id`, time-based) and set `data.split_date`.
5. **Weak outcome labels** (`weak_outcome_v1`, train only): `positive` / `deflected` / `unresolved` / `unknown`, stored in `weak_outcome` + `weak_outcome_source="heuristic_v1"`.
6. Commit `data/processed/records.parquet` with columns `record_id, thread_id, created_at, customer_text, context, brand_reply, is_followup, split, weak_outcome, weak_outcome_source`.
7. Write `tests/test_split_integrity.py` now.

**Exit:** regenerates from the raw CSV in minutes; 20 spot-checks look right; split tests pass. **Decision log:** unit of prediction; time-based per-thread split; the outcome heuristic is weak supervision.

### Phase 3 — Codebook: intent taxonomy + escalation policy
**Status (2026-09-11):** taxonomy ✅ FROZEN (v1); escalation policy ✅ FROZEN after dev calibration
(`results/escalation/dev_calibration.md`).

**Outcome**
- Codebook `data/codebook.md` and evidence `results/taxonomy/proposal.md` are both rendered from
  `data/taxonomy/taxonomy_v1.yaml` by `scripts/taxonomy_explore.py render`.
- **4 conversation states**: `new_issue`, `issue_followup`, `acknowledgement_closing`,
  `social_offtopic`. The last two carry no intent.
- **11 primary intents**: connectivity, install/update, hardware (controllers inside),
  software/game/app, account, purchases/billing/orders, entitlements/subscriptions/codes,
  enforcement, product info/feedback, support-process complaint, needs_more_context.
- **Deterministic rules**: S1–S2 settle the state (S1: closing only if no unresolved issue
  remains), T0 picks the primary intent, T1–T11 settle between intents, T12 comes last.
- **Risk and escalation** are a separate overlay layer.
- **Internal-only fields**: `secondary_intents`, `subtype`, `event_tag`.
- The 150-row coding sample (`data/taxonomy/discovery_sample_coding.csv`) is discovery evidence
  from train, not gold.
- The name lists are pinned by `tests/test_taxonomy_frozen.py`.
- **Dev set** (40 holdout items, `scripts/sample_dev.py`): labelled as ChatGPT drafts approved by
  the project owner, then used by `scripts/calibrate_escalation.py` to calibrate escalation. It is
  kept exactly as drawn. D12 is Portuguese and got past the heuristic language filter: the
  English words came from a game title and tied 2–2. It is labelled, not redrawn.

**Carry forward into later phases**
- **Phase 4 contracts:** `Intent` has 11 values; add `ConversationState` (4) and `RiskLevel` (3).
  `GoldenExample` gets `conversation_state`, a nullable `intent`, `risk_level`, `escalate`,
  `reason_code`, plus internal `secondary_intents`, `subtype` and `event_tag`. `AgentOutput`
  predicts state, intent and escalation. `ReasonCode` adds `STEPS_FAILED`; `REPLY_FAILED_CHECKS`
  is only valid with `triggered_by = validation`.
- **Phase 5:** golden sampled, excluding the 40 dev threads. The project owner labels it blind
  first (see Phase 5 status).
- **Phase 9:** metrics as listed under Phase 9.

_The original Phase 3 plan, kept for the record:_

### Phase 3 — Codebook: intent taxonomy + escalation policy (~3h, train only)
1. **Open coding (primary view):** hand-read about 150 random train messages.
2. **Exploratory clustering (secondary view):** `src/dataprep/taxonomy_explore.py` embeds ~5k messages, runs KMeans with k≈20–30, and has the LLM summarise each cluster from 15 samples. Output goes to `results/taxonomy_exploration.md` as **notes, never labels**.
3. Reconcile both views into 8–12 intents + `other`. An intent survives only if it implies a distinct reply strategy or escalation policy.
4. Write `data/codebook.md` (`v1`). For each intent: definition, include/exclude rules, 3 train examples, default escalation policy. Add rules for multi-intent tweets, sarcasm and follow-ups.
5. **Reason codes:**
   - escalation: `ACCOUNT_SPECIFIC, BILLING_DISPUTE, SAFETY_LEGAL, SECURITY, HIGH_ANGER, REPEAT_CONTACT, OUT_OF_SCOPE, LOW_CONFIDENCE, REPLY_FAILED_CHECKS`
   - auto-handle: `ROUTINE_TROUBLESHOOTING`, `GENERAL_INFO`
6. Pilot on 30 fresh train messages. `other` should be ≲10–15%. Revise, then **freeze v1 before golden labelling**; any later change means relabelling and a version bump.

**Decision log:** codebook-as-truth; intent count; escalation definition; Banking77 skipped.

### Phase 4 — Typed contracts (~2h)
`src/contracts/` (pydantic v2):
- `enums.py`: `Intent` (mirrors codebook v1), `ReasonCode`, `Split`, `WeakLabelSource`.
- `SupportRequest` (frozen): `request_id, brand, customer_text, context: list[Turn], created_at, is_followup`.
- `IntentPrediction`: `intent, confidence∈[0,1], rationale`.
- `RetrievedExample`: `record_id, customer_text, brand_reply, similarity, weak_outcome, weak_outcome_source`.
- `EscalationDecision`: `escalate, reason_code, reason_text, triggered_by∈{rule, signal, policy, validation}`.
- `AgentState` (pydantic; LangGraph state): `request, cleaned_text, rule_hits, intent, retrieved, draft, validation_errors, draft_attempts, escalation, trace`.
- `AgentOutput`: `request_id, system, intent, intent_confidence, reply, escalate, reason_code, reason_text, retrieved_ids, codebook_version, model_versions, latency_ms`. Validators: a reason is always required; escalation codes are allowed only when `escalate=True`.
- `GoldenExample`: `request, label_intent, label_escalate, label_reason_code, slice∈{random, stratified}, notes, labeler`.
- `finalize(state) -> AgentOutput` (a pure function).

`tests/test_contracts.py`: JSON round-trips, invalid inputs rejected, `Intent` matches the codebook headings.

**Exit:** tests pass; baselines, agent and eval import types only from `src/contracts`.

### Phase 5 — Dev + golden labelling (~4h)
**Revised order (2026-09-11):**
1. **Dev drawn first.** `scripts/sample_dev.py` drew 40 holdout items, one per thread and all
   eval-eligible: 16 random plus 24 targeted (4 each: strong anger, repeat contact,
   account-specific, vague/low confidence, after a clarification, repair/replacement). They are in
   a blind sheet, `data/golden/dev_labeling_sheet.csv`, with `dev_sample_key.csv` recording each
   item's slice and thread.
2. **A human labels dev** with the codebook, including the cue columns. No model pre-fill.
3. **Calibrate escalation on dev.** Compare the draft combination rules with the labeller's
   decisions, adjust, record the changes in DECISIONS, then **freeze the escalation policy**.
4. **Only then sample the golden set (200) from the holdout, excluding every dev thread.** Label
   it and lock it with `golden.lock`.

**Status (2026-09-11):**
- **Steps 1–3 done.** Dev labels were ChatGPT drafts approved by the project owner, so the
  calibration is partly circular and not independent validation.
- **Golden sampled** by `scripts/sample_golden.py`: 120 random + 80 stratified, in the blind sheet
  `data/golden/golden_labeling_sheet.csv`.
- **Human-first protocol** (`data/golden/LABELING.md`), in order:
  1. primary human labels, locked
  2. a blind LLM second opinion
  3. an adjudication log
  4. final labels generated from the human labels plus the log
- **Golden is evaluation-only**, and `tests/test_golden_integrity.py` guards it.

_Original Phase 5 text:_
1. Sample from the post-split pool:
   - golden: 120 random + 80 stratified (rare intents, anger, follow-ups, multi-intent, sarcasm)
   - dev: 40 random
   - dev and golden use disjoint threads
2. Label in a spreadsheet with codebook v1: `intent, escalate, reason_code, notes`. No LLM pre-fill, to avoid anchoring.
3. Validate the rows against `GoldenExample` and write `data/golden/{golden,dev}.jsonl`. Write `golden.lock` (SHA-256) and commit.
4. Write `data/golden/LABELING.md`: sampling, codebook version, time spent, ambiguous cases, biases.
5. Schedule a 30-item blind re-label for self-consistency κ (Phase 10).

### Phase 5b — Rate limiting for free-tier Gemini (~45 min, new in v3)
- Add an optional `requests_per_minute` per role in `config.yaml` (`null` = unlimited).
- Add a small thread-safe min-interval limiter inside `LiteLLMClient._call`. It applies only to live calls; cache hits are never throttled.
- Add a test using a fake clock.
- Check the quotas at ai.dev/rate-limit and size bulk jobs to fit them. The cache makes bulk jobs **resumable across days**: a rerun skips work that's already done.
- If the daily quota is too small, either reduce the weak-label count (e.g. 1k) or enable billing (which also unlocks a Pro judge).

### Phase 6 — Weak supervision & baselines (~2.5h)
1. `src/dataprep/weak_intents.py`: the LLM applies codebook v1 to ~2k **train** records (count adjusted per 5b). Output: `data/processed/weak_labels.parquet` with `weak_intent, weak_intent_confidence, weak_label_source="llm:<model>", codebook_version`.
2. **Measure weak-label quality:**
   - the same labeler on **dev** → accuracy / macro-F1
   - hand-check 40 train `weak_outcome` labels → precision per class
3. **Usage policy** (goes in the README): weak labels may train the TF-IDF baseline and inform re-ranking. They must never appear in dev/golden and never be used as eval targets.
4. `src/eval/baselines.py` (plain Python, returns `AgentOutput`):
   - **Trivial:** majority intent; always-escalate (and never-escalate for contrast); fixed template reply.
   - **Simple:** TF-IDF + LogisticRegression on weak labels; regex escalation; nearest-neighbour historical reply.

**Decision log:** the simple baseline distils the labeler, so its ceiling is roughly the labeler's quality.

### Phase 7 — Core business logic, framework-free (~3.5h)
All in `src/core/`, with no `langgraph` imports; every LLM is an injected `LLMClient`.

| Function | What it does |
|---|---|
| `preprocess.clean(request)` | Cleans the incoming text |
| `rules.screen(text, context) -> list[RuleHit]` | Hard + soft rules |
| `classify.classify(text, context, codebook, llm) -> IntentPrediction` | `prompts/classify.md`; few-shot from train only |
| `retrieve.retrieve(text, intent, index, k)` | numpy cosine over the train-only `data/processed/index.npz`; intent filter; re-rank favouring `positive`, down-weighting `deflected` |
| `draft.draft(text, context, examples, style_guide, llm)` | `prompts/draft.md`: ≤280 chars; no invented policies, links or refunds; no public PII requests |
| `validate.validate_reply(reply) -> list[str]` | Length, invented URLs, PII-ask regex |
| `escalate.decide(...) -> EscalationDecision` | Rules → signals → per-intent policy |

Tests: `tests/test_core.py` (`FakeLLM`) and `tests/test_core_no_framework.py` (asserts langgraph is not in `sys.modules`).

**Exit:** tests pass; thresholds tuned on **dev only**.

### Phase 8 — LangGraph orchestration (~1.5h)
- `src/orchestration/graph.py`: `build_graph(deps)` with `StateGraph(AgentState)`. Nodes wrap core functions via closures. Conditional edges as in the §3 diagram.
- `run.py`: `run(request, deps) -> AgentOutput`; CLI `python -m src.orchestration.run "tweet"`.
- Side effects (store, sink) run after `finalize`, outside the graph, and only when `profile != "eval"`.
- `tests/test_graph.py`: the handoff path, the retry-once path, and graph output == a sequential core composition.

### Phase 9 — Eval harness + LLM judge + human agreement (~4h)
**Routing metrics, fixed at the taxonomy freeze** (bootstrap 95% CIs, per slice). These are in
addition to reply quality and the judge:
- **Conversation state:** accuracy and macro-F1 (4 states, all items).
- **Intent:** macro-F1 over the 11 intents, **conditional on intent-bearing gold states**
  (`new_issue`, `issue_followup`), plus per-intent F1 and a confusion matrix.
- **Escalation:** precision and recall, plus **must-escalate recall** (gold risk high, or reason
  SECURITY / SAFETY_LEGAL / BILLING_DISPUTE).
- **Joint routing correctness:** state, primary intent (when one is due) and escalate all correct.
- **Never scored:** `secondary_intents`, `subtype`, `event_tag`. `reason_code` agreement is
  reported for information only.
- **Slices:** random vs stratified, first contact vs follow-up, and event-tied vs not. Reply
  quality is also sliced by `reply_template_in_train`.

_Original Phase 9 text:_
1. `run_eval.py`:
   - verify `golden.lock`
   - build deps with `profile="eval"`
   - run trivial, simple and agent on golden
   - write `results/{predictions.jsonl, metrics.json, summary.md}`
2. `metrics.py`:
   - intent: accuracy, macro-F1, per-class F1, confusion matrix
   - escalation: P/R/F1, with **recall on must-escalate** as the safety metric; auto-handle rate
   - reply checks: ≤280 chars, invented URLs, PII asks
   - **bootstrap 95% CIs**, reported for the `random` and `stratified` slices separately
3. `judge.py` + `prompts/judge.md`:
   - scores 1–5 for groundedness, helpfulness, tone/brand voice, safety, conciseness
   - reference-guided: shows the brand's real reply as a reference, not as gold
   - uses `models.judge`
4. `agreement.py`:
   - 50 blinded replies: 15 from dev for calibration (then freeze the prompt), 35 from golden for measurement
   - human grades go in `data/golden/human_judgments.csv`
   - report per-dimension weighted κ, exact / within-1 agreement, and biases
5. Optional: a no-retrieval ablation.

**Exit:** `LLM_OFFLINE=1 make eval` reproduces `summary.md` from the cache.

### Phase 10 — Failure analysis & one controlled iteration (~3h)
1. Dump golden errors to `results/failures.md`. Tag and count them, then write up the top 5 with examples, a hypothesis and a fix for each.
2. Optionally apply one fix: validate it on dev, re-run golden once, and report before/after.
3. Run the 30-item self-consistency re-label to get intra-annotator κ.

### Phase 11 — Report, decision log, reproducibility, submit (~4h)
1. **README:** quickstart (`uv sync --locked && LLM_OFFLINE=1 uv run ...eval`), live mode, split and weak-supervision policy, how to regenerate from raw. Export `requirements.txt`.
2. **`REPORT.md` (≤6 pages):**
   - framing; what "good" means; what was not built
   - results vs baselines with CIs and slices; weak-label quality; judge–human κ; top-5 failures
   - **misleading-number section:** same person built the codebook and the labels; stratified slice ≠ production mix; Flash-tier, same-vendor judge; historical replies are often deflections; weak outcomes drive re-ranking; 2017 data; single-turn eval; English-only filter; n=200 CI width
   - next week
3. `DECISIONS.md`: trim to the best 10–15, including P0 entries and the §1.2 incidents where relevant.
4. **Citations:** dataset, LiteLLM, LangGraph, sentence-transformers.
5. **Fresh-clone test** on the Linux FS: new directory, no API key, `uv sync --locked`, timed <15 min.
6. Push and submit via the Notion form.

### Phase 12 — Optional integrations (stretch; only after Phase 11 passes)
- `src/integrations/`: `PostgresResultStore`, `RedisCache` (runtime only; the committed SQLite cache stays the reproducibility source), `SlackEscalationSink`, FastAPI `POST /triage`, LangSmith tracing.
- Each adapter takes `config=cfg` (matching `factory._optional`) and lazy-imports its library. On failure → fallback.
- `docker-compose.yml` for Postgres + Redis.
- `tests/test_integrations_isolated.py`: with the optional packages unimportable, an eval run still works.
- Re-run the fresh-clone test.

---

## 7. Final repo layout

```
hiver/
├── README.md  REPORT.md  DECISIONS.md  PLAN.md  Makefile  config.yaml
├── pyproject.toml  uv.lock  .python-version  requirements.txt (exported, P11)  .env.example
├── prompts/            classify.md  draft.md  judge.md  style_guide.md
├── data/
│   ├── raw/            (gitignored) twcs.csv
│   ├── processed/      records.parquet  weak_labels.parquet  index.npz
│   ├── golden/         golden.jsonl  golden.lock  dev.jsonl  human_judgments.csv  LABELING.md
│   ├── codebook.md
│   └── cache/          llm_cache.sqlite   (committed)
├── src/
│   ├── config.py                                                     [built]
│   ├── contracts/      enums.py  models.py
│   ├── core/           preprocess rules classify retrieve draft validate escalate
│   ├── orchestration/  graph.py  run.py
│   ├── llm/            client.py  __main__.py                        [built]
│   ├── ports/          protocols.py  defaults.py  factory.py         [built]
│   ├── integrations/   postgres_store redis_cache slack_sink api      (optional)
│   ├── dataprep/       ingest splits loaders weak_outcomes weak_intents taxonomy_explore
│   └── eval/           baselines metrics judge agreement run_eval
├── tests/              test_llm_client.py test_ports.py              [built]
│                       test_contracts test_split_integrity test_core test_core_no_framework
│                       test_graph test_integrations_isolated
├── notebooks/          01_eda.ipynb
└── results/            summary.md metrics.json predictions.jsonl failures.md taxonomy_exploration.md
```

## 8. Verification
- **After migration:** §2 step 4 (11/11 tests, offline cache replay, live Gemini call, lock dry-run clean).
- **Every phase:** its exit criteria hold before the next phase starts. `uv run pytest -q` stays green.
- **End-to-end (Phase 11):** on a fresh clone with no API key, `uv sync --locked` followed by `LLM_OFFLINE=1` eval reproduces `results/summary.md` exactly in <15 min. `python -m src.orchestration.run "my app keeps crashing"` prints a valid `AgentOutput`. A provider swap (change `models.*.name`) still runs.
