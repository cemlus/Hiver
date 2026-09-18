# Thin wrappers: every target is a single command you can also run directly.
.PHONY: setup test llm-smoke data sample taxonomy index eval report

setup:      ## create .venv (Python 3.11) and install the pinned dependencies from uv.lock
	uv sync --locked

test:
	uv run pytest -q

llm-smoke:  ## one real LLM call with the agent model (needs an API key in .env)
	uv run python -m src.llm "Reply with the single word: ok"

data:       ## download the raw Kaggle dataset into data/raw/ (needs Kaggle credentials)
	uv run --extra data --env-file .env kaggle datasets download -d thoughtvector/customer-support-on-twitter -p data/raw --unzip

sample:     ## Phase 2: data/processed/records.parquet + results/phase2_*.md (needs data/raw/twcs.csv)
	uv run python -m src.dataprep.build

taxonomy report:
	@echo "'$@' is implemented in a later phase" && exit 1

index:
	uv run python scripts/build_embeddings.py

eval:       ## reproduce the headline routing table from the committed cache (no API key)
	LLM_OFFLINE=1 uv run python scripts/run_routing_eval.py
