"""Read-only check of the primary human golden labels against the frozen codebook.

Run from the repo root:   uv run python scripts/check_golden_labels.py

Reads data/golden/golden_labeling_sheet.csv and golden_sample_key.csv plus the frozen
data/taxonomy/taxonomy_v1.yaml. Writes results/golden/label_check.md and prints a summary.

**This script never edits the sheet.** The human labels are the primary gold layer: only the
labeller changes them (see data/golden/LABELING.md). Everything below is either a blocking problem
to hand back to the labeller, or a note for the adjudication step later.
"""
from __future__ import annotations

import io
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "data" / "golden"
OUT = ROOT / "results" / "golden" / "label_check.md"
SPEC = ROOT / "data" / "taxonomy" / "taxonomy_v1.yaml"
SCORED = ["conversation_state", "intent", "escalate", "label_confidence"]
CONFIDENCE = ["high", "medium", "low"]
ALWAYS_ESCALATE = ["purchases_billing_orders", "support_process_complaint"]


def clean(value: str) -> str:
    """The label as written, minus surrounding whitespace."""
    return str(value).strip()


def odd_characters(value: str) -> str:
    """Characters that shouldn't be in a label: non-ASCII, or control characters."""
    bad = [c for c in value if ord(c) > 126 or (ord(c) < 32 and c not in "\t")]
    return ", ".join(f"U+{ord(c):04X} ({unicodedata.name(c, 'unnamed')})" for c in bad)


def read_sheet() -> tuple[pd.DataFrame, list]:
    """Read the human sheet without touching it. Invalid UTF-8 bytes are replaced and reported, so
    one stray byte (a non-breaking space pasted into a cell, say) can't stop the check."""
    raw = (GOLDEN / "golden_labeling_sheet.csv").read_bytes()
    problems = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        text = raw.decode("utf-8", errors="replace")
        problems.append(("—", "encoding", f"the file is not valid UTF-8 ({exc}); the offending bytes "
                                          "show up as U+FFFD in the rows below"))
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False), problems


def check(sheet: pd.DataFrame, key: pd.DataFrame, spec: dict) -> tuple[list, list]:
    states = [s["name"] for s in spec["conversation_states"]]
    intents = [it["name"] for it in spec["intents"]]
    no_intent = set(spec["states_without_intent"])
    blocking, notes = [], []

    if list(sheet["golden_id"]) != list(key["golden_id"]) or list(sheet["record_id"]) != list(key["record_id"]):
        blocking.append(("—", "rows", "the sheet's golden_id / record_id no longer match "
                                     "golden_sample_key.csv (rows reordered, added or removed)"))
    missing_cols = [c for c in SCORED if c not in sheet.columns]
    if missing_cols:
        blocking.append(("—", "columns", f"missing scored column(s): {', '.join(missing_cols)}"))
        return blocking, notes

    for r in sheet.to_dict("records"):
        gid = r["golden_id"]
        state, intent = clean(r["conversation_state"]), clean(r["intent"])
        escalate, confidence = clean(r["escalate"]), clean(r["label_confidence"])
        for field, value in (("conversation_state", state), ("intent", intent),
                             ("escalate", escalate), ("label_confidence", confidence)):
            odd = odd_characters(value)
            if odd:
                blocking.append((gid, field, f"`{value}` contains {odd}"))
        if state not in states:
            blocking.append((gid, "conversation_state", f"`{state or '(blank)'}` is not one of the 4 states"))
        elif (state in no_intent) != (intent == ""):
            blocking.append((gid, "intent", f"state `{state}` needs intent "
                                            f"{'blank' if state in no_intent else 'filled'}, got `{intent or '(blank)'}`"))
        if intent and intent not in intents and not odd_characters(intent):
            blocking.append((gid, "intent", f"`{intent}` is not one of the 11 intents"))
        if escalate not in ("yes", "no"):
            blocking.append((gid, "escalate", f"`{escalate or '(blank)'}` is not yes / no"))
        if confidence not in CONFIDENCE:
            blocking.append((gid, "label_confidence", f"`{confidence or '(blank)'}` is not high / medium / low"))
        if intent in ALWAYS_ESCALATE and escalate == "no":
            notes.append((gid, "policy", f"`{intent}` always escalates under the frozen policy (rule b), "
                                         "but this is labelled `no`"))
    return blocking, notes


def distributions(sheet: pd.DataFrame, key: pd.DataFrame) -> list[str]:
    df = sheet.merge(key[["golden_id", "slice"]], on="golden_id")
    df["group"] = df["slice"].str.startswith("stratified").map({True: "stratified", False: "random"})
    lines = []
    for field in ("conversation_state", "intent", "escalate", "label_confidence"):
        counts = pd.crosstab(df[field].map(clean).replace("", "(blank)"), df["group"])
        for col in ("random", "stratified"):
            if col not in counts:
                counts[col] = 0
        counts["total"] = counts["random"] + counts["stratified"]
        counts = counts.sort_values("total", ascending=False)
        lines += [f"**{field}**", "", "| value | random (120) | stratified (80) | total |", "|---|---|---|---|"]
        lines += [f"| `{v}` | {r['random']} | {r['stratified']} | {r['total']} |" for v, r in counts.iterrows()]
        lines.append("")
    return lines


def main() -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    sheet, encoding_problems = read_sheet()
    key = pd.read_csv(GOLDEN / "golden_sample_key.csv", dtype=str)
    blocking, notes = check(sheet, key, spec)
    blocking = encoding_problems + blocking

    lines = ["# Golden labels: check against the frozen codebook", "",
             "_Generated by `uv run python scripts/check_golden_labels.py`, which never edits the sheet. "
             "Blocking problems go back to the labeller; the notes are for the adjudication step._", "",
             f"Rows: {len(sheet)}. Columns present: {', '.join(f'`{c}`' for c in sheet.columns)}.", "",
             "## Blocking problems", ""]
    lines += ([f"- **{gid}** · `{field}`: {text}" for gid, field, text in blocking] or ["None."])
    lines += ["", "## Notes for adjudication (not errors)", ""]
    lines += ([f"- **{gid}** · {field}: {text}" for gid, field, text in notes] or ["None."])
    lines += ["", "## Distributions", ""] + distributions(sheet, key)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(blocking)} blocking, {len(notes)} notes")
    for gid, field, text in blocking:
        print(f"  BLOCKING {gid} {field}: {text}")
    for gid, field, text in notes:
        print(f"  note     {gid} {field}: {text}")


if __name__ == "__main__":
    main()
