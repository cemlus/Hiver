"""Phase 1 EDA: compare brands in the Customer Support on Twitter dataset and pick one.

Run from the repo root:   uv run python scripts/eda.py
Optional:                 uv run python scripts/eda.py --candidates AppleSupport SpotifyCares ...

Reads data/raw/twcs.csv (read-only) and writes:
  results/brand_comparison.csv   one row per top brand; stage-2 columns only for candidates
  results/eda.md                 tables + sample threads. The block between the
                                 <!-- manual:start --> / <!-- manual:end --> markers is
                                 hand-written and is kept when the script is re-run.

Stage 1 screens the top brands by outbound (brand-authored) tweet volume with cheap text
metrics. Stage 2 looks at a few candidate brands in depth: thread structure, follow-ups,
outcome signals, canned replies, frequent customer terms, and sample threads.

Every text metric here is a keyword heuristic. They are estimates for choosing a brand,
never labels.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config, resolve  # noqa: E402

TOP_N = 15                # brands screened in stage 1
N_CANDIDATES = 4          # brands analysed in stage 2 (unless --candidates is given)
MIN_ENGLISH = 0.85        # candidates must be mostly English...
MIN_REPLIES = 20_000      # ...and have enough brand replies
CANNED_MIN_REPEATS = 5    # a normalised reply seen this often (per brand) counts as canned
N_SAMPLE_BRANDS = 2       # strongest candidates that get sample threads in eda.md
N_SAMPLE_THREADS = 8

# Patterns run on lower-cased text. Non-capturing groups and no lookarounds, so they behave
# the same under Python's `re` and pyarrow's RE2 (pandas may use either).
URL = r"https?://\S+"
MENTION = r"@\w+"
DM_REDIRECT = (
    r"\b(?:dm|dms|dm'd|d\.m|direct messages?|private messages?|pm us|message us|"
    r"send us a (?:note|message)|reach out (?:to us )?(?:via|in|through|by) (?:dm|direct|private))\b"
)
# Troubleshooting / guidance cues. Deliberately excludes words that mostly appear in DM
# redirects ("click here to DM", "upgrade options", "check your account").
ACTION = (
    r"\b(?:restart|restarting|reboot|re-?install|uninstall|update|updating|sign (?:out|in)|"
    r"sign back in|log ?(?:out|in)|logging (?:out|in)|clear (?:the |your )?(?:cache|data|cookies|history)|"
    r"settings|go to|tap|toggle|turn (?:it )?(?:off|on)|reset|resetting|force (?:quit|close|stop)|"
    r"power cycle|unplug|delete (?:the )?app|remove|try|tried|make sure|check (?:that|if)|steps|"
    r"enable|disable|head to|navigate|open the|should (?:now )?be (?:able|working|fixed)|"
    r"you can (?:find|change|set|use|add|cancel|manage|vote|check))\b"
)
POSITIVE = (
    r"\b(?:thanks|thank you|thx|ty|cheers|appreciate it|worked|works now|working now|fixed|"
    r"sorted|resolved|solved|perfect|awesome|that did it|all good)\b"
)
NEGATIVE = (
    r"\b(?:still|not working|doesn't work|didn't work|does not work|did not work|won't|"
    r"same (?:issue|problem)|(?:happened|happening|doing it|did it|broke|broken) again|"
    r"already (?:tried|did|done)|no luck|useless|ridiculous|worst|terrible|no response|"
    r"no reply|nobody|never)\b"
)
EN_STOP = (
    r"\b(?:the|to|my|you|your|and|for|this|that|with|have|has|can|not|why|how|what|when|just|"
    r"get|got|please|thanks|help|been|was|are|will|would|still|any|of|is|it|on|me|i'm|it's|"
    r"don't|doesn't|can't)\b"
)
FOREIGN_STOP = (
    r"\b(?:que|por|para|los|las|el|una|pero|muy|estoy|tengo|gracias|hola|porque|cuando|est|pas|"
    r"les|des|avec|pour|merci|bonjour|und|nicht|ist|mit|ich|das|der|não|você|obrigado|uma|"
    r"mais|het|een|niet|mijn)\b"
)
# Cyrillic, Arabic, Thai, Japanese kana, CJK, Hangul. A plain (non-raw) string, so Python turns
# the escapes into literal characters that both regex engines accept.
FOREIGN_SCRIPT = "[Ѐ-ӿ؀-ۿ฀-๿぀-ヿ一-鿿가-힯]"
# Agent sign-offs at the end of a reply (URLs removed first): "^JK", "*RickK", "/NS", "-Sam".
SIGNOFF = r"(?:[\^\*/] ?[a-z]{1,15}(?: [a-z]{1,15})?|[-–~] ?[a-z]{2,15})\s*$"
# One reply split over several tweets: "1/2", a leading "2: ", or a bare trailing " 1".
SPLIT = r"(?:\b[1-4]/[2-4]\b|^(?:@\w+ )+[1-4]: |\s[1-4]\s*$)"

STOPWORDS = set(
    """a about above after again all also am an and any are as at be because been before being
    but by can can't cannot could did didn't do does doesn't doing don't down for from get got had
    has have having he her here him his how i i'd i'll i'm i've if in into is isn't it it's its
    just me more most my no not now of off on once only or other our out over own please same she
    should so some such than thank thanks that that's the their them then there these they this
    those through to too under until up very was wasn't we were what when where which while who
    why will with won't would you you're your yours amp one still even really why what's let
    back need know like help want going since been way hey hi guys""".split()
)


# --------------------------------------------------------------------------- loading

def load(path: Path) -> pd.DataFrame:
    # The C engine, not pyarrow: some tweets contain newlines inside quoted fields, which
    # pyarrow's CSV reader rejects ("Expected 7 columns, got 4").
    df = pd.read_csv(path, dtype={"author_id": str, "text": str, "response_tweet_id": str})
    df["created_at"] = pd.to_datetime(df["created_at"], format="%a %b %d %H:%M:%S %z %Y", utc=True)
    df["text"] = df["text"].fillna("")
    df["lower"] = df["text"].str.lower()
    return df


def add_threads(df: pd.DataFrame) -> pd.DataFrame:
    """Give every tweet its parent's row position, the parent's author and its thread root.

    A thread is the tree of tweets linked by in_response_to_tweet_id. The root is the first
    ancestor present in the dataset. "Orphans" reply to a tweet that isn't in the dataset.
    """
    ids = pd.Index(df["tweet_id"])
    parent = ids.get_indexer(df["in_response_to_tweet_id"])      # -1 = no parent in the data
    root = np.where(parent >= 0, parent, np.arange(len(df)))
    for _ in range(64):                                            # pointer jumping
        nxt = root[root]
        if np.array_equal(nxt, root):
            break
        root = nxt
    authors = df["author_id"].to_numpy(dtype=object)
    df["parent_pos"] = parent
    df["parent_author"] = np.where(parent >= 0, authors[parent], None)
    df["root"] = df["tweet_id"].to_numpy()[root]
    df["orphan"] = df["in_response_to_tweet_id"].notna().to_numpy() & (parent < 0)
    return df


def add_language(df: pd.DataFrame) -> pd.DataFrame:
    """Estimate the language of customer tweets: "en", "other" or "undetermined" (too short,
    no function words). Counting function words is crude but needs no extra dependency."""
    inbound = df["inbound"].to_numpy()
    body = (
        df.loc[inbound, "lower"]
        .str.replace(URL, " ", regex=True)
        .str.replace(MENTION, " ", regex=True)
    )
    en = body.str.count(EN_STOP)
    fx = body.str.count(FOREIGN_STOP)
    script = body.str.contains(FOREIGN_SCRIPT, regex=True)
    lang = np.where(script | (fx > en), "other", np.where(en >= 1, "en", "undetermined"))
    df["lang"] = None
    df.loc[inbound, "lang"] = lang
    return df


def pct(mask) -> float:
    mask = np.asarray(mask, dtype=bool)
    return round(100 * mask.mean(), 1) if mask.size else float("nan")


# --------------------------------------------------------------------------- stage 1

def brand_replies(df: pd.DataFrame, brands) -> pd.DataFrame:
    """Brand-authored tweets with per-reply heuristic flags."""
    out = df[~df["inbound"] & df["author_id"].isin(brands)].copy()
    lower = out["lower"]
    out["dm"] = lower.str.contains(DM_REDIRECT, regex=True)
    out["action"] = lower.str.contains(ACTION, regex=True)
    out["url"] = lower.str.contains(URL, regex=True)

    body = lower.str.replace(URL, " ", regex=True).str.strip()
    out["signoff"] = body.str.contains(SIGNOFF, regex=True)
    unsigned = body.str.replace(SIGNOFF, " ", regex=True)
    out["split"] = unsigned.str.contains(SPLIT, regex=True)
    # The reply's template: no handles, URLs, sign-offs, digits or punctuation.
    out["norm"] = (
        unsigned.str.replace(MENTION, " ", regex=True)
        .str.replace(r"[^a-z' ]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    repeats = out.groupby(["author_id", "norm"])["norm"].transform("size")
    out["canned"] = (repeats >= CANNED_MIN_REPEATS) & (out["norm"] != "")
    out["substantive"] = out["action"] & ~out["canned"]
    out["dm_only"] = out["dm"] & ~out["action"]
    return out


def screen(df: pd.DataFrame, out: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for brand, g in out.groupby("author_id"):
        # Customer tweets this brand replied to: the unit we'll later classify.
        pos = np.unique(g.loc[g["parent_pos"] >= 0, "parent_pos"].to_numpy())
        replied = df.iloc[pos]
        replied = replied[replied["inbound"]]
        lang = replied["lang"]
        decided = lang.isin(["en", "other"])
        rows.append({
            "brand": brand,
            "brand_replies": len(g),
            "customer_tweets_replied": len(replied),
            "first_date": g["created_at"].min().date().isoformat(),
            "last_date": g["created_at"].max().date().isoformat(),
            "pct_replies_in_last_90d": pct(g["created_at"] >= g["created_at"].max() - pd.Timedelta(days=90)),
            "english_share": round(float((lang == "en").sum() / max(decided.sum(), 1)), 3),
            "lang_undetermined_pct": pct(lang == "undetermined"),
            "dm_redirect_pct": pct(g["dm"]),
            "dm_only_pct": pct(g["dm_only"]),
            "actionable_pct": pct(g["action"]),
            "substantive_pct": pct(g["substantive"]),
            "url_pct": pct(g["url"]),
            "canned_pct": pct(g["canned"]),
            "unique_reply_ratio": round(g["norm"].nunique() / len(g), 3),
            "signoff_pct": pct(g["signoff"]),
            "split_reply_pct": pct(g["split"]),
            "median_reply_chars": int(g["text"].str.len().median()),
        })
    return pd.DataFrame(rows).sort_values("brand_replies", ascending=False).reset_index(drop=True)


def pick_candidates(table: pd.DataFrame) -> list[str]:
    """Mostly-English brands with enough replies, ranked by the share of substantive replies
    (actionable and not canned): the material a grounded reply generator can learn from."""
    ok = table[(table["english_share"] >= MIN_ENGLISH) & (table["brand_replies"] >= MIN_REPLIES)]
    return ok.sort_values("substantive_pct", ascending=False)["brand"].head(N_CANDIDATES).tolist()


# --------------------------------------------------------------------------- stage 2

def outcome_signal(lower: pd.Series) -> pd.Series:
    neg = lower.str.contains(NEGATIVE, regex=True)
    pos = lower.str.contains(POSITIVE, regex=True)
    return pd.Series(
        np.where(neg, "unresolved_signal", np.where(pos, "resolved_signal", "continued_other")),
        index=lower.index,
    )


def deep_dive(df: pd.DataFrame, out: pd.DataFrame, brand: str) -> tuple[dict, dict]:
    g = out[out["author_id"] == brand]
    roots = g["root"].unique()
    th = df[df["root"].isin(roots)]
    sizes = th.groupby("root").size()
    brands_per_thread = th[~th["inbound"]].groupby("root")["author_id"].nunique()
    is_brand = th["author_id"] == brand

    # Follow-up: a customer tweet that answers one of this brand's replies.
    followups = th[th["inbound"] & (th["parent_author"] == brand)]
    last = followups.sort_values("created_at").groupby("root").tail(1)
    signals = outcome_signal(last["lower"]).value_counts()
    n = len(roots)
    root_rows = df[df["tweet_id"].isin(roots)]

    metrics = {
        "threads": n,
        "avg_thread_len": round(sizes.mean(), 2),
        "median_thread_len": float(sizes.median()),
        "p90_thread_len": float(sizes.quantile(0.9)),
        "inbound_share_pct": pct(th["inbound"]),
        "brand_share_pct": pct(is_brand),
        "other_brand_share_pct": pct(~th["inbound"] & ~is_brand),
        "multi_brand_thread_pct": pct(brands_per_thread.reindex(roots).fillna(0).to_numpy() > 1),
        "truncated_thread_pct": pct(root_rows["orphan"]),
        "followup_rate_pct": round(100 * followups["root"].nunique() / n, 1),
        "outcome_resolved_pct": round(100 * signals.get("resolved_signal", 0) / n, 1),
        "outcome_unresolved_pct": round(100 * signals.get("unresolved_signal", 0) / n, 1),
        "outcome_continued_pct": round(100 * signals.get("continued_other", 0) / n, 1),
        "outcome_no_followup_pct": round(100 * (n - len(last)) / n, 1),
        "unique_substantive_replies": int(g.loc[g["substantive"], "norm"].nunique()),
    }

    # Qualitative material for eda.md.
    replied_pos = np.unique(g.loc[g["parent_pos"] >= 0, "parent_pos"].to_numpy())
    replied = df.iloc[replied_pos]
    replied = replied[replied["inbound"]]
    tokens = Counter(
        w
        for text in replied["lower"].str.replace(URL, " ", regex=True).str.replace(MENTION, " ", regex=True)
        for w in re.findall(r"[a-z][a-z']{2,}", text)
        if w not in STOPWORDS
    )
    templates = g.loc[g["canned"], "norm"].value_counts().head(5)
    monthly = g["created_at"].dt.strftime("%Y-%m").value_counts().sort_index()
    detail = {"top_terms": tokens.most_common(20), "templates": templates, "monthly": monthly,
              "thread_sizes": sizes}
    return metrics, detail


# --------------------------------------------------------------------------- report

def fmt(value) -> str:
    """Whole-number floats (from columns that also hold NaN) print as integers."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(fmt(row[c]) for c in cols) + " |")
    return "\n".join(lines)


