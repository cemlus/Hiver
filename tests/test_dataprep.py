"""Exchange reconstruction, cleaning, splits and weak signals, on tiny hand-made threads."""
import pandas as pd
import pytest

from src.dataprep.exchanges import apply_filters, build_exchanges, has_guidance
from src.dataprep.loaders import load
from src.dataprep.raw import add_language, add_threads
from src.dataprep.splits import assign_splits
from src.dataprep.text import clean_brand_part, clean_customer
from src.dataprep.weak_signals import weak_outcome

BRAND = "XboxSupport"
T0 = pd.Timestamp("2017-10-01 12:00", tz="UTC")
DAY = 60 * 24


def raw(rows):
    """rows: (tweet_id, author, minutes after T0, text, parent tweet_id or None)."""
    t = pd.DataFrame(rows, columns=["tweet_id", "author_id", "minutes", "text", "parent"])
    df = pd.DataFrame({
        "tweet_id": t["tweet_id"],
        "author_id": t["author_id"].astype(str),
        "inbound": ~t["author_id"].isin([BRAND, "MicrosoftHelps"]),
        "created_at": T0 + pd.to_timedelta(t["minutes"], unit="m"),
        "text": t["text"],
        "response_tweet_id": None,
        "in_response_to_tweet_id": pd.to_numeric(t["parent"], errors="coerce"),
    })
    df["lower"] = df["text"].str.lower()
    return add_language(add_threads(df))


def by_id(ex, record_id):
    return ex.set_index("record_id").loc[str(record_id)]


def test_split_brand_reply_is_merged_into_one_response():
    ex = build_exchanges(raw([
        (1, "100", 0, "@XboxSupport my console won't turn on after the update", None),
        (2, BRAND, 10, "@100 Sorry to hear that! Let's try a power cycle: https://t.co/abc  1 ^XS", 1),
        (3, BRAND, 10, "@100 then check that the power brick light is white. 2 ^XS", 2),
    ]), BRAND)
    assert len(ex) == 1
    r = ex.iloc[0]
    assert r["n_reply_parts"] == 2 and r["reply_tweet_ids"] == ["2", "3"]
    assert r["brand_reply_clean"] == ("Sorry to hear that! Let's try a power cycle: <URL> "
                                      "then check that the power brick light is white.")


def test_parts_with_the_same_timestamp_follow_the_reply_chain():
    ex = build_exchanges(raw([
        (1, "100", 0, "@XboxSupport will my preorder download early?", None),
        (3, BRAND, 10, "@100 have any insight into that. 2 ^JL", 2),        # continuation, listed first
        (2, BRAND, 10, "@100 That would be up to the developer. We would not 1 ^JL", 1),
    ]), BRAND)
    assert ex.iloc[0]["brand_reply_clean"] == ("That would be up to the developer. "
                                               "We would not have any insight into that.")


def test_sibling_parts_with_the_same_timestamp_follow_their_markers():
    ex = build_exchanges(raw([
        (1, "100", 0, "@XboxSupport can I buy currency in another region?", None),
        (3, BRAND, 10, "@100 combining the two. Buy with your real location.  2 ^JL", 1),  # both answer tweet 1
        (2, BRAND, 10, "@100 Unfortunately no, currency is region locked, and we can't allow  1 ^JL", 1),
    ]), BRAND)
    assert ex.iloc[0]["brand_reply_clean"] == ("Unfortunately no, currency is region locked, and we can't "
                                               "allow combining the two. Buy with your real location.")


def test_late_brand_continuation_is_not_merged():
    ex = build_exchanges(raw([
        (1, "100", 0, "@XboxSupport my console won't turn on", None),
        (2, BRAND, 10, "@100 Let's try a power cycle ^XS", 1),
        (3, BRAND, 60, "@100 Any luck with that? ^JS", 2),     # 50 min later: not a split part
    ]), BRAND)
    assert ex.iloc[0]["n_reply_parts"] == 1


def test_split_customer_message_is_merged():
    ex = build_exchanges(raw([
        (1, "100", 0, "@XboxSupport my xbox keeps disconnecting 1/2", None),
        (2, "100", 1, "@XboxSupport from xbox live every few minutes 2/2", 1),
        (3, BRAND, 5, "@100 Let's try the steps here https://t.co/x ^JA", 2),
    ]), BRAND)
    r = ex.iloc[0]
    assert r["record_id"] == "2" and r["n_customer_parts"] == 2
    assert r["customer_text_clean"] == "my xbox keeps disconnecting 1/2 from xbox live every few minutes 2/2"
    assert r["context_turns"] == 0 and not r["is_followup"]


def test_followup_gets_context_and_next_answer():
    ex = build_exchanges(raw([
        (1, "100", 0, "@XboxSupport my game crashes on launch", None),
        (2, BRAND, 10, "@100 Try reinstalling the game ^XS", 1),
        (3, "100", 30, "@XboxSupport tried that, it still crashes", 2),
        (4, BRAND, 40, "@100 Please DM us your gamertag ^XS", 3),
    ]), BRAND)
    first, followup = by_id(ex, 1), by_id(ex, 3)
    assert not first["is_followup"] and followup["is_followup"]
    assert [(t["role"], t["text"]) for t in followup["context"]] == [
        ("customer", "my game crashes on launch"), ("brand", "Try reinstalling the game")]
    assert first["next_customer_text"] == "@XboxSupport tried that, it still crashes"
    assert first["reply_type"] == "substantive" and followup["reply_type"] == "dm_deflection"
    assert set(ex["thread_id"]) == {"1"}


