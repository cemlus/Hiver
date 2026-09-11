"""Phase 3 aids for the intent taxonomy. Exploration and rendering only: no classifier.

Everything reads the train split only, through src/dataprep/loaders.py.

  uv run python scripts/taxonomy_explore.py sample   # open-coding sheet: 150 random train exchanges
  uv run python scripts/taxonomy_explore.py topics   # exploratory NMF topics (evidence only)
  uv run python scripts/taxonomy_explore.py search "refund|charged" [--n 15]   # find examples
  uv run python scripts/taxonomy_explore.py render   # proposal + codebook from the hand-written spec

`render` combines two hand-written files:
  data/taxonomy/taxonomy_v1.yaml             states, intents, risk rules, tie-breaks, scoring, examples
  data/taxonomy/discovery_sample_coding.csv  the 150-exchange discovery sample, coded by hand
and writes results/taxonomy/proposal.md (evidence) and data/codebook.md (labeller guide).
Examples are copied verbatim from the records; counts are estimated from the discovery sample.
"""
from __future__ import annotations

import argparse
import math
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config  # noqa: E402
from src.dataprep.loaders import load  # noqa: E402
from validate_brand import GENERIC_WORDS  # noqa: E402  (scripts/validate_brand.py)

OUT = ROOT / "results" / "taxonomy"
SPEC = ROOT / "data" / "taxonomy" / "taxonomy_v1.yaml"
CODING = ROOT / "data" / "taxonomy" / "discovery_sample_coding.csv"
CODEBOOK = ROOT / "data" / "codebook.md"
N_SAMPLE = 150
N_TOPICS = 15
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def short(text, limit: int = 220) -> str:
    text = str(text).replace("\n", " ").replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def cell(text) -> str:
    """Text safe for a markdown table cell."""
    return str(text).replace("\n", " ").replace("|", "\\|")


def exchange_lines(r, with_reply: bool = False) -> list[str]:
    """An exchange as markdown bullets: context turns, the message, optionally the reply."""
    lines = [f"  - _{t['role']}_: {short(t['text'])}" for t in r["context"]]
    lines.append(f"  - **customer:** {short(r['customer_text_clean'], 450)}")
    if with_reply:
        lines.append(f"  - _historical reply (strategy evidence only; code from message + context):_ "
                     f"{short(r['brand_reply_clean'], 320)}")
    return lines


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion k/n."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def split_list(value: str) -> list[str]:
    return [x.strip() for x in value.split(";") if x.strip()]


# --------------------------------------------------------------------------- exploration

def cmd_sample(train: pd.DataFrame, seed: int) -> None:
    s = train.sample(N_SAMPLE, random_state=seed).sort_values("created_at")
    lines = [
        "# Open-coding sample (train only)",
        "",
        f"_{N_SAMPLE} random train exchanges (seed {seed}), from `scripts/taxonomy_explore.py sample`. "
        "Taxonomy discovery evidence, not gold labels. Code each one from the customer message **and "
        "its context**; the historical reply is shown only as evidence of how the brand handled it. "
        f"Codes go in `{CODING.relative_to(ROOT)}`._",
        "",
    ]
    for i, r in enumerate(s.to_dict("records"), 1):
        kind = "follow-up" if r["is_followup"] else "first contact"
        lines += [f"**O{i:03d}** · `{r['record_id']}` · {kind} · reply_type={r['reply_type']}"]
        lines += exchange_lines(r, with_reply=True)
        lines.append("")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "open_coding_sample.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT / 'open_coding_sample.md'}")


def cmd_search(train: pd.DataFrame, pattern: str, n: int, seed: int) -> None:
    pattern = pattern.replace("(?:", "(").replace("(", "(?:")   # no capture groups (pandas warns)
    hits = train[train["customer_text_clean"].str.contains(pattern, case=False, regex=True)]
    print(f"{len(hits):,} of {len(train):,} train exchanges match /{pattern}/")
    for r in hits.sample(min(n, len(hits)), random_state=seed).to_dict("records"):
        print(f"- `{r['record_id']}` · {'follow-up' if r['is_followup'] else 'first contact'}")
        print("\n".join(exchange_lines(r)))