def sample_threads(df: pd.DataFrame, brand: str, sizes: pd.Series, seed: int) -> str:
    eligible = sizes[(sizes >= 2) & (sizes <= 8)].index.to_numpy()
    rng = np.random.default_rng(seed)
    chosen = rng.choice(eligible, size=min(N_SAMPLE_THREADS, len(eligible)), replace=False)
    blocks = []
    for root in chosen:
        th = df[df["root"] == root].sort_values("created_at")
        lines = [f"**Thread {root}** ({len(th)} tweets)", ""]
        for _, t in th.iterrows():
            who = "Customer" if t["inbound"] else t["author_id"]
            text = t["text"].replace("\n", " ").replace("|", "\\|")
            lines.append(f"- `{t['created_at']:%Y-%m-%d %H:%M}` **{who}**: {text}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


MANUAL_START, MANUAL_END = "<!-- manual:start -->", "<!-- manual:end -->"


def manual_block(path: Path) -> str:
    """The hand-written recommendation, kept across re-runs."""
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MANUAL_START in text and MANUAL_END in text:
            return text[text.index(MANUAL_START): text.index(MANUAL_END) + len(MANUAL_END)]
    return f"{MANUAL_START}\n## Recommendation\n\n_To be written after reading the tables and samples below._\n{MANUAL_END}"


def write_report(path, df, facts, table, candidates, details, samples) -> None:
    stage1_cols = ["brand", "brand_replies", "customer_tweets_replied", "first_date", "last_date",
                   "english_share", "dm_redirect_pct", "dm_only_pct", "actionable_pct",
                   "substantive_pct", "url_pct", "canned_pct", "unique_reply_ratio", "signoff_pct",
                   "split_reply_pct", "median_reply_chars"]
    stage2_cols = ["brand", "threads", "avg_thread_len", "median_thread_len", "p90_thread_len",
                   "inbound_share_pct", "brand_share_pct", "other_brand_share_pct",
                   "multi_brand_thread_pct", "truncated_thread_pct", "followup_rate_pct",
                   "unique_substantive_replies"]
    outcome_cols = ["brand", "outcome_resolved_pct", "outcome_unresolved_pct",
                    "outcome_continued_pct", "outcome_no_followup_pct"]
    cand = table.set_index("brand").loc[candidates].reset_index()

    parts = [
        "# Phase 1 EDA: brand selection",
        "",
        "_Generated by `scripts/eda.py` from `data/raw/twcs.csv` (seed "
        f"{facts['seed']}). Everything below the recommendation is regenerated on each run; the "
        "recommendation is hand-written and kept between runs._",
        "",
        manual_block(path),
        "",
        "## Dataset facts",
        "",
        f"- {facts['rows']:,} tweets: {facts['inbound']:,} from customers, {facts['outbound']:,} "
        f"from {facts['brands']} brand accounts.",
        f"- Tweet dates: {facts['first']} to {facts['last']}; {facts['pct_last_90d']}% fall in the "
        "final 90 days.",
        f"- `response_tweet_id` holds several comma-separated IDs in {facts['multi_response']:,} "
        "tweets, so threads are trees, not chains. Threads here are rebuilt from "
        "`in_response_to_tweet_id` (parent pointers).",
        f"- {facts['newline_texts']:,} tweets contain line breaks inside quoted text, which "
        "pyarrow's CSV reader rejects. Load with pandas' default C engine.",
        f"- {facts['orphans']:,} tweets ({facts['orphan_pct']}%) reply to a tweet that isn't in the "
        "dataset, so some threads start mid-conversation.",
        f"- Customer handles are anonymised: {facts['numeric_mention_pct']}% of brand replies "
        "mention a numeric handle such as `@115712`.",
        "",
        f"## Stage 1: top {len(table)} brands by brand-authored tweets",
        "",
        "Percentages are of the brand's replies. `english_share` is over the customer tweets the "
        "brand replied to whose language could be estimated. `substantive` = actionable and not "
        f"canned. Candidates are the top {N_CANDIDATES} by `substantive_pct` among brands with "
        f"`english_share` ≥ {MIN_ENGLISH} and ≥ {MIN_REPLIES:,} replies.",
        "",
        md_table(table[stage1_cols]),
        "",
        f"## Stage 2: candidates ({', '.join(candidates)})",
        "",
        "### Threads",
        "",
        md_table(cand[stage2_cols]),
        "",
        "### Outcome signals (share of threads, heuristic)",
        "",
        "Based on the customer's last reply to the brand in each thread: `resolved` = thanks/fixed "
        "cues, `unresolved` = still/not-working/happening-again cues (these win over thanks), "
        "`continued` = some other reply, `no_followup` = the customer never answered the brand in "
        "public (resolved, moved to DM, or gave up: we can't tell).",
        "",
        md_table(cand[outcome_cols]),
        "",
    ]
    for brand in candidates:
        d = details[brand]
        terms = ", ".join(f"{w} ({c:,})" for w, c in d["top_terms"])
        parts += [f"### {brand}", "", f"**Frequent customer terms:** {terms}", "",
                  "**Most repeated reply templates** (normalised):", ""]
        parts += [f"- {count:,}× \"{text[:160]}\"" for text, count in d["templates"].items()]
        monthly = d["monthly"]
        recent = monthly.tail(4)
        older = int(monthly.iloc[:-4].sum()) if len(monthly) > 4 else 0
        parts += ["", "**Replies per month:** " + ", ".join(f"{m}: {c:,}" for m, c in recent.items())
                  + (f"; earlier months: {older:,}" if older else ""), ""]
    parts += [
        "## Method and caveats",
        "",
        "- **DM redirect**: the reply mentions DM / direct or private message. **DM-only**: a DM "
        "redirect with no actionable cue.",
        "- **Actionable**: contains a troubleshooting or guidance cue (restart, update, settings, "
        "try, go to, power cycle, …). Keyword-based: it over-counts (\"try DMing us\") and "
        "under-counts (fixes phrased unusually, informational answers such as \"this song isn't "
        "available yet\").",
        f"- **Canned**: the normalised reply (no handles, URLs, sign-offs, digits, punctuation) "
        f"occurs ≥ {CANNED_MIN_REPEATS} times for that brand.",
        "- **Sign-off**: an agent tag at the end of the reply (`^JK`, `*RickK`, `/NS`, `-Sam`). "
        "**Split reply**: one answer spread over several tweets (`1/2`, a leading `2:`, a trailing "
        "` 1`).",
        "- **English share**: counts English vs Spanish/French/German/Portuguese/Dutch function "
        "words and checks for non-Latin scripts. Tweets with neither are `undetermined` and "
        "excluded from the share.",
        "- **Outcome signals** are weak heuristics, used here only to compare brands. They are "
        "never ground truth.",
        "",
        "## Appendix: sample threads",
        "",
        f"Random threads with 2–8 tweets (seed {facts['seed']}) from the strongest "
        f"{N_SAMPLE_BRANDS} candidates by `substantive_pct`.",
        "",
    ]
    for brand, text in samples.items():
        parts += [f"### {brand}", "", text, ""]
    path.write_text("\n".join(parts), encoding="utf-8")


# --------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--candidates", nargs="+", help="override the automatic candidate pick")
    args = parser.parse_args()

    cfg = load_config()
    seed = cfg["seed"]
    raw = resolve(cfg["data"]["raw_csv"])
    results = resolve("results")

    print(f"loading {raw} ...")
    df = add_language(add_threads(load(raw)))
    is_out = ~df["inbound"]
    last = df["created_at"].max()
    facts = {
        "seed": seed,
        "rows": len(df),
        "inbound": int(df["inbound"].sum()),
        "outbound": int(is_out.sum()),
        "brands": df.loc[is_out, "author_id"].nunique(),
        "first": df["created_at"].min().date().isoformat(),
        "last": last.date().isoformat(),
        "pct_last_90d": pct(df["created_at"] >= last - pd.Timedelta(days=90)),
        "multi_response": int(df["response_tweet_id"].str.contains(",", regex=False).fillna(False).sum()),
        "newline_texts": int(df["text"].str.contains("\n", regex=False).sum()),
        "orphans": int(df["orphan"].sum()),
        "orphan_pct": pct(df["orphan"]),
        "numeric_mention_pct": pct(df.loc[is_out, "lower"].str.contains(r"@\d+", regex=True)),
    }

    top = df.loc[is_out, "author_id"].value_counts().head(TOP_N).index.tolist()
    print(f"stage 1: screening {len(top)} brands ...")
    out = brand_replies(df, top)
    table = screen(df, out)

    candidates = args.candidates or pick_candidates(table)
    missing = set(candidates) - set(top)
    if missing:
        out = pd.concat([out, brand_replies(df, sorted(missing))])
        table = pd.concat([table, screen(df, out[out["author_id"].isin(missing)])], ignore_index=True)
    print(f"stage 2: candidates {candidates}")

    details = {}
    for brand in candidates:
        metrics, details[brand] = deep_dive(df, out, brand)
        for k, v in metrics.items():
            table.loc[table["brand"] == brand, k] = v
    table["candidate"] = table["brand"].isin(candidates)

    strongest = (
        table[table["candidate"]].sort_values("substantive_pct", ascending=False)["brand"]
        .head(N_SAMPLE_BRANDS).tolist()
    )
    samples = {b: sample_threads(df, b, details[b]["thread_sizes"], seed) for b in strongest}

    results.mkdir(exist_ok=True)
    table.to_csv(results / "brand_comparison.csv", index=False)
    write_report(results / "eda.md", df, facts, table, candidates, details, samples)
    print(f"wrote {results / 'brand_comparison.csv'} and {results / 'eda.md'}")


if __name__ == "__main__":
    main()