def test_context_shows_the_whole_split_reply():
    ex = build_exchanges(raw([
        (1, "100", 0, "@XboxSupport can I upgrade my preorder to deluxe?", None),
        (2, BRAND, 10, "@100 There's no upgrade option, so the pre-order would 1 ^EZ", 1),
        (3, BRAND, 10, "@100 need to be cancelled to get the deluxe edition. 2 ^EZ", 1),  # sibling part
        (4, "100", 30, "@XboxSupport ok, how do I cancel it then?", 3),
        (5, BRAND, 40, "@100 You can cancel it from your order history: https://t.co/a ^EZ", 4),
    ]), BRAND)
    assert [t["text"] for t in by_id(ex, 4)["context"]] == [
        "can I upgrade my preorder to deluxe?",
        "There's no upgrade option, so the pre-order would need to be cancelled to get the deluxe edition."]


def test_reply_to_a_brand_announcement_is_not_a_followup():
    r = build_exchanges(raw([
        (1, BRAND, 0, "Check out the new dashboard features: https://t.co/a", None),
        (2, "100", 30, "@XboxSupport the new dashboard keeps crashing on me", 1),
        (3, BRAND, 40, "@100 Let's try a power cycle ^XS", 2),
    ]), BRAND).iloc[0]
    assert not r["is_followup"] and r["context"][0]["role"] == "brand"


def test_long_context_keeps_the_opener():
    rows, parent = [], None
    for i in range(1, 8):                      # C B C B C B C, 20 min apart
        author = "100" if i % 2 else BRAND
        rows.append((i, author, 20 * i, f"@x turn {i} text", parent))
        parent = i
    rows.append((8, BRAND, 200, "@100 final answer ^XS", 7))
    followup = by_id(build_exchanges(raw(rows), BRAND), 7)
    assert followup["context_truncated"]
    assert [t["text"] for t in followup["context"]] == ["turn 1 text", "turn 5 text", "turn 6 text"]


def test_stale_context_is_dropped():
    r = build_exchanges(raw([
        (1, "200", 0, "@XboxSupport an old question from a month ago", None),
        (2, "100", 30 * DAY, "@XboxSupport my controller won't pair with the console", 1),
        (3, BRAND, 30 * DAY + 10, "@100 Let's try the steps here ^XS", 2),
    ]), BRAND).iloc[0]
    assert r["context_turns"] == 0 and r["context_truncated"]


def test_filters_follow_the_phase1_funnel():
    texts = [
        "@XboxSupport my controller will not connect to the console",   # kept
        "@XboxSupport hola necesito ayuda con mi cuenta por favor gracias",  # non-English
        "@XboxSupport help!!",                                          # < 3 words
        "@XboxSupport just sent you a dm",                              # DM hand-off
        "@XboxSupport my controller will not connect to the console!",  # duplicate of the first
    ]
    rows = []
    for i, text in enumerate(texts):
        rows += [(10 * i + 1, f"10{i}", 60 * i, text, None),
                 (10 * i + 2, BRAND, 60 * i + 5, "@x Let's try these steps ^XS", 10 * i + 1)]
    kept, steps = apply_filters(build_exchanges(raw(rows), BRAND))
    assert [n for _, n in steps] == [5, 4, 3, 2, 1]
    assert kept["record_id"].tolist() == ["1"]


def test_guidance_must_be_outside_a_dm_request():
    assert not has_guidance("Can you DM us your gamertag and what you see when you try to sign in?")
    assert has_guidance("Have you tried resetting your router and then a power cycle: <URL> "
                        "Mind sending us a direct message <URL> with your Gamertag?")
    assert has_guidance("Let's try a power cycle <URL>")
    assert not has_guidance("Thanks for the kind words, enjoy your new console!")


def test_clean_text():
    assert clean_customer("@XboxSupport @115786 my Xbox &amp; TV https://t.co/x") == "my Xbox & TV <URL>"
    assert clean_brand_part("@123 Hi there! Could you DM https://t.co/nPX us your Gamertag? 2/2 ^JA") == \
        "Hi there! Could you DM <URL> us your Gamertag?"
    assert clean_brand_part("@1 We'll take a look backstage /SU https://t.co/ld") == "We'll take a look backstage <URL>"
    assert clean_brand_part("@1 Please check your Wi-Fi") == "Please check your Wi-Fi"
    assert clean_brand_part("@1 Could you DM us some details?^EZ") == "Could you DM us some details?"
    assert clean_brand_part("@1 reach out to our chat team: https://t.co/x .^IS") == "reach out to our chat team: <URL> ."


def test_split_is_per_thread_and_train_strictly_precedes_holdout():
    sd = pd.Timestamp("2017-11-15", tz="UTC")
    start = pd.Series(pd.to_datetime(["2017-11-01", "2017-11-01", "2017-11-20"], utc=True))
    created = pd.Series(pd.to_datetime(["2017-11-02", "2017-11-16", "2017-11-20"], utc=True))
    assert list(assign_splits(start, created, sd)) == ["train", "excluded", "holdout"]


def test_weak_outcome_rules():
    nxt = pd.Series(["That worked, thanks!", "tried that and it's still broken", "none of these worked",
                     "thanks for the reply", None, None, "That worked!"])
    rtype = pd.Series(["substantive", "substantive", "substantive", "other", "dm_deflection", "other", "other"])
    out = weak_outcome(nxt, rtype)
    assert list(zip(out["weak_outcome"], out["outcome_confidence"])) == [
        ("resolved", "medium"), ("unresolved", "medium"), ("unresolved", "medium"),
        ("acknowledged", "low"), ("deflected", "high"), ("unknown", "none"), ("resolved", "low")]


@pytest.mark.parametrize("split", ["golden", "excluded"])
def test_loader_rejects_other_splits(split):
    with pytest.raises(ValueError):
        load(split)
