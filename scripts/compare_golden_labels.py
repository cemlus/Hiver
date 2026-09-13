"""Compare the locked human gold labels with the blind LLM second opinion, and build the
adjudication workflow (label layer 3).

Run from the repo root:
    uv run python scripts/compare_golden_labels.py            # report + adjudication template
    uv run python scripts/compare_golden_labels.py --finalize # write golden_final.csv

Reads (never writes) data/golden/golden_labeling_sheet.csv, the primary human gold, and
data/golden/golden_llm_labels.csv. Writes:
  results/golden/human_vs_llm.md    agreement per scored field (percent and Cohen's kappa),
                                    confusion tables, and every disagreement with its message
  data/golden/golden_adjudication.csv  one row per disagreement, with blank `final`, `decided_by`
                                    and `rationale` for a human to fill. Existing rows are kept.
  data/golden/golden_final.csv      (--finalize) the human labels with adjudicated overrides
                                    applied, generated only when every disagreement is resolved.

Rules this script enforces:
- the human sheet is never modified, and its hash must match golden.lock;
- `final` may only be the human value, the LLM value, or a third value the adjudicator writes;
- an unresolved disagreement blocks --finalize, so no label is changed silently.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.dataprep.loaders import eval_pool  # noqa: E402

GOLDEN = ROOT / "data" / "golden"
OUT = ROOT / "results" / "golden" / "human_vs_llm.md"
ADJUDICATION = GOLDEN / "golden_adjudication.csv"
FINAL = GOLDEN / "golden_final.csv"
FIELDS = ["conversation_state", "intent", "escalate", "label_confidence"]
SCORED = ["conversation_state", "intent", "escalate"]      # label_confidence is metadata, not a label
ADJ_COLUMNS = ["golden_id", "field", "human", "llm", "final", "decided_by", "rationale"]


def read_csv(path: Path) -> pd.DataFrame:
    """Read a label file exactly as written (invalid bytes replaced, never rewritten)."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)


def human_labels() -> pd.DataFrame:
    sheet = GOLDEN / "golden_labeling_sheet.csv"
    lock = GOLDEN / "golden.lock"
    if lock.exists():
        digest = hashlib.sha256(sheet.read_bytes()).hexdigest()
        if digest != lock.read_text().split()[0]:
            sys.exit(f"{sheet.name} does not match golden.lock: the primary human labels changed.")
    elif not lock.exists():
        sys.exit("golden.lock is missing: lock the human labels before comparing.")
    return read_csv(sheet)


def agreement_rows(human: pd.DataFrame, llm: pd.DataFrame) -> list[list[str]]:
    rows = []
    for field in FIELDS:
        h, m = human[field].str.strip(), llm[field].str.strip()
        same = int((h == m).sum())
        kappa = cohen_kappa_score(h, m) if h.nunique() > 1 and m.nunique() > 1 else float("nan")
        rows.append([f"`{field}`", f"{same}/{len(h)} ({same / len(h):.0%})", f"{kappa:.2f}"])
    both = (human[SCORED].apply(lambda s: s.str.strip()) == llm[SCORED].apply(lambda s: s.str.strip())).all(axis=1)
    rows.append(["**all three scored fields**", f"{int(both.sum())}/{len(both)} ({both.mean():.0%})", "—"])
    return rows


