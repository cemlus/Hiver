"""Probe the judge model before trusting it with a calibration run.

Run from the repo root:   uv run python scripts/probe_judge.py [--n 5]

Judge: `groq/openai/gpt-oss-120b` (config `models.judge`) -- a different model from the production
router/drafter `groq/qwen/qwen3.8-27b`, which is the point: a model must not grade its own work.

Measures, on a handful of real drafted dev replies:
  - one result per input, and the ids map back to the right item
  - schema validity and how many schema repairs the client needed
  - every score inside the rubric's 1-5 range
  - prompt / completion / total tokens, and latency per call
  - the provider's rate-limit headers, read from a raw call because LiteLLMClient does not expose them
  - an extrapolated cost for the full 15-item calibration run, measured rather than assumed

Writes results/eval/judge_calibration/probe.json. Dev only; the golden set is never loaded.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config                                  # noqa: E402
from src.contracts import SupportRequest                             # noqa: E402
from src.eval.judge import (DIMENSIONS, JUDGE_RUBRIC_VERSION, ReplyJudgement,  # noqa: E402
                            judge_reply, system_prompt)
from src.core.retrieve import examples_by_id                      # noqa: E402
from src.eval.quota import PER_MINUTE, classify                                  # noqa: E402
from src.ports.factory import build_deps                             # noqa: E402

DRAFTS = ROOT / "results" / "eval" / "dev_drafts.jsonl"
OUT = ROOT / "results" / "eval" / "judge_calibration"
CALIBRATION_ITEMS = 15


def drafted() -> list[dict]:
    if not DRAFTS.exists():
        sys.exit(f"{DRAFTS.relative_to(ROOT)} is missing: run scripts/draft_dev_replies.py first "
                 "(LLM_OFFLINE=1 replays it from cache for free).")
    rows = [json.loads(line) for line in DRAFTS.open(encoding="utf-8")]
    return [r for r in rows if (r.get("draft") or "").strip()]


def as_request(row: dict) -> SupportRequest:
    return SupportRequest(request_id=row["id"], brand=load_config()["brand"],
                          customer_text=row["message"], context=())


def rate_limit_headers(model: str) -> dict:
    """One minimal raw call, purely to read the x-ratelimit-* headers LiteLLM hides.

    Per DECISIONS [P7] these report per-MINUTE capacity and look healthy even when the daily token
    budget is exhausted, so they are recorded as context, never as proof a full run will fit.
    """
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return {"error": "GROQ_API_KEY not set in the environment"}
    body = json.dumps({"model": model.removeprefix("groq/"),
                       "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 1, "temperature": 0}).encode()
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 # A bare Python-urllib User-Agent is refused by the edge with "error code: 1010".
                 "User-Agent": "hiver-support-agent/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return {k.lower(): v for k, v in response.headers.items()
                    if k.lower().startswith("x-ratelimit")}
    except urllib.error.HTTPError as error:                       # noqa: PERF203
        detail = error.read().decode("utf-8", "replace")[:400]
        return {"http_status": error.code, "body": detail.replace(key, "***REDACTED***")}
    except Exception as error:                                    # noqa: BLE001
        return {"error": str(error)[:200].replace(key, "***REDACTED***")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--n", type=int, default=5, help="how many replies to probe")
    parser.add_argument("--skip", type=int, default=0,
                        help="skip this many replies first, so a re-probe makes live calls")
    parser.add_argument("--sleep", type=float, default=12.0,
                        help="seconds between live calls; ~2.1k tokens each against an 8k/min "
                             "ceiling means unspaced calls breach TPM deterministically")
    args = parser.parse_args()

    cfg = load_config()
    judge_cfg = cfg["models"]["judge"]
    agent_name = cfg["models"]["agent"]["name"]
    if judge_cfg["name"] == agent_name:
        sys.exit(f"judge and agent are both {agent_name}: a model must not grade its own replies.")

    llm = build_deps(profile="eval", config=cfg).judge_llm
    rows = drafted()[args.skip : args.skip + args.n]
    print(f"probing {llm.model} on {len(rows)} drafted dev replies "
          f"(rubric {JUDGE_RUBRIC_VERSION}, agent is {agent_name})", flush=True)

    results, failures = [], []
    before_retries = getattr(llm, "schema_retries", 0)
    for row in rows:
      while True:
        started = time.time()
        try:
            # Evidence text is resolved from the train-only corpus: dev_drafts.jsonl stores only
            # ids, and an empty evidence block makes groundedness unscoreable.
            retrieved = examples_by_id(row.get("retrieved_ids", []))
            judgement: ReplyJudgement = judge_reply(as_request(row), row["draft"], retrieved, llm,
                                                    reference=row.get("reference_reply", ""))
            usage = llm.last_usage or {}
            results.append({
                "id": row["id"],
                "scores": judgement.scores(),
                "in_range": all(1 <= v <= 5 for v in judgement.scores().values()),
                "dimensions_present": sorted(judgement.scores()) == sorted(DIMENSIONS),
                "unsupported_claims": judgement.unsupported_claims,
                "escalation_appropriate": judgement.escalation_appropriate,
                "latency_s": round(time.time() - started, 2),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "cached": llm.last_usage is None})
            print(f"  {row['id']}: {judgement.scores()} ({results[-1]['latency_s']}s)", flush=True)
            if llm.last_usage:
                time.sleep(args.sleep)
            break
        except Exception as error:                                # noqa: BLE001
            message = str(error)[:400]
            limit = classify(message)
            if limit and limit.kind == PER_MINUTE:
                # Transient by definition: wait out the window the API named and retry the item.
                print(f"  {row['id']}: per-minute limit; waiting "
                      f"{limit.wait_seconds:.0f}s", flush=True)
                time.sleep(limit.wait_seconds)
                continue
            failures.append({"id": row["id"], "error": message,
                             "rate_limited": limit.kind if limit else None})
            print(f"  {row['id']} FAILED: {message[:140]}", flush=True)
            break

    live = [r for r in results if r.get("total_tokens")]
    mean_tokens = (sum(r["total_tokens"] for r in live) / len(live)) if live else None
    mean_latency = (sum(r["latency_s"] for r in results) / len(results)) if results else None

    manifest = {
        "probe": "judge",
        "judge_model": llm.model,
        "production_agent_model": agent_name,
        "models_are_distinct": llm.model != agent_name,
        "rubric_version": JUDGE_RUBRIC_VERSION,
        "judge_params": {k: judge_cfg.get(k) for k in
                         ("temperature", "max_tokens", "reasoning_effort", "timeout")},
        "system_prompt_chars": len(system_prompt()),
        "probed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sleep_seconds": args.sleep,
        "items_probed": len(rows),
        "probed_ids": [r["id"] for r in rows],
        "results": results,
        "failures": failures,
        "ids_unique_and_mapped": sorted(r["id"] for r in results) == sorted(r["id"] for r in rows
                                                                           if r["id"] not in
                                                                           {f["id"] for f in failures}),
        "all_scores_in_range": all(r["in_range"] for r in results),
        "all_dimensions_present": all(r["dimensions_present"] for r in results),
        "schema_repairs": getattr(llm, "schema_retries", 0) - before_retries,
        "mean_latency_s": round(mean_latency, 2) if mean_latency else None,
        "mean_total_tokens": round(mean_tokens) if mean_tokens else None,
        "extrapolated_full_run": {
            "items": CALIBRATION_ITEMS,
            "estimated_tokens": round(mean_tokens * CALIBRATION_ITEMS) if mean_tokens else None,
            "daily_free_tier_tokens": 200_000,
            "fits_in_one_day": (mean_tokens * CALIBRATION_ITEMS < 200_000) if mean_tokens else None,
            "note": "measured from this probe, not assumed; one call per reply, never batched",
        },
        "rate_limit_headers": rate_limit_headers(judge_cfg["name"]),
        "header_caveat": "x-ratelimit-* report PER-MINUTE capacity and look healthy even when the "
                         "daily token budget is exhausted (DECISIONS [P7]), so a successful probe "
                         "is not evidence that a full run will fit.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    probe_file = OUT / "probe.json"
    history = json.loads(probe_file.read_text()) if probe_file.exists() else {"runs": []}
    history.setdefault("runs", []).append(manifest)
    probe_file.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {(OUT / 'probe.json').relative_to(ROOT)}: {len(results)} ok, {len(failures)} "
          f"failed, {manifest['schema_repairs']} schema repair(s), "
          f"~{manifest['mean_total_tokens']} tokens/call")


if __name__ == "__main__":
    main()
