"""Validate the Phase 1 brand choice: how much usable data does the brand really have?

Run from the repo root:   uv run python scripts/validate_brand.py [--brand XboxSupport]

Reads data/raw/twcs.csv (read-only) and writes results/brand_validation.md, answering:
  1. how many usable customer -> brand exchanges there are (after cleaning),
  2. how many distinct threads they come from,
  3. how many candidate "resolved" cases remain,
  4. the approximate distribution of the top 15 customer issue clusters,
  5. roughly how many examples ~10 draft intents would get.

The clusters (TF-IDF + KMeans) and the keyword draft intents are exploratory sizing aids
only. The Phase 3 codebook, written by hand, is the source of truth for intents.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from eda import MANUAL_END, MANUAL_START, brand_replies, md_table, pct  # also puts the repo root on sys.path
from src.config import load_config, resolve  # noqa: E402
from src.dataprep.raw import add_language, add_threads, load_raw as load  # noqa: E402
from src.dataprep.text import (  # noqa: E402
    ACTION, DM_LOGISTICS, DM_REDIRECT, FIX_CONFIRMED, FIX_NEGATED, MENTION, NEGATIVE, POSITIVE, URL,
)

CONTINUATION_WINDOW = pd.Timedelta(minutes=15)  # brand tweet replying to its own tweet = split part
MIN_WORDS = 3               # customer tweets with fewer alphabetic words carry no issue
N_CLUSTERS = 15
GOLDEN_RANDOM_SLICE = 120   # random part of the planned golden set (PLAN.md Phase 5)

# DM_LOGISTICS, FIX_CONFIRMED and FIX_NEGATED are shared with the pipeline: src/dataprep/text.py.

# ~10 draft intents as keyword rules, checked in this order (first match wins). A rough
# sizing aid for Phase 3, not the codebook.
DRAFT_INTENTS = [
    ("enforcement_ban", r"\b(?:ban|banned|suspend|suspended|suspension|enforcement|reported me)\b"),
    # "bought"/"paid" left out: "I bought X and it won't install" is an install problem.
    ("purchase_billing_refund", r"\b(?:refund\w*|charged|charge|charges|billing|billed|payment|credit card|debit card|declined|money|price|purchase|purchasing|can't buy|cannot buy|unable to buy)\b"),
    # Bare "code" left out: it mostly means "error code", "code of conduct" or "zip code".
    ("code_redemption", r"\b(?:redeem\w*|redemption|gift ?cards?|vouchers?|dlc|tokens?|pre-?order bonus|(?:promo|download|digital|product|season pass|25 digit|25-digit) codes?|codes? (?:isn't|won't|not|doesn't|didn't|says|invalid))\b"),
    ("subscription_membership", r"\b(?:gold|game ?pass|membership|subscription|subscribe|renew|ea access)\b"),
    ("account_access_security", r"\b(?:hack|hacked|password|sign ?in|signed out|log ?in|login|account|email|gamertag|recovery|family|child)\b"),
    ("connectivity_online", r"\b(?:disconnect\w*|connection|connect|network|nat|wifi|wi-fi|internet|servers?|lag\w*|online|party|multiplayer|ping)\b"),
    ("download_install_update", r"\b(?:update\w*|download\w*|install\w*|storage|queue|stuck at)\b"),
    ("console_hardware_display", r"\b(?:turn on|turns? off|turning off|won't turn|power\w*|freez\w*|frozen|black screen|disc|disk|hdmi|overheat\w*|fan|4k|hdr|tv|display)\b"),
    ("controller_accessories", r"\b(?:controllers?|kinect|headset|mic|elite|battery|batteries|adapter|keyboard)\b"),
    ("game_app_bug", r"\b(?:crash\w*|bug\w*|glitch\w*|error\w*|won't load|won't launch|not loading|achievements?)\b"),
    ("info_feature_request", r"\b(?:when|release|coming|will there|is there|feature|backwards?|compatib\w*|suggestion|news|sale)\b"),
]


def build_exchanges(df: pd.DataFrame, brand: str) -> pd.DataFrame:
    """One row per customer tweet that got a reply from `brand`.

    The reply is every brand tweet answering that customer tweet, plus the brand's own
    continuation tweets posted within CONTINUATION_WINDOW (split replies: "1/2", "2/2").
    """
    out = brand_replies(df, [brand])                      # index = row position in df
    inbound = df["inbound"].to_numpy()
    created = df["created_at"]
    parent = out["parent_pos"]

    anchor = {pos: p for pos, p in parent.items() if p >= 0 and inbound[p]}
    continuations = parent[out["parent_author"] == brand]
    for _ in range(3):                                    # up to 4-part replies
        for pos, p in continuations.items():
            if pos not in anchor and p in anchor and created[pos] - created[p] <= CONTINUATION_WINDOW:
                anchor[pos] = anchor[p]
    part_to_customer = pd.Series(anchor, name="customer_pos")

    parts = out.loc[part_to_customer.index].assign(customer_pos=part_to_customer).sort_values("created_at")
    g = parts.groupby("customer_pos")
    ex = pd.DataFrame({"reply": g["text"].agg(" ".join), "n_parts": g.size(), "all_canned": g["canned"].all()})
    reply_lower = ex["reply"].str.lower()
    ex["action"] = reply_lower.str.contains(ACTION, regex=True)
    ex["dm"] = reply_lower.str.contains(DM_REDIRECT, regex=True)

    customer = df.loc[ex.index]
    ex["customer_text"] = customer["text"]
    ex["lang"] = customer["lang"]
    ex["root"] = customer["root"]
    ex["is_followup"] = (customer["parent_author"] == brand).to_numpy()
    clean = (
        customer["lower"].str.replace(URL, " ", regex=True)
        .str.replace(MENTION, " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    ex["clean"] = clean
    ex["words"] = clean.str.count(r"[a-z]{2,}")
    ex["norm"] = clean.str.replace(r"[^a-z ]+", " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()

    # The same customer's first answer to any part of the reply.
    followups = df[df["inbound"] & df["parent_pos"].isin(part_to_customer.index)]
    followups = followups.assign(customer_pos=part_to_customer.reindex(followups["parent_pos"]).to_numpy())
    same_author = followups["author_id"].to_numpy() == df["author_id"].to_numpy()[followups["customer_pos"]]
    first_answer = followups[same_author].sort_values("created_at").drop_duplicates("customer_pos")
    ex["next_customer"] = first_answer.set_index("customer_pos")["text"].reindex(ex.index)
    return ex


def clean_waterfall(ex: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, int]]]:
    steps = [("customer tweets with a brand reply", len(ex))]
    ex = ex[ex["lang"] != "other"]
    steps.append(("drop non-English", len(ex)))
    ex = ex[ex["words"] >= MIN_WORDS]
    steps.append((f"drop < {MIN_WORDS} words after removing handles/URLs", len(ex)))
    ex = ex[~(ex["clean"].str.contains(DM_LOGISTICS, regex=True) & (ex["words"] < 8))]
    steps.append(("drop DM hand-off messages (\"DM sent\")", len(ex)))
    ex = ex[~ex["norm"].duplicated()]
    steps.append(("drop exact-duplicate customer texts", len(ex)))
    return ex, steps


def reply_type(ex: pd.DataFrame) -> pd.Series:
    return pd.Series(
        np.where(ex["action"] & ~ex["all_canned"], "substantive",
                 np.where(ex["dm"] & ~ex["action"], "dm_deflection", "other_reply")),
        index=ex.index,
    )


def resolution(ex: pd.DataFrame) -> pd.Series:
    nxt = ex["next_customer"].fillna("").str.lower()
    neg = nxt.str.contains(NEGATIVE, regex=True) | nxt.str.contains(FIX_NEGATED, regex=True)
    fix = nxt.str.contains(FIX_CONFIRMED, regex=True) & ~neg
    thanks = nxt.str.contains(POSITIVE, regex=True) & ~neg & ~fix
    return pd.Series(
        np.select([ex["next_customer"].isna(), fix, thanks, neg],
                  ["no_customer_answer", "fix_confirmed", "thanks_only", "unresolved_cue"],
                  default="other_answer"),
        index=ex.index,
    )


def draft_intent(clean: pd.Series) -> tuple[pd.Series, pd.Series]:
    hits = pd.DataFrame({name: clean.str.contains(pat, regex=True) for name, pat in DRAFT_INTENTS})
    first = hits.idxmax(axis=1).where(hits.any(axis=1), "other_unclear")
    return first, hits.sum(axis=1)


# Words in almost every support tweet that carry no topic.
GENERIC_WORDS = """xbox xboxone xboxsupport microsoft help thanks thank just fix fixed work working
works doesn't don't can't won't it's i'm i've got get getting guys hey hi hello need problem problems
issue issues tried trying support like know want new did does yes ok okay make way time day today
really right going good please say says said sure let use using used thing things still anymore""".split()


def clusters(ex: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, float]:
    """Topic clusters over first-contact tweets (where the customer states the issue): NMF on
    TF-IDF, each tweet assigned to its strongest topic. Plain KMeans put 35-52% of these short
    tweets into one catch-all cluster, so NMF is easier to read."""
    fc = ex[~ex["is_followup"]]
    vec = TfidfVectorizer(stop_words=list(ENGLISH_STOP_WORDS.union(GENERIC_WORDS)), min_df=5,
                          max_df=0.3, ngram_range=(1, 2), sublinear_tf=True,
                          token_pattern=r"[a-z][a-z']{2,}")
    X = vec.fit_transform(fc["clean"])
    nmf = NMF(n_components=N_CLUSTERS, init="nndsvda", random_state=seed, max_iter=400)
    W = nmf.fit_transform(X)
    label = np.where(W.max(axis=1) < 1e-3, -1, W.argmax(axis=1))   # -1 = matches no topic
    terms = np.array(vec.get_feature_names_out())
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(N_CLUSTERS):
        members = fc[label == k]
        if members.empty:
            continue
        example = members["customer_text"].iloc[rng.integers(len(members))]
        rows.append({
            "cluster": k,
            "n": len(members),
            "pct": pct(label == k),
            "top_terms": ", ".join(terms[np.argsort(nmf.components_[k])[::-1][:8]]),
            "main_draft_intent": members["intent"].value_counts().index[0],
            "example": example.replace("\n", " ").replace("|", "\\|")[:140],
        })
    table = pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)
    return table, pct(label == -1)


def counts_table(labels: pd.Series, ex: pd.DataFrame, name: str) -> pd.DataFrame:
    t = pd.DataFrame({
        name: labels.value_counts().index,
        "n": labels.value_counts().to_numpy(),
    })
    t["pct"] = (100 * t["n"] / len(labels)).round(1)
    by = lambda mask: labels[mask].value_counts().reindex(t[name]).fillna(0).astype(int).to_numpy()  # noqa: E731
    t["first_contact"] = by(~ex["is_followup"])
    t["with_substantive_reply"] = by(ex["reply_type"] == "substantive")
    return t


def manual(path) -> str:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MANUAL_START in text and MANUAL_END in text:
            return text[text.index(MANUAL_START): text.index(MANUAL_END) + len(MANUAL_END)]
    return f"{MANUAL_START}\n## Answers\n\n_To be written after reading the numbers below._\n{MANUAL_END}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--brand", default="XboxSupport")
    args = parser.parse_args()
    cfg = load_config()
    seed, brand = cfg["seed"], args.brand
    path = resolve("results") / "brand_validation.md"

    print("loading raw CSV ...")
    df = add_language(add_threads(load(resolve(cfg["data"]["raw_csv"]))))
    brand_tweets = int(((~df["inbound"]) & (df["author_id"] == brand)).sum())
    all_threads = df.loc[(~df["inbound"]) & (df["author_id"] == brand), "root"].nunique()

    ex_all = build_exchanges(df, brand)
    ex, waterfall = clean_waterfall(ex_all)
    ex = ex.assign(reply_type=reply_type(ex), resolution=resolution(ex))
    ex["intent"], n_hits = draft_intent(ex["clean"])
    print(f"{len(ex):,} usable exchanges; clustering ...")
    cl, unassigned = clusters(ex, seed)

    usable = len(ex)
    subst = ex["reply_type"] == "substantive"
    res = ex["resolution"].value_counts()
    fix_subst = int(((ex["resolution"] == "fix_confirmed") & subst).sum())
    intents = counts_table(ex["intent"], ex, "draft_intent")
    intents["expected_in_random_golden_120"] = (GOLDEN_RANDOM_SLICE * intents["n"] / usable).round(1)
    rtypes = counts_table(ex["reply_type"], ex, "reply_type")[["reply_type", "n", "pct", "first_contact"]]
    resol = counts_table(ex["resolution"], ex, "resolution")

    parts = [
        f"# Brand validation: {brand}",
        "",
        "_Generated by `scripts/validate_brand.py` from `data/raw/twcs.csv` (seed "
        f"{seed}). Numbers are regenerated on each run; the answers block is hand-written and kept._",
        "",
        manual(path),
        "",
        "## 1. Usable customer → brand exchanges",
        "",
        f"An exchange is one customer tweet plus {brand}'s reply to it. The brand's own continuation "
        f"tweets posted within {int(CONTINUATION_WINDOW.total_seconds() // 60)} min are merged into "
        f"that reply (split replies). {brand_tweets:,} brand tweets form {len(ex_all):,} exchanges; "
        f"{int((ex_all['n_parts'] > 1).sum()):,} replies were merged from 2+ tweets.",
        "",
        md_table(pd.DataFrame(waterfall, columns=["step", "remaining"])),
        "",
        f"Of the {usable:,} usable exchanges, {int((~ex['is_followup']).sum()):,} are first contacts "
        f"and {int(ex['is_followup'].sum()):,} are customer follow-ups to an earlier brand reply.",
        "",
        "What kind of reply each usable exchange got:",
        "",
        md_table(rtypes),
        "",
        "## 2. Distinct threads",
        "",
        f"- All threads containing a {brand} tweet: {all_threads:,}",
        f"- Threads with at least one usable exchange: {ex['root'].nunique():,}",
        f"- Threads with at least one usable exchange that got a substantive reply: "
        f"{ex.loc[subst, 'root'].nunique():,}",
        "",
        "## 3. Candidate resolved cases",
        "",
        "Based on the same customer's first answer to the brand's reply. `fix_confirmed` = "
        "worked/fixed/sorted cues, `thanks_only` = thanks without a fix cue, `unresolved_cue` = "
        "still/not working/happening again (these win). Heuristic: see the answers block for a "
        "hand check.",
        "",
        md_table(resol),
        "",
        f"- `fix_confirmed` after a substantive reply (the public fix worked): **{fix_subst:,}**",
        f"- `fix_confirmed` + `thanks_only`: {int(res.get('fix_confirmed', 0) + res.get('thanks_only', 0)):,}",
        "",
        f"## 4. Top {N_CLUSTERS} customer issue clusters (exploratory)",
        "",
        f"NMF topics over TF-IDF (1–2 grams) of the {int((~ex['is_followup']).sum()):,} usable "
        "first-contact tweets, with English stop words and generic support words (xbox, help, "
        "thanks, fix, working, …) removed. Each tweet goes to its strongest topic; "
        f"{unassigned}% match none. Plain KMeans put 35–52% of these short tweets into one "
        "catch-all cluster, so NMF is used. `main_draft_intent` is the most common keyword draft "
        "intent inside the cluster, a cross-check between the two views.",
        "",
        md_table(cl),
        "",
        "## 5. Examples per draft intent (~10 intents)",
        "",
        "Keyword rules checked in a fixed order, first match wins (see `DRAFT_INTENTS` in the "
        f"script). {pct(n_hits > 1)}% of usable texts match more than one rule and "
        f"{pct(n_hits == 0)}% match none (`other_unclear`). "
        f"`expected_in_random_golden_120` = share × {GOLDEN_RANDOM_SLICE}, the random slice of the "
        "planned golden set.",
        "",
        md_table(intents),
        "",
    ]
    path.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