def cmd_topics(train: pd.DataFrame, seed: int) -> None:
    fc = train[~train["is_followup"]]
    vec = TfidfVectorizer(stop_words=list(ENGLISH_STOP_WORDS.union(GENERIC_WORDS)), min_df=5,
                          max_df=0.3, ngram_range=(1, 2), sublinear_tf=True,
                          token_pattern=r"[a-z][a-z']{2,}")
    X = vec.fit_transform(fc["customer_text_clean"])
    nmf = NMF(n_components=N_TOPICS, init="nndsvda", random_state=seed, max_iter=400)
    W = nmf.fit_transform(X)
    label = np.where(W.max(axis=1) < 1e-3, -1, W.argmax(axis=1))
    terms = np.array(vec.get_feature_names_out())
    rng = np.random.default_rng(seed)
    order = sorted(range(N_TOPICS), key=lambda k: -(label == k).sum())
    lines = [
        "# Exploratory topics (train first contacts)",
        "",
        f"_NMF with {N_TOPICS} topics over TF-IDF (1–2 grams; English stop words and generic "
        f"support words removed) of the {len(fc):,} train first-contact messages, seed {seed}. "
        f"Each message is assigned to its strongest topic; {(label == -1).mean():.1%} match none. "
        "**Exploratory evidence only**: topics group words, not support strategies, and the "
        "taxonomy is curated by hand around distinct response and escalation strategies._",
        "",
    ]
    for k in order:
        members = fc[label == k]
        top = ", ".join(terms[np.argsort(nmf.components_[k])[::-1][:10]])
        lines += [f"## Topic {k}: {len(members):,} ({len(members) / len(fc):.1%})", "", f"Top terms: {top}", ""]
        for i in rng.choice(len(members), size=min(3, len(members)), replace=False):
            lines.append(f"- `{members.iloc[i]['record_id']}`: {short(members.iloc[i]['customer_text_clean'])}")
        lines.append("")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "topics.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT / 'topics.md'}")


# --------------------------------------------------------------------------- render

def validate(spec: dict, coding: pd.DataFrame, train_ids: set[str]) -> None:
    intents = {it["name"]: it for it in spec["intents"]}
    states = {s["name"] for s in spec["conversation_states"]}
    no_intent = set(spec["states_without_intent"])
    assert set(coding["conversation_state"]) <= states, "unknown conversation_state in coding"
    has_intent = coding["intent"] != ""
    wrong = coding[has_intent == coding["conversation_state"].isin(no_intent)]
    assert wrong.empty, f"intent must be blank exactly for {no_intent}: {wrong['sample_no'].tolist()}"
    assert set(coding.loc[has_intent, "intent"]) <= set(intents), "unknown intent in coding"
    assert set(coding["alt_intent"]) - {""} <= set(intents), "unknown alt_intent in coding"
    for row in coding[coding["subtype"] != ""].itertuples():
        assert row.subtype in intents[row.intent].get("subtypes", {}), f"{row.sample_no}: bad subtype"
    for row in coding[coding["secondary_intents"] != ""].itertuples():
        assert row.intent, f"{row.sample_no}: secondary intents need a primary intent"
        for sec in split_list(row.secondary_intents):
            assert sec in intents and sec != row.intent, f"{row.sample_no}: bad secondary {sec}"
            # T0: the primary is the higher-risk issue, so no secondary may outrank it.
            assert RISK_ORDER[intents[sec]["default_risk"]] <= RISK_ORDER[intents[row.intent]["default_risk"]], \
                f"{row.sample_no}: T0 violated ({sec} outranks {row.intent})"
    assert set(coding["event_tag"]) - {""} <= set(spec["events"]), "unknown event_tag in coding"
    ids = list(coding["record_id"])
    ids += [str(x) for group in spec["intents"] + spec["conversation_states"] + spec["tie_breaks"]
            for x in group.get("examples", [])]
    missing = sorted(set(ids) - train_ids)
    assert not missing, f"IDs not in the train split: {missing}"
    for tb in spec["tie_breaks"]:
        assert set(tb["between"]) <= set(intents) | states, f"{tb['id']}: unknown names"
    assert all(it["default_risk"] in RISK_ORDER for it in spec["intents"])
    assert {row[1] for row in spec["s1_examples"]} <= states


def estimates(coding: pd.DataFrame, column: str, names: list[str], n_train: int) -> dict[str, dict]:
    n = len(coding)
    out = {}
    for name in names:
        k = int((coding[column] == name).sum())
        lo, hi = wilson(k, n)
        out[name] = {"k": k, "share": f"{k / n:.1%}", "est": f"≈ {round(k / n * n_train, -1):,.0f}",
                     "range": f"{round(lo * n_train, -1):,.0f} – {round(hi * n_train, -1):,.0f}"}
    return out


