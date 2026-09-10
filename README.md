# Hiver Support Agent

An AI support agent for one brand from the Kaggle *Customer Support on Twitter* dataset. It
classifies each customer tweet's intent, drafts a reply grounded in how the brand has replied
before, and decides whether to auto-handle or escalate (with a reason). The repo also contains
the evaluation harness that measures how far the agent can be trusted.

> **Status:** Phase 0 (setup) complete. See [Build progress](#build-progress).

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
| `data/` | Processed subsample, golden/dev sets, codebook, LLM cache |
| `prompts/` | Prompt templates |
| `results/` | Metrics, predictions, failure analysis |
| `DECISIONS.md` | Decision log |

## Build progress

- [x] Phase 0: setup, ports, provider-agnostic LLM layer
- [ ] Phase 1: EDA & brand selection
- [ ] Phase 2: ingestion, cleaning, splits, weak outcome labels
- [ ] Phase 3: intent taxonomy & escalation policy (codebook)
- [ ] Phase 4: typed contracts
- [ ] Phase 5: dev + golden labelling
- [ ] Phase 6: weak supervision & baselines
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
