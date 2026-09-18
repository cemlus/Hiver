# XboxSupport agent — report

An AI support agent over the Kaggle *Customer Support on Twitter* dataset (brand: **XboxSupport**).
It classifies each customer tweet into a frozen taxonomy, decides auto-handle vs escalate with a
stated reason, and drafts a reply grounded in how the brand actually answered similar messages.

The interesting part is not the agent. It is the evidence about when to trust it.

## What "good" means here

A support router is not a classifier with a single score. Two errors cost very different things: a
**missed escalation** reaches a customer as an unanswered problem, while a **false escalation**
costs an agent a few seconds of triage. The system is therefore built so the model never decides:
it reports observations (state, intent, nine policy cues, a confidence) and a **frozen deterministic
policy** computes escalation and a reason code. The model's schema has no `escalate` field.

The headline metric is **joint routing correctness** — state, intent (when one is due) and the
escalation decision all correct on the same item — because a system that gets two of three right
still routes the ticket wrongly.

## Results

**Agent vs. the clean baseline floor.** 200 locked golden items, final adjudicated labels, 10,000
bootstrap resamples, seed 42.

| metric | agent | best clean baseline |
|---|---|---|
| State accuracy | **0.94** [0.90–0.96] | 0.86 (`cue_rule`) |
| State macro-F1 | **0.85** [0.74–0.93] | 0.60 (`cue_rule`) |
| Intent macro-F1 | **0.82** [0.73–0.89] | 0.41 (`tfidf_lr`) |
| Escalation precision | **0.71** [0.61–0.79] | 0.64 (`cue_rule`) |
| Escalation recall | **0.97** [0.93–1.00] | 0.66 (`cue_rule`) |
| `must_escalate_recall_cue_blind` | **0.96** [0.86–1.00] | 0.76 (`cue_rule`) |
| **Joint routing correctness** | **0.71** [0.65–0.77] | 0.30 (`tfidf_lr_cues`) |

Seven baselines were built and published **before** the agent existed, so every gain is stated
against a cheap alternative rather than against zero. The degenerate ones behave as they should:
`always_escalate` buys recall 1.00 at precision 0.37 and joint 0.01.

**The escalation numbers are a deliberate trade-off, not uniform strength.** Of 32 escalation
errors, **30 are over-escalation and 2 are under-escalation**. The system buys near-complete
coverage of cases needing a human by sending roughly three in ten auto-handled cases to a human
unnecessarily. For support triage that is the right direction — but it is a real cost, and the 0.71
precision is where it shows.

**Slices.** Random 120 → joint 0.74; stratified 80 → joint 0.66. **Sensitivity** against the
project owner's original labels, before adjudication: joint 0.69, state 0.89, intent macro-F1 0.84.
The ranking does not depend on the adjudicated layer.

## Top five failure modes

**1. The frozen policy over-triggers on genuine cues — 26 of 30 over-escalations.**
Reason codes *within this subset*: `ACCOUNT_SPECIFIC` 9, `STEPS_FAILED` 9, `SECURITY` 4,
`REPEAT_CONTACT` 2, `HIGH_ANGER` 2. (Across all 30 over-escalations — i.e. including mode 2 below —
`results/eval/routing_failures.md` reports 11 / 10 / 4 / 3 / 2; the counts differ because that file
does not split by whether the gold state carries an intent.) G002 ("i've tried almost everything help") genuinely reports failed steps; the
human still judged it auto-handleable. The cue detection is right and the *policy* is conservative.
**Fix:** require a second signal before `STEPS_FAILED` alone escalates. Validate on dev; the policy
stays frozen for this evaluation.