def confusables(spec: dict, coding: pd.DataFrame) -> tuple[dict[str, list[str]], dict[frozenset, int]]:
    """Top confusable intents per intent: tie-break partners, ranked by pairs seen in coding."""
    pairs = coding[(coding["intent"] != "") & (coding["alt_intent"] != "")]
    seen: dict[frozenset, int] = {}
    for a, b in zip(pairs["intent"], pairs["alt_intent"]):
        seen[frozenset((a, b))] = seen.get(frozenset((a, b)), 0) + 1
    names = {it["name"] for it in spec["intents"]}
    partners: dict[str, set[str]] = {n: set() for n in names}
    for tb in spec["tie_breaks"]:
        between = [x for x in tb["between"] if x in names]
        for a, b in combinations(between, 2):
            partners[a].add(b)
            partners[b].add(a)
    top = {n: [f"`{p}` ({seen.get(frozenset((n, p)), 0)})"
               for p in sorted(partners[n], key=lambda p: (-seen.get(frozenset((n, p)), 0), p))[:3]]
           for n in names}
    return top, seen


def final_table(spec: dict, est: dict, top: dict) -> list[str]:
    head = ["intent", "definition", "include", "exclude", "est. train count (95% range)",
            "response strategy", "default risk", "default escalation", "top confusable (seen in coding)"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for it in spec["intents"]:
        e = est[it["name"]]
        lines.append("| " + " | ".join(cell(v) for v in [
            f"`{it['name']}`", it["definition"], "; ".join(it["include"]), "; ".join(it["exclude"]),
            f"{e['est']} ({e['range']})", it["strategy"], it["default_risk"], it["escalation_short"],
            ", ".join(top[it["name"]]) or "—"]) + " |")
    return lines


def s1_table(spec: dict) -> list[str]:
    lines = ["**S1 made explicit:** `acknowledgement_closing` requires that no unresolved support issue "
             "remains.", "", "| customer says | state | why |", "|---|---|---|"]
    lines += [f"| \"{cell(m)}\" | `{s}` | {cell(w)} |" for m, s, w in spec["s1_examples"]]
    return lines


def tie_break_lines(spec: dict, seen: dict) -> list[str]:
    lines = ["Apply in this order: S1–S2 decide the state, T0 picks the primary intent of a multi-issue "
             "message, T1–T11 settle between two intents, and T12 comes last. `seen` = how often the "
             "pair appeared as (chosen, runner-up) in the discovery sample.", ""]
    intents = {it["name"] for it in spec["intents"]}
    for tb in spec["tie_breaks"]:
        pair = " vs ".join(f"`{x}`" for x in tb["between"]) or "any two intents"
        # Coding records (intent, runner-up) pairs only, so counts exist for intent-vs-intent rules.
        is_intent_pair = len(tb["between"]) == 2 and set(tb["between"]) <= intents
        count = f" (seen {seen.get(frozenset(tb['between']), 0)})" if is_intent_pair else ""
        ex = ", ".join(f"`{x}`" for x in tb.get("examples", []))
        lines.append(f"- **{tb['id']}**: {pair}{count}. {tb['rule']}" + (f" _Examples: {ex}._" if ex else ""))
    return lines


def risk_lines(spec: dict) -> list[str]:
    lines = [f"_Escalation policy status: **{spec['escalation_status'].upper()}**._", "",
             "| level | meaning |", "|---|---|"]
    lines += [f"| `{k}` | {cell(v)} |" for k, v in spec["risk_levels"].items()]
    lines += ["", "| rule | fires when | Phase 2 signal (weak cue) | raises risk to | reason code |",
              "|---|---|---|---|---|"]
    lines += [f"| `{r[0]}` | {cell(r[1])} | {r[2]} | `{r[3]}` | `{r[4]}` |" for r in spec["risk_rules"]]
    lines += ["", *[f"- {x}" for x in spec["escalation_combination"]]]
    return lines


def examples_block(ids, by_id: pd.DataFrame) -> list[str]:
    lines = []
    for rid in ids:
        r = by_id.loc[str(rid)]
        lines.append(f"- `{rid}` · {'follow-up' if r['is_followup'] else 'first contact'}")
        lines += exchange_lines(r)
    return lines


def internal_lines(spec: dict, coding: pd.DataFrame) -> list[str]:
    coded = coding[coding["intent"] != ""]
    lines = ["_Internal notes for analysis only. `secondary_intents`, subtypes and event tags are "
             "**not** benchmark labels and are never scored._", "",
             "**Secondary intents in the discovery sample** (multi-issue messages; T0 picked the primary)", ""]
    multi = coded[coded["secondary_intents"] != ""]
    lines += [f"- `{r.record_id}`: primary `{r.intent}`, secondary "
              + ", ".join(f"`{s}`" for s in split_list(r.secondary_intents)) for r in multi.itertuples()]
    lines += ["", f"{len(multi)} of {len(coded)} intent-bearing exchanges raised more than one issue.", "",
              "**Subtypes in the discovery sample**", ""]
    for it in spec["intents"]:
        if not it.get("subtypes"):
            continue
        rows = coded[coded["intent"] == it["name"]]
        counts = ", ".join(f"`{s}` {int((rows['subtype'] == s).sum())}" for s in it["subtypes"])
        lines.append(f"- `{it['name']}` ({len(rows)} coded): {counts}; untagged "
                     f"{int((rows['subtype'] == '').sum())}")
    lines += ["", "**Event tags** (train-period events; a temporal-generalization risk because the "
              "holdout covers 15 Nov – 3 Dec 2017)", "",
              "| event | definition | coded rows | intents / states |", "|---|---|---|---|"]
    for tag, definition in spec["events"].items():
        rows = coding[coding["event_tag"] == tag]
        where = rows["intent"].where(rows["intent"] != "", rows["conversation_state"]).value_counts()
        lines.append(f"| `{tag}` | {cell(definition)} | {len(rows)} | "
                     + ", ".join(f"{k} {v}" for k, v in where.items()) + " |")
    lines += ["", "Share of each intent's coded rows that are tied to a train-period event:", ""]
    for it in spec["intents"]:
        rows = coded[coded["intent"] == it["name"]]
        tied = int((rows["event_tag"] != "").sum())
        lines.append(f"- `{it['name']}`: {tied} of {len(rows)}")
    return lines


def cmd_render(train: pd.DataFrame) -> None:
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    coding = pd.read_csv(CODING, dtype=str).fillna("")
    by_id = train.set_index("record_id")
    validate(spec, coding, set(by_id.index))

    n, n_train = len(coding), len(train)
    intent_names = [it["name"] for it in spec["intents"]]
    state_names = [s["name"] for s in spec["conversation_states"]]
    est = estimates(coding, "intent", intent_names, n_train)
    state_est = estimates(coding, "conversation_state", state_names, n_train)
    top, seen = confusables(spec, coding)
    n_intent = int((coding["intent"] != "").sum())
    rel = lambda p: p.relative_to(ROOT)  # noqa: E731

    state_table = ["| state | carries an intent | definition | in sample | est. train count (95% range) | strategy |",
                   "|---|---|---|---|---|---|"]
    for s in spec["conversation_states"]:
        e = state_est[s["name"]]
        state_table.append(f"| `{s['name']}` | {'no' if s['name'] in spec['states_without_intent'] else 'yes'} | "
                           f"{cell(s['definition'])} | {e['k']} / {n} | {e['est']} ({e['range']}) | {cell(s['strategy'])} |")

    # ---- proposal.md: the evidence
    p = [
        f"# Intent taxonomy ({spec['version']})",
        "",
        f"> **{spec['status']}** Rendered by `scripts/taxonomy_explore.py render` from "
        f"`{rel(SPEC)}` and `{rel(CODING)}`. The labeller-facing codebook is `{rel(CODEBOOK)}`. "
        "No classifier exists yet.",
        "",
        f"> **Evidence status.** {spec['evidence_status']}",
        "",
        *spec["preamble"],
        "",
        "## Final table (v1)",
        "",
        f"Estimates are `k / {n} × {n_train:,}` train exchanges (95% Wilson range); the sample is too "
        f"small to resolve intents under ~2%. {n_intent} of the {n} sampled exchanges carry an "
        "intent; the rest are closing or social messages (see conversation states). Default risk and "
        "escalation are a separate layer and are still DRAFT.",
        "",
        *final_table(spec, est, top),
        "",
        "## Conversation states",
        "",
        "Every exchange gets a state. Only `new_issue` and `issue_followup` carry a primary intent; "
        "the other two sit outside the intent benchmark and are scored as state accuracy.",
        "",
        *state_table,
        "",
        *s1_table(spec),
        "",
    ]
    for s in spec["conversation_states"]:
        p += [f"**`{s['name']}` examples**", "", *examples_block(s["examples"], by_id), ""]
    for i, it in enumerate(spec["intents"], 1):
        e = est[it["name"]]
        p += [
            f"## {i}. `{it['name']}`",
            "",
            f"**Definition.** {it['definition']}",
            "",
            "**Include**", *[f"- {x}" for x in it["include"]], "",
            "**Exclude**", *[f"- {x}" for x in it["exclude"]], "",
            f"**Response strategy.** {it['strategy']}",
            "",
            f"**Default risk.** `{it['default_risk']}`. **Default escalation (draft).** {it['escalation']}",
            "",
            f"**Estimated training count.** {e['est']} (95% range {e['range']}; {e['k']} of {n} in the "
            "discovery sample).",
            "",
            f"**Top confusable intents** (pairs seen in coding): {', '.join(top[it['name']]) or '—'}",
            "",
        ]
        if it.get("subtypes"):
            p += ["**Internal subtypes** (never scored): "
                  + "; ".join(f"`{k}`: {v}" for k, v in it["subtypes"].items()), ""]
        p += ["**Representative examples** (train; context shown where present):", "",
              *examples_block(it["examples"], by_id), ""]
    p += ["## Deterministic tie-break rules", "", *tie_break_lines(spec, seen), "",
          "## Risk and escalation (a layer on top of intent)", "", *risk_lines(spec), "",
          "## Escalation calibration plan (dev set)", "", *spec["calibration"], "",
          "## How the golden set will be scored", "", *spec["scoring"], "",
          "## Internal fields: secondary intents, subtypes, events", "", *internal_lines(spec, coding), "",
          "## Exploratory topic evidence", "", *spec["topic_evidence"], "",
          "## Remaining risks", "", *[f"- {q}" for q in spec["open_questions"]], ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "proposal.md").write_text("\n".join(p), encoding="utf-8")

    # ---- codebook.md: what a labeller follows
    c = [
        f"# Codebook ({spec['version']})",
        "",
        f"> **{spec['status']}** Generated from `{rel(SPEC)}` by `scripts/taxonomy_explore.py render`; "
        f"edit the YAML, not this file. The evidence behind it is in `{rel(OUT / 'proposal.md')}`.",
        "",
        f"> **Evidence status.** {spec['evidence_status']}",
        "",
        "## Label fields",
        "",
        "| field | when | values |",
        "|---|---|---|",
        *[f"| `{f}` | {w} | {cell(v)} |" for f, w, v in spec["label_fields"]],
        "",
        "## Procedure",
        "",
        *[f"{i}. {step}" for i, step in enumerate(spec["procedure"], 1)],
        "",
        "## Conversation states",
        "",
        *state_table,
        "",
        *s1_table(spec),
        "",
        "## Intents",
        "",
    ]
    for it in spec["intents"]:
        c += [
            f"### `{it['name']}`",
            "",
            it["definition"],
            "",
            "- **Include:** " + "; ".join(it["include"]),
            "- **Exclude:** " + "; ".join(it["exclude"]),
            f"- **Response strategy:** {it['strategy']}",
            f"- **Default risk:** `{it['default_risk']}`. **Default escalation (draft):** {it['escalation']}",
            "- **Examples:**",
            *examples_block(it["examples"][:3], by_id),
            "",
        ]
    c += ["## Tie-break rules (deterministic, in order)", "", *tie_break_lines(spec, seen), "",
          "## Risk and escalation rules", "", *risk_lines(spec), "",
          "## Escalation calibration plan (dev set)", "", *spec["calibration"], "",
          "## How labels are scored", "", *spec["scoring"], "",
          "## Internal fields (never scored)", "",
          "- `secondary_intents`: the other intent(s) of a multi-issue message (T0 picks the primary).",
          "- `subtype`: " + "; ".join(f"`{it['name']}` → " + ", ".join(f"`{k}`" for k in it["subtypes"])
                                      for it in spec["intents"] if it.get("subtypes")),
          "- `event_tag`: " + ", ".join(f"`{k}`" for k in spec["events"]),
          "", "## Summary table", "", *final_table(spec, est, top), ""]
    CODEBOOK.write_text("\n".join(c), encoding="utf-8")
    print(f"wrote {OUT / 'proposal.md'} and {CODEBOOK}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    sub.add_parser("topics")
    sub.add_parser("render")
    search = sub.add_parser("search")
    search.add_argument("pattern")
    search.add_argument("--n", type=int, default=15)
    args = parser.parse_args()

    seed = load_config()["seed"]
    train = load("train")
    if args.cmd == "sample":
        cmd_sample(train, seed)
    elif args.cmd == "topics":
        cmd_topics(train, seed)
    elif args.cmd == "search":
        cmd_search(train, args.pattern, args.n, seed)
    else:
        cmd_render(train)


if __name__ == "__main__":
    main()
