"""Text patterns and cleaning helpers for the tweet data.

Shared by the data pipeline (src/dataprep) and the Phase 1 analysis scripts (scripts/).
Patterns run on lower-cased text. They use non-capturing groups and no lookarounds, so they
behave the same under Python's `re` and pyarrow's RE2 (pandas may use either).

Every pattern is a keyword heuristic: good enough to filter, route and count, never ground truth.
The Phase 1 reports (results/eda.md, results/brand_validation.md) record how each was
spot-checked by hand.
"""
from __future__ import annotations

import html
import re

import numpy as np
import pandas as pd

URL = r"https?://\S+"
MENTION = r"@\w+"

# --- brand replies -------------------------------------------------------------------------
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
# Agent sign-offs at the end of a reply (URLs removed first): "^JK", "*RickK", "/NS", "-Sam".
SIGNOFF = r"(?:[\^\*/] ?[a-z]{1,15}(?: [a-z]{1,15})?|[-–~] ?[a-z]{2,15})\s*$"
# One reply split over several tweets: "1/2", a leading "2: ", or a bare trailing " 1".
SPLIT = r"(?:\b[1-4]/[2-4]\b|^(?:@\w+ )+[1-4]: |\s[1-4]\s*$)"
# The brand sends the customer somewhere else: another team, channel or company.
HANDOFF = (
    r"\b(?:chat team|live chat|chat support|chat with (?:our|the)|support team|phone support|"
    r"give us a call|call (?:our|the) \w+ team|reach out to (?:the |our |your )?(?:chat|phone|"
    r"support|developer|publisher|maker|bank|isp|it department|game studio)\w*|contact (?:the |our |your )?"
    r"(?:chat|support|developer|publisher|bank|isp)\w*|submit a (?:case|ticket|request)|case review)\b"
)
POLICY = r"\b(?:enforcement|code of conduct|terms of use|suspension|banned|ban)\b"

# --- customer's answer to the brand --------------------------------------------------------
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
# Stronger than "thanks": the customer says the problem is gone.
FIX_CONFIRMED = (
    r"\b(?:worked|it works|works now|working now|fixed|sorted|resolved|solved|that did it|"
    r"did the trick|all good)\b"
)
# Negated or hoped-for fixes that FIX_CONFIRMED would otherwise catch: "nothing has worked",
# "none of these worked", "didnt worked", "hope it works", "see if it can be resolved".
FIX_NEGATED = (
    r"(?:nothing|none|not|n't|didnt|dont|hope\w*|see if|if it|if that)\W+(?:\w+\W+){0,3}"
    r"(?:work\w*|fix\w*|resolv\w*|sort\w*|solv\w*)"
)

# --- customer messages ---------------------------------------------------------------------
# Messages that only manage the DM hand-off ("DM sent", "just messaged you").
DM_LOGISTICS = r"\b(?:dm|dms|dm'd|messaged|sent you|sent it|sent a|just sent)\b"
ANGER = (
    r"\b(?:fuck\w*|shit\w*|wtf|bullshit|crap|ridiculous|pathetic|worst|terrible|awful|useless|"
    r"garbage|trash|scam\w*|pissed|furious|angry|disgusting|joke)\b"
)
LEGAL = r"\b(?:sue|suing|lawyer|attorney|legal action|lawsuit|court|bbb|better business bureau|trading standards)\b"
SECURITY = (
    r"\b(?:hack\w*|stolen|compromised|fraud\w*|unauthori[sz]ed|phishing|scammed|someone (?:else )?"
    r"(?:is |has been |keeps )?(?:using|signed|signing|logged|logging|getting) (?:in|into|on))\b"
)
BILLING_DISPUTE = (
    r"\b(?:refund\w*|charged (?:twice|me|again|for)|double charged|overcharged|chargeback|"
    r"money back|unauthori[sz]ed (?:charge|purchase)|billed)\b"
)
REPEAT_CONTACT = (
    r"\b(?:again|still|already (?:tried|called|contacted|did|done|sent)|(?:second|third|fourth) time|"
    r"for (?:days|weeks|hours|months)|(?:days|weeks) now|no one (?:has )?(?:responded|replied|helped|answered)|"
    r"still waiting)\b"
)

# --- language ------------------------------------------------------------------------------
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


def language(lower: pd.Series) -> pd.Series:
    """Estimate the language of lower-cased tweets: "en", "other" or "undetermined" (too short,
    no function words). Counting function words is crude but needs no extra dependency."""
    body = lower.str.replace(URL, " ", regex=True).str.replace(MENTION, " ", regex=True)
    en = body.str.count(EN_STOP)
    fx = body.str.count(FOREIGN_STOP)
    script = body.str.contains(FOREIGN_SCRIPT, regex=True)
    lang = np.where(script | (fx > en), "other", np.where(en >= 1, "en", "undetermined"))
    return pd.Series(lang, index=lower.index)


def template_key(lower: pd.Series) -> pd.Series:
    """Reduce a brand tweet to its template: no URLs, sign-off, handles, digits or punctuation.
    Two tweets with the same key are the same canned reply."""
    return (
        lower.str.replace(URL, " ", regex=True)
        .str.strip()
        .str.replace(SIGNOFF, " ", regex=True)
        .str.replace(MENTION, " ", regex=True)
        .str.replace(r"[^a-z' ]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


_LEADING_MENTIONS = re.compile(r"^(?:\s*@\w+)+\s*")
_URL = re.compile(URL)
_MENTION = re.compile(MENTION)
_TRAILING_URL = re.compile(r"\s*<URL>\s*$")
# A "^" tag may be glued to the text ("details?^EZ"); "*", "/" and "-" tags need whitespace
# before them, so "Wi-Fi" or "and/or" at the end of a reply survive.
_SIGNOFF_END = re.compile(
    r"(?:\s*\^ ?[a-z]{1,15}|\s+(?:[\*/] ?[a-z]{1,15}(?: [a-z]{1,15})?|[-–~] ?[a-z]{2,15}))\s*$", re.I
)
_SPLIT_END = re.compile(r"\s+[1-4](?:/[2-4])?\s*$")
_SPLIT_START = re.compile(r"^[1-4](?::|/[2-4])\s+")
_SPACES = re.compile(r"\s+")


def clean_customer(text: str) -> str:
    """Customer tweet for the model: HTML entities decoded, leading @handles dropped, other
    handles -> @user, URLs -> <URL>, whitespace collapsed."""
    t = _LEADING_MENTIONS.sub("", html.unescape(text))
    t = _MENTION.sub("@user", _URL.sub("<URL>", t))
    return _SPACES.sub(" ", t).strip()


def clean_brand_part(text: str) -> str:
    """One brand tweet, reduced to what the agent says: leading @handles, the agent sign-off
    ("^XS") and split markers ("1/2", trailing " 1") removed; URLs -> <URL>; handles -> @user."""
    t = _LEADING_MENTIONS.sub("", html.unescape(text))
    t = _URL.sub("<URL>", t)
    tail = ""
    while _TRAILING_URL.search(t):            # a sign-off may sit before a trailing link
        t = _TRAILING_URL.sub("", t)
        tail += " <URL>"
    for _ in range(2):                        # "... 1/2 ^TJ" and "... ^ZM 2/2"
        t = _SPLIT_END.sub("", _SIGNOFF_END.sub("", t))
    t = _SPLIT_START.sub("", t.strip()) + tail
    t = _MENTION.sub("@user", t)
    return _SPACES.sub(" ", t).strip()
