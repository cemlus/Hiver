"""Customer -> brand exchanges: the unit the agent is trained and evaluated on.

An exchange is one customer message plus the brand's reply to it.
- Customer message: the customer tweet the brand answered, merged with the same customer's own
  tweets just before it (one message split over several tweets, each within MERGE_WINDOW).
- Brand reply: every brand tweet answering that customer tweet, plus the brand's continuation
  tweets within MERGE_WINDOW ("1/2", "2/2"), merged in reply-chain order into one response.
- Context: the conversation before the customer message (its parent chain, at most
  MAX_CONTEXT_AGE old), as logical turns, so a follow-up ("tried that, still broken") stays
  understandable. A brand turn always shows the brand's whole (merged) reply.

build_exchanges() keeps every exchange; apply_filters() drops the unusable ones and returns a
waterfall of counts that should match the Phase 1 funnel (results/brand_validation.md).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from src.dataprep.text import (
    ACTION, DM_LOGISTICS, DM_REDIRECT, MENTION, URL,
    clean_brand_part, clean_customer, language, template_key,
)

MERGE_WINDOW = np.timedelta64(15, "m")    # max gap between the parts of one split message
MAX_PARTS = 5                             # max tweets merged into one message or reply
MAX_CONTEXT_TURNS = 3                     # longer contexts keep the opener + the last 2 turns
MAX_CONTEXT_AGE = np.timedelta64(7, "D")  # older turns belong to a revived, stale thread
MIN_WORDS = 3                             # fewer alphabetic words = no statable issue
CANNED_MIN_REPEATS = 5                    # a template used this often by the brand is canned

_SENTENCES = re.compile(r"(?<=[.!?])\s+|<url>")
# Phrases that describe what the customer did, not what the brand tells them to do.
_CUSTOMER_ATTEMPT = re.compile(
    r"\b(?:steps you(?:'ve| have)? tried|(?:when|if|as|while|whenever) you (?:try|tried)|"
    r"you(?:'ve| have)? (?:already )?tried)\b"
)
_ACTION = re.compile(ACTION)
_DM = re.compile(DM_REDIRECT)


def has_guidance(reply_clean: str) -> bool:
    """True if a sentence of the reply gives troubleshooting/guidance and is not itself a DM
    request. "Can you DM us what you see when you try to sign in?" asks for a DM; it doesn't
    guide. Links split sentences, since replies often read "steps: <URL> DM us if ...". """
    for sentence in _SENTENCES.split(reply_clean.lower()):
        sentence = _CUSTOMER_ATTEMPT.sub(" ", sentence)
        if _ACTION.search(sentence) and not _DM.search(sentence):
            return True
    return False


def flag_brand_tweets(df: pd.DataFrame, brand: str) -> pd.DataFrame:
    """Template key and canned flag for every tweet by `brand` (index = row position)."""
    out = df[~df["inbound"] & (df["author_id"] == brand)]
    key = template_key(out["lower"])
    repeats = key.map(key.value_counts())
    return pd.DataFrame(
        {"template": key, "canned": (repeats >= CANNED_MIN_REPEATS) & (key != "")}, index=out.index
    )


def build_exchanges(df: pd.DataFrame, brand: str) -> pd.DataFrame:
    """One row per customer tweet that `brand` replied to. `df` comes from raw.load_raw +
    raw.add_threads and must keep its RangeIndex (row positions are used as pointers)."""
    assert (df.index == np.arange(len(df))).all(), "df must have a RangeIndex"
    flags = flag_brand_tweets(df, brand)
    canned, template = flags["canned"].to_dict(), flags["template"].to_dict()
    inbound = df["inbound"].to_numpy()
    author = df["author_id"].to_numpy(dtype=object)
    text = df["text"].to_numpy(dtype=object)
    tweet_id = df["tweet_id"].to_numpy()
    parent = df["parent_pos"].to_numpy()
    created = df["created_at"].dt.tz_convert(None).to_numpy()
    root_pos = pd.Index(df["tweet_id"]).get_indexer(df["root"])

    # 1. Each brand tweet -> the customer tweet it answers (its "anchor"). A brand tweet that
    #    answers the brand's own anchored tweet within MERGE_WINDOW is a continuation; `depth`
    #    orders parts that share a timestamp (a continuation comes after what it continues).
    brand_pos = [int(q) for q in flags.index]
    anchor = {q: int(parent[q]) for q in brand_pos if parent[q] >= 0 and inbound[parent[q]]}
    depth = dict.fromkeys(anchor, 0)
    for _ in range(MAX_PARTS - 1):
        for q in brand_pos:
            p = int(parent[q])
            if q not in anchor and p in anchor and created[q] - created[p] <= MERGE_WINDOW:
                anchor[q], depth[q] = anchor[p], depth[p] + 1
    reply_parts: dict[int, list[int]] = {}
    for q, c in anchor.items():
        reply_parts.setdefault(c, []).append(q)
    for parts in reply_parts.values():   # time, then chain depth, then the "1 ^JL" / "2/2" marker
        parts.sort(key=lambda q: (created[q], depth[q], _part_number(text[q])))
    reply_clean = {c: " ".join(clean_brand_part(text[q]) for q in parts) for c, parts in reply_parts.items()}

    # Customer tweets answering each tweet, to find "what the customer said next".
    answers: dict[int, list[int]] = {}
    for q in np.flatnonzero(inbound & (parent >= 0)):
        answers.setdefault(int(parent[q]), []).append(int(q))

    def role(q: int, customer: str) -> str:
        if author[q] == customer:
            return "customer"
        if author[q] == brand:
            return "brand"
        return "other_customer" if inbound[q] else "other_brand"

    rows = []
    for c, parts in reply_parts.items():
        customer = author[c]

        # 2. The same customer's tweets just before c belong to the same message, unless the
        #    brand answered that earlier tweet separately (then it's its own exchange).
        msg = [c]
        while len(msg) < MAX_PARTS:
            p = int(parent[msg[0]])
            if (p < 0 or not inbound[p] or author[p] != customer or p in reply_parts
                    or created[msg[0]] - created[p] > MERGE_WINDOW):
                break
            msg.insert(0, p)
        before = int(parent[msg[0]])

        # 3. Context: the parent chain before the message, up to MAX_CONTEXT_AGE old.
        #    Consecutive tweets by one author form one turn; a brand reply that was split over
        #    several tweets is shown whole, even if the chain only passes through one part.
        chain, q = [], before
        while q >= 0 and len(chain) < 50 and created[msg[0]] - created[q] <= MAX_CONTEXT_AGE:
            chain.append(q)
            q = int(parent[q])
        stale = q >= 0 and len(chain) < 50           # stopped because the next turn was too old
        turns, last_author, shown_replies = [], None, set()
        for q in reversed(chain):
            if q in anchor:
                if anchor[q] in shown_replies:
                    continue
                shown_replies.add(anchor[q])
                piece = reply_clean[anchor[q]]
            else:
                piece = clean_customer(text[q]) if inbound[q] else clean_brand_part(text[q])
            if turns and author[q] == last_author:
                turns[-1]["text"] += " " + piece
            else:
                turns.append({"role": role(q, customer), "text": piece, "created_at": _iso(created[q])})
            last_author = author[q]
        truncated = stale or len(turns) > MAX_CONTEXT_TURNS
        if len(turns) > MAX_CONTEXT_TURNS:
            turns = turns[:1] + turns[-(MAX_CONTEXT_TURNS - 1):]

        nxt = [a for q in parts for a in answers.get(q, []) if author[a] == customer]
        nxt = min(nxt, key=lambda a: created[a]) if nxt else None
        rows.append({
            "record_id": str(tweet_id[c]),
            "thread_id": str(tweet_id[root_pos[c]]),
            "thread_started_at": created[root_pos[c]],
            "created_at": created[c],
            "customer_id": str(customer),
            # A follow-up answers an earlier brand *reply*; answering a brand announcement
            # (a brand tweet that replies to nobody) is a first contact.
            "is_followup": bool(before >= 0 and not inbound[before] and parent[before] >= 0),
            "context": turns,
            "context_turns": len(turns),
            "context_truncated": truncated,
            "customer_tweet_ids": [str(tweet_id[q]) for q in msg],
            "n_customer_parts": len(msg),
            "customer_text": " ".join(text[q] for q in msg),
            "customer_text_clean": " ".join(clean_customer(text[q]) for q in msg),
            "reply_tweet_ids": [str(tweet_id[q]) for q in parts],
            "n_reply_parts": len(parts),
            "brand_reply": " ".join(text[q] for q in parts),
            "brand_reply_clean": reply_clean[c],
            "reply_created_at": created[parts[0]],
            "reply_is_canned": all(canned[q] for q in parts),
            "reply_template": " | ".join(template[q] for q in parts),
            "next_customer_text": text[nxt] if nxt is not None else None,
        })

    ex = pd.DataFrame(rows)
    for col in ["thread_started_at", "created_at", "reply_created_at"]:
        ex[col] = pd.to_datetime(ex[col]).dt.tz_localize("UTC")
    ex["reply_delay_min"] = ((ex["reply_created_at"] - ex["created_at"]).dt.total_seconds() / 60).round(1)

    lower = ex["customer_text"].str.lower()
    ex["lang"] = language(lower)
    body = (lower.str.replace(URL, " ", regex=True).str.replace(MENTION, " ", regex=True)
            .str.replace(r"\s+", " ", regex=True).str.strip())
    ex["n_words"] = body.str.count(r"[a-z]{2,}")
    ex["_body"] = body

    guidance = ex["brand_reply_clean"].map(has_guidance).astype(bool)
    dm = ex["brand_reply"].str.lower().str.contains(DM_REDIRECT, regex=True)
    ex["reply_type"] = np.where(guidance & ~ex["reply_is_canned"], "substantive",
                                np.where(dm & ~guidance, "dm_deflection", "other"))
    ex["customer_prior_threads"] = _prior_threads(ex)
    return ex.sort_values(["created_at", "record_id"]).reset_index(drop=True)


def apply_filters(ex: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, int]]]:
    """Drop exchanges with no usable customer message. Returns (kept, waterfall of counts)."""
    steps = [("customer messages with a brand reply", len(ex))]
    ex = ex[ex["lang"] != "other"]
    steps.append(("drop non-English", len(ex)))
    ex = ex[ex["n_words"] >= MIN_WORDS]
    steps.append((f"drop < {MIN_WORDS} words after removing handles/URLs", len(ex)))
    ex = ex[~(ex["_body"].str.contains(DM_LOGISTICS, regex=True) & (ex["n_words"] < 8))]
    steps.append(("drop DM hand-off messages (\"DM sent\")", len(ex)))
    letters = ex["_body"].str.replace(r"[^a-z ]+", " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
    ex = ex[~letters.duplicated()]              # ex is in time order, so the earliest copy stays
    steps.append(("drop exact-duplicate customer texts (earliest kept)", len(ex)))
    return ex.drop(columns="_body").reset_index(drop=True), steps


def _prior_threads(ex: pd.DataFrame) -> np.ndarray:
    """How many earlier threads each exchange's customer had with the brand."""
    first = ex.groupby(["customer_id", "thread_id"])["created_at"].min().reset_index()
    first["prior"] = first.sort_values("created_at").groupby("customer_id").cumcount()
    merged = ex[["customer_id", "thread_id"]].merge(first, on=["customer_id", "thread_id"], how="left")
    return merged["prior"].to_numpy()


_PART_END = re.compile(r"\s([1-4])(?:/[2-4])?\s*(?:\^\s?\w{1,3})?\s*(?:https?://\S+\s*)*$")
_PART_START = re.compile(r"^(?:@\w+\s+)+([1-4])(?::|/[2-4])")


def _part_number(tweet: str) -> int:
    """The split marker of a brand tweet ("... 1 ^JL", "2/2", "@123 2: ..."), or 0 if none.
    Orders sibling parts that were posted in the same second."""
    m = _PART_END.search(tweet) or _PART_START.search(tweet)
    return int(m.group(1)) if m else 0


def _iso(t: np.datetime64) -> str:
    return f"{np.datetime_as_string(t, unit='m')}Z"
