"""Build the blind human rating sheet for judge calibration, then stop.

Run from the repo root:   uv run python scripts/make_rating_sheet.py

Human-first, exactly as the golden labels were done: the project owner rates every drafted reply
before the judge is ever run, and the sheet is then locked by SHA-256. The judge never sees these
ratings, and this script never writes or reads a judge score.

Writes:
  data/golden/dev_human_judgments.csv   the sheet to fill in (blank score columns)
  data/golden/dev_human_judgments.md    the reading copy: message, evidence, reference, draft
  results/eval/judge_calibration/rubric_<version>.md   the rubric, rendered from the code constant

Dev only. The golden set is never loaded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eval.judge import DIMENSIONS, JUDGE_RUBRIC_VERSION, rubric_markdown   # noqa: E402

DRAFTS = ROOT / "results" / "eval" / "dev_drafts.jsonl"
GOLDEN = ROOT / "data" / "golden"
OUT = ROOT / "results" / "eval" / "judge_calibration"
SHEET = GOLDEN / "dev_human_judgments.csv"
READING = GOLDEN / "dev_human_judgments.md"
COLUMNS = ["dev_id", *DIMENSIONS, "unsupported_claims", "escalation_appropriate", "notes"]


def main() -> None:
    if not DRAFTS.exists():
        sys.exit(f"{DRAFTS.relative_to(ROOT)} is missing: run scripts/draft_dev_replies.py "
                 "(LLM_OFFLINE=1 replays it from cache for free).")
    rows = [json.loads(line) for line in DRAFTS.open(encoding="utf-8")]
    drafted = [r for r in rows if (r.get("draft") or "").strip()]
    if not drafted:
        sys.exit("no drafted replies found: nothing to rate.")

    if SHEET.exists():
        existing = pd.read_csv(SHEET, dtype=str, keep_default_na=False)
        if any(existing[d].astype(str).str.strip().any() for d in DIMENSIONS):
            sys.exit(f"{SHEET.relative_to(ROOT)} already has ratings in it. Refusing to overwrite "
                     "human work; delete it deliberately if you really mean to start over.")

    sheet = pd.DataFrame([{c: "" for c in COLUMNS} | {"dev_id": r["id"]} for r in drafted],
                         columns=COLUMNS)
    sheet.to_csv(SHEET, index=False)

    lines = [f"# Reply-quality rating sheet ({len(drafted)} items, rubric {JUDGE_RUBRIC_VERSION})",
             "",
             "Rate every item in `dev_human_judgments.csv`: five dimensions scored 1-5, plus the two "
             "yes/no flags. The rubric is below the items.", "",
             "**Rate these before looking at any model's scores.** The judge has not been run yet, "
             "and once you are finished this sheet is locked by SHA-256 so the comparison stays "
             "honest.", "",
             "The brand's real historical reply is shown for context. It is a **reference, not the "
             "right answer** -- it is often a canned \"please DM us\" deflection, and a draft that "
             "differs from it may be better.", "", "---", ""]
    for r in drafted:
        lines += [f"## {r['id']}", "",
                  f"**Customer wrote:** {r['message']}", "",
                  f"**The agent's drafted reply:** {r['draft']}", "",
                  f"**Brand's historical reply (reference, not gold):** "
                  f"{r.get('reference_reply') or '(none)'}", "",
                  f"_Routing: {r.get('state', '?')} / {r.get('intent') or '-'} · evidence used: "
                  f"{', '.join(r.get('retrieved_ids') or []) or 'none'} · reply_template_in_train: "
                  f"{r.get('reply_template_in_train')}_", "", "---", ""]
    lines += [rubric_markdown()]
    READING.write_text("\n".join(lines), encoding="utf-8")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"rubric_{JUDGE_RUBRIC_VERSION}.md").write_text(rubric_markdown(), encoding="utf-8")

    print(f"wrote {SHEET.relative_to(ROOT)} ({len(drafted)} rows, blank) and "
          f"{READING.relative_to(ROOT)}")
    print("\nNext: fill in the CSV, then the sheet gets locked before the judge runs.")


if __name__ == "__main__":
    main()