**2. Cues misfire on conversations that are already resolved — 4 over-escalations.**
G035 ("Huge thanks, now it works!") escalated with `STEPS_FAILED`; G112 ("the problem was fixed by
your online support team") with `REPEAT_CONTACT`. In both the agent identified the state correctly
as `acknowledgement_closing` and escalated anyway, because cue extraction reads past-tense
resolution language as an unresolved complaint. **Fix:** suppress cues when the state carries no
intent — a closed conversation cannot have failed steps.

**3. The two under-escalations have different causes, and only one is an intent failure.**
G156's gold intent `support_process_complaint` escalates unconditionally under rule (b); the agent
predicted `enforcement_safety` and auto-handled, so **the intent error directly caused the miss**.
G122 is not that: its gold intent alone would *not* escalate (verified against the policy), so the
human escalated on cues the agent failed to detect. **Fix:** treat intent errors on always-escalate
intents as a distinct safety metric; they are not interchangeable with cue misses.

**4. Follow-up detection — 13 state errors, dominated by `issue_followup` → `new_issue` (4).**
Evaluation is single-turn over a reconstructed context window, so a follow-up that does not
reference its own history looks like a fresh issue. **Fix:** thread-level features, not more prompt.

**5. Intent boundaries are diffuse — 26 intent errors, no pair above 2.**
`hardware_devices` ↔ `software_game_app` (4 combined), `entitlements` → `install_download_update`
(2). These are genuinely ambiguous ("I can't launch Fortnite, it asks if I own a disc"). **Fix:**
sharpen the codebook's exclude lists; expect limited headroom.

**Response-side (dev only, 15 drafted replies).** Retrieval returned 5 examples for 13 of 15 items,
3 for one, and **0 for one** — that item (D25) had its draft rejected twice and escalated with
`REPLY_FAILED_CHECKS`, which is the designed behaviour working unprompted. Five of fifteen drafts
copied the corpus's `<URL>` redaction placeholder into customer-facing text and were caught only
after a post-hoc audit added a rule for it.

## What is misleading about my headline number?

**0.71 joint routing correctness is the honest headline, and it still means 29% of items carry at
least one routing error.** Beyond that:

- **The golden evaluation scores routing only.** Retrieval, drafting and validation are *never*
  scored on golden. Reply quality is currently **unmeasured** — the judge is probed and its rubric
  drafted, but human calibration is still in progress. Nothing here says the replies are good.
- **The 200 items are not a production mix.** 120 random + 80 deliberately stratified toward hard
  escalation cases. The blended headline sits between the two slices (0.74 random, 0.66 stratified)
  and matches neither real traffic nor the hardest cases.
- **"Gold" is one person plus an assistant.** A single labeller — who also wrote the codebook and
  the escalation policy — labelled all 200. A blind second-opinion model disagreed somewhere on
  **61 of the 200 items (30%)**, giving 86 field-level disagreements; **83 of those were
  adjudicated by the assistant**, not by a second independent human, changing 39 fields across 29
  items. **Single-labeller self-consistency was never measured**, so annotation repeatability is
  unknown.
- **`must_escalate_recall_cue_blind` is a proxy.** The locked sheet has no cue, risk or reason
  columns, so risk is derived cue-blind from the gold intent. It **under-counts** the true
  must-escalate set (denominator 25) and is not the metric originally specified.
- **The confidence intervals are not significance tests.** Percentile bootstrap only; no paired
  test was run, so no difference between systems here is "statistically significant". In ~2.2% of
  resamples a rare intent vanishes and macro-F1 averages over fewer classes.
- **Three per-intent scores are unusable.** `install_download_update` (n=4),
  `support_process_complaint` (n=5), `needs_more_context` (n=7).
- **Model selection was not independent.** Dev labels were ChatGPT-drafted and human-approved, so
  the A/B that chose the production router is a tuning signal, not a result.
- **One baseline is contaminated and excluded.** `keyword_rule`'s regexes were written after the
  assistant had read 61 golden messages during adjudication.
- **The judge shares a vendor with the agent.** Different family, same provider — weaker than
  cross-vendor separation.
- **The data is 2017, English-filtered heuristically** (one Portuguese item survived into dev), and
  **52% of held-out DM deflections reuse a training template**, so scoring a draft against the
  historical reply rewards copying a canned answer.

## What was not built

Weak-supervision at scale (~2k labels) was planned and deliberately dropped after baselines showed
it was not the bottleneck. The judge's golden run, reply-quality metrics, and judge–human κ do not
exist yet. Optional Postgres/Redis/Slack adapters remain stubs, never used by evaluation.

## Reproducing this

See [README](README.md#reproducing-the-headline-numbers). In short: `make eval` regenerates every
number above from the committed cache in **~85 seconds with zero API calls**. A genuinely fresh
live rerun is a different proposition — 162 model calls, ~655k tokens, and, on the free tier this
was built against, **three days across seven quota windows**.