def confusion(human: pd.Series, llm: pd.Series, title: str) -> list[str]:
    table = pd.crosstab(human.str.strip().replace("", "(none)"), llm.str.strip().replace("", "(none)"))
    header = ["human \\ LLM", *[f"`{c}`" for c in table.columns]]
    lines = [f"**{title}**", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for value, row in table.iterrows():
        lines.append(f"| `{value}` | " + " | ".join(str(v) for v in row) + " |")
    return lines + [""]


def disagreements(human: pd.DataFrame, llm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h, m in zip(human.to_dict("records"), llm.to_dict("records")):
        for field in SCORED:
            if h[field].strip() != m[field].strip():
                rows.append({"golden_id": h["golden_id"], "field": field,
                             "human": h[field].strip(), "llm": m[field].strip(),
                             "final": "", "decided_by": "", "rationale": ""})
    return pd.DataFrame(rows, columns=ADJ_COLUMNS)


def merge_adjudication(fresh: pd.DataFrame) -> pd.DataFrame:
    """Keep decisions already made; add rows for new disagreements; never drop a resolved row."""
    if not ADJUDICATION.exists():
        return fresh
    old = read_csv(ADJUDICATION)
    merged = fresh.merge(old, on=["golden_id", "field"], how="left", suffixes=("", "_old"))
    for column in ("final", "decided_by", "rationale"):
        merged[column] = merged[f"{column}_old"].fillna("").where(
            merged[f"{column}_old"].notna(), merged[column])
    return merged[ADJ_COLUMNS]


def finalize(human: pd.DataFrame, adjudication: pd.DataFrame) -> pd.DataFrame:
    unresolved = adjudication[adjudication["final"].str.strip() == ""]
    if len(unresolved):
        sys.exit(f"{len(unresolved)} unresolved disagreement(s) in {ADJUDICATION.name}: "
                 f"fill `final` (and `decided_by`, `rationale`) for "
                 f"{', '.join(unresolved['golden_id'] + '/' + unresolved['field'])}")
    final = human.copy()
    final.insert(len(final.columns), "adjudicated", "")
    by_id = final.set_index("golden_id")
    for row in adjudication.to_dict("records"):
        gid, field = row["golden_id"], row["field"]
        by_id.at[gid, field] = row["final"].strip()
        by_id.at[gid, "adjudicated"] = (by_id.at[gid, "adjudicated"] + f" {field}").strip()
    return by_id.reset_index()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--finalize", action="store_true", help="write golden_final.csv")
    args = parser.parse_args()

    human = human_labels()
    llm_path = GOLDEN / "golden_llm_labels.csv"
    if not llm_path.exists():
        sys.exit(f"{llm_path.name} is missing: run scripts/llm_second_opinion.py first.")
    llm = read_csv(llm_path)
    missing = set(human["golden_id"]) - set(llm["golden_id"])
    if missing:
        sys.exit(f"the LLM second opinion is incomplete ({len(missing)} items missing, e.g. "
                 f"{sorted(missing)[0]}): rerun scripts/llm_second_opinion.py.")
    llm = llm.set_index("golden_id").loc[human["golden_id"]].reset_index()

    fresh = merge_adjudication(disagreements(human, llm))
    ADJUDICATION.parent.mkdir(parents=True, exist_ok=True)
    fresh.to_csv(ADJUDICATION, index=False)

    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str)).set_index("record_id")
    text = {r["golden_id"]: pool.loc[r["record_id"], "customer_text_clean"] for r in human.to_dict("records")}
    reason = dict(zip(llm["golden_id"], llm["rationale"]))

    lines = ["# Golden labels: human vs LLM second opinion", "",
             "_Generated by `uv run python scripts/compare_golden_labels.py`. The human labels are the "
             "locked primary gold layer and are never modified here. The LLM is a blind second opinion; "
             "disagreements are resolved in `data/golden/golden_adjudication.csv`._", "",
             f"Human labeller: the project owner. LLM: `{llm['model'].iloc[0]}`, codebook "
             f"`{llm['codebook_version'].iloc[0]}`.", "",
             "## Agreement", "",
             "| field | agreement | Cohen's κ |", "|---|---|---|"]
    lines += ["| " + " | ".join(row) + " |" for row in agreement_rows(human, llm)]
    lines += ["", "Cohen's κ corrects for agreement by chance. `label_confidence` is metadata, not a "
              "scored label. Single-labeller self-consistency was not measured, so this is the only "
              "labelling-reliability evidence available.", "",
              "## Confusion", ""]
    lines += confusion(human["conversation_state"], llm["conversation_state"], "conversation_state")
    lines += confusion(human["escalate"], llm["escalate"], "escalate")
    lines += ["## Disagreements to adjudicate", "",
              f"{len(fresh)} across {fresh['golden_id'].nunique()} items "
              f"({len(fresh[fresh['final'].str.strip() != ''])} already resolved).", "",
              "| item | field | human | LLM | message | LLM's reason |", "|---|---|---|---|---|---|"]
    for row in fresh.to_dict("records"):
        message = " ".join(str(text[row["golden_id"]]).split())[:110].replace("|", "/")
        why = " ".join(str(reason.get(row["golden_id"], "")).split())[:110].replace("|", "/")
        lines.append(f"| {row['golden_id']} | {row['field']} | `{row['human'] or '(none)'}` | "
                     f"`{row['llm'] or '(none)'}` | {message} | {why} |")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} and {ADJUDICATION.relative_to(ROOT)} "
          f"({len(fresh)} disagreements over {fresh['golden_id'].nunique()} items)")

    if args.finalize:
        final = finalize(human, fresh)
        final.to_csv(FINAL, index=False)
        print(f"wrote {FINAL.relative_to(ROOT)}: {int((final['adjudicated'] != '').sum())} items "
              "changed by adjudication")


if __name__ == "__main__":
    main()
