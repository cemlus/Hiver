# Hiver Support Agent

An AI support agent for one brand from the Kaggle *Customer Support on Twitter* dataset. It
classifies each customer tweet's intent, drafts a reply grounded in how the brand has replied
before, and decides whether to auto-handle or escalate (with a reason). The repo also contains
the evaluation harness that measures how far the agent can be trusted.

> **Status:** Phases 0–3 complete. Taxonomy **frozen** (11 intents, 4 conversation states) and
> escalation policy **frozen** after calibration on the 40-item dev set. Golden set labelled by hand and locked.
> Brand: **XboxSupport**. See [Build progress](#build-progress).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.11 itself).

```bash
uv sync --locked              # .venv with Python 3.11 + exact deps from uv.lock (CPU-only torch)
uv run pytest -q              # offline tests, no API key needed
cp .env.example .env          # then add the API key for the provider named in config.yaml
uv run python -m src.llm "Reply with the single word: ok"   # one real LLM call
```

`make setup`, `make test` and `make llm-smoke` run the same commands if you have `make`.

## Switching LLM provider

Edit `models.agent.name` and `models.judge.name` in `config.yaml`. They are LiteLLM strings
such as `anthropic/claude-haiku-4-5`, `openai/<model>`, `gemini/<model>` or `ollama/<model>`.
Then put that provider's key in `.env`. No code changes are needed.

Every LLM call is cached in `data/cache/llm_cache.sqlite` (committed). With `LLM_OFFLINE=1`,
runs use only that cache, so results reproduce without an API key.

## Data pipeline

`uv run python -m src.dataprep.build` (or `make sample`) rebuilds the committed
`data/processed/records.parquet` from `data/raw/twcs.csv` in about 40 s. It never modifies the
raw file.

- **Unit.** One exchange = one customer message plus XboxSupport's reply. Tweets split across
  several posts are merged on both sides, and earlier turns are kept as `context`. There are
  18,712 usable exchanges.
- **Splits.** Assigned per thread, by time (`data.split_date: 2017-11-15`):
  - `train`: 12,792
  - `holdout`: 5,803 (Phase 5 samples dev/golden from it)
  - `excluded`: 117

  Read the records only through `src/dataprep/loaders.py`.
- **Weak supervision.** `weak_outcome`, `outcome_confidence` and `brand_escalation_evidence` are
  heuristics. They exist only on train and are never evaluation targets.
- **Grounding corpus.** Only `retrieval_eligible` rows (train + substantive reply).
  `substantive` is a retrieval heuristic, not ground truth: it was about 60% precise in a hand
  sample, and it is never an evaluation target.
- **Held-out template reuse.** 52% of holdout DM-deflection replies reuse a reply template that
  also occurs in train. Reply-quality results must therefore be sliced by
  `reply_template_in_train`.

[`results/phase2_data_report.md`](results/phase2_data_report.md) documents every cleaning
decision, the funnel, the leakage checks and the data dictionary. The hand-inspected samples are
in [`results/reconstruction_samples.md`](results/reconstruction_samples.md).

## Taxonomy and evaluation plan

- **Codebook.** [`data/codebook.md`](data/codebook.md) is generated from
  `data/taxonomy/taxonomy_v1.yaml` by `uv run python scripts/taxonomy_explore.py render`.
  - Every exchange gets one of 4 conversation states. `acknowledgement_closing` and
    `social_offtopic` carry no intent; `new_issue` and `issue_followup` carry exactly one of the
    11 frozen primary intents.
  - `secondary_intents`, `subtype` and `event_tag` are internal and never scored.
  - The name lists are pinned by `tests/test_taxonomy_frozen.py`.
- **Freeze order.** Taxonomy (frozen) → escalation policy (calibrated on the 40-item dev set and
  frozen; [`results/escalation/dev_calibration.md`](results/escalation/dev_calibration.md)) → golden
  set sampled (see below), now waiting for human labels.
- **Dev set.** `scripts/sample_dev.py` drew 40 holdout items (16 random + 24 targeted at the
  escalation behaviours to calibrate) into `data/golden/dev_labeling_sheet.csv`. The sheet is
  blind; `dev_sample_key.csv` records each item's slice and thread. Its labels are ChatGPT drafts
  reviewed and approved by the project owner (see `DECISIONS.md`), and it is never a reported
  result. D12 is Portuguese; it got past the heuristic
  language filter and is kept as drawn (see `DECISIONS.md`). Because the drafts applied the same
  rules, the calibration's 40/40 agreement is partly circular: it is **not** independent
  validation.
- **Golden set.** `scripts/sample_golden.py` drew 200 holdout items (120 random + 80 stratified)
  into the blind sheet `data/golden/golden_labeling_sheet.csv`. It excludes every dev thread and
  every near-duplicate of a train or dev message.
  - The project owner labelled all 200 items first, without seeing model labels, and the sheet is
    locked by SHA-256 (`golden.lock`). Three labels deliberately diverge from the frozen policy and
    are reported as a policy over-escalation finding; single-labeller self-consistency was not
    measured.
  - An LLM second opinion and an adjudication log are kept as separate layers; see
    [`data/golden/LABELING.md`](data/golden/LABELING.md).
  - Golden is used for evaluation only.
- **Metrics** (bootstrap 95% CIs, reported per golden slice):
  - Conversation state: accuracy and macro-F1.
  - Intent: macro-F1 conditional on intent-bearing gold states, plus per-intent F1 and a
    confusion matrix.
  - Escalation: precision and recall, plus **must-escalate recall** (gold risk high or reason
    SECURITY / SAFETY_LEGAL / BILLING_DISPUTE).
  - **Joint routing correctness:** state, primary intent (when one is due) and escalate all
    correct at once.
- **Evidence status.** The 150-exchange coding sample in `data/taxonomy/` is taxonomy discovery
  evidence from train, not gold labels.

## Repo map

| Path | What lives there |
|---|---|
| `src/contracts/` | Typed data contracts shared by every module |
| `src/core/` | Framework-free business logic (classify, retrieve, draft, escalate) |
| `src/orchestration/` | LangGraph workflow wrapping `src/core` |
| `src/llm/` | Provider-agnostic LLM client with caching |
| `src/ports/` | Interfaces + local defaults + dependency factory |
| `src/integrations/` | Optional Postgres / Redis / Slack adapters (never used by eval) |
| `src/dataprep/` | Ingestion, cleaning, splits, weak labels, taxonomy exploration |
| `src/eval/` | Baselines, metrics, LLM judge, judge–human agreement |
| `scripts/` | Rerunnable analysis: `eda.py` (brand comparison) and `validate_brand.py` (usable-data check), which need `data/raw/twcs.csv`; `taxonomy_explore.py` (discovery sample, topics, codebook render); `sample_dev.py` (the 40-item dev set); `calibrate_escalation.py` (draft vs proposed escalation policy on dev labels); `sample_golden.py` (the 200-item golden set and its blind labelling sheet); `check_golden_labels.py` (read-only check of the human gold labels); `llm_second_opinion.py` (blind LLM labels for the same items); `compare_golden_labels.py` (human vs LLM agreement, adjudication log, final labels) |
| `data/taxonomy/` | Taxonomy spec (`taxonomy_v1.yaml`) and the discovery coding sample (not gold) |
| `data/` | Processed subsample, golden/dev sets, codebook, LLM cache |
| `prompts/` | Prompt templates |
| `results/` | EDA and brand validation reports, metrics, predictions, failure analysis |
| `DECISIONS.md` | Decision log |
| `PLAN.md` | Phase-by-phase build plan and lessons learned |

## Build progress

- [x] Phase 0: setup, ports, provider-agnostic LLM layer
- [x] Phase 1: EDA & brand selection (XboxSupport; [`results/eda.md`](results/eda.md), [`results/brand_validation.md`](results/brand_validation.md))
- [x] Phase 2: ingestion, cleaning, splits, weak outcome labels ([`results/phase2_data_report.md`](results/phase2_data_report.md))
- [x] Phase 3a: intent taxonomy frozen ([`data/codebook.md`](data/codebook.md), [`results/taxonomy/proposal.md`](results/taxonomy/proposal.md))
- [x] Phase 3b: escalation policy calibrated on the dev set and frozen ([`results/escalation/dev_calibration.md`](results/escalation/dev_calibration.md))
- [x] Phase 4: typed contracts (`src/contracts/`: enums pinned to the frozen codebook, pydantic models, `finalize()`)
- [ ] Phase 5: dev + golden labelling (dev done; golden sampled, awaiting human labels)
- [x] Phase 6: non-LLM routing baselines ([`results/eval/routing_baselines.md`](results/eval/routing_baselines.md)); the ~2k weak-label pass is deferred until the agent shows it is needed
- [ ] Phase 7: core business logic
- [ ] Phase 8: LangGraph orchestration
- [ ] Phase 9: evaluation harness + LLM judge + human agreement
- [ ] Phase 10: failure analysis
- [ ] Phase 11: report, reproducibility, submission
- [ ] Phase 12: optional integrations (stretch)

## Citations

- Dataset: *Customer Support on Twitter*, Thought Vector, Kaggle (`thoughtvector/customer-support-on-twitter`).
- [LiteLLM](https://github.com/BerriAI/litellm): provider-agnostic LLM calls.
- [LangGraph](https://github.com/langchain-ai/langgraph): workflow orchestration.
- [sentence-transformers](https://www.sbert.net/): `all-MiniLM-L6-v2` embeddings.
