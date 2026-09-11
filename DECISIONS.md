# Decision log

A running list of non-obvious decisions and why they were made. `[P#]` is the phase each one
comes from. It will be trimmed to the best 10–15 for submission.

- **[P0] LiteLLM is the only LLM dependency.** It gives one call signature for Anthropic,
  OpenAI, Gemini and Ollama, so the provider is just a config string. Hand-written per-provider
  adapters would be more code to explain, with no benefit to the evaluation.
- **[P0] Structured output = schema in the prompt + pydantic validation + one retry.** We don't
  use provider-native JSON modes because they differ between providers and would break
  provider-agnosticism.
- **[P0] Every LLM call is cached, keyed by (model, system, prompt, params), and the cache is
  committed.** Headline numbers reproduce in minutes with no API key (`LLM_OFFLINE=1`). This
  also means reproducibility doesn't rely on temperature 0, which some models reject anyway.
- **[P0] Empty replies are never cached; the thinking budget and the timeout are config.** Gemini
  2.5 Flash spends "thinking" tokens from `max_tokens` and can return empty text. A cached empty
  reply would poison every rerun, including offline reviewer runs, so the client raises instead.
  `reasoning_effort` and `timeout` are per-role settings in `config.yaml`, not code. LiteLLM's
  default timeout is 6000 s, which would let one hung call stall a bulk labelling job.
- **[P0] Ports & adapters.** Code depends on Protocols (`LLMClient`, `Cache`, `ResultStore`,
  `EscalationSink`). The `eval` profile always uses local defaults, so Postgres, Redis or Slack
  can never block evaluation.
- **[P0] uv + lockfile, CPU-only torch.** Exact pins make installs reproducible. The default
  Linux torch wheel pulls about 2 GB of CUDA libraries we never use, which would eat the
  15-minute reproduction budget.
- **[P0] Local sentence-transformers embeddings (`all-MiniLM-L6-v2`).** Free, deterministic, and
  independent of the LLM provider.
- **[P1] Brand: XboxSupport, chosen on fit, not size.** It was scored on five criteria: volume,
  intent diversity, substantive resolutions, grounding material and noise. It has the highest
  share of substantive replies in the top 15 (20.8%), the longest troubleshooting threads and the
  highest customer follow-up rate.
  - AppleSupport is 4× larger but dominated by one iOS 11 bug, answered with the same canned link
    6,250 times. A golden set drawn from it would inflate the headline numbers.
  - AmazonHelp is only about 81% English, and TMobileHelp is 74% DM-only.

  Evidence: `results/eda.md`.
- **[P1] Count usable exchanges, not brand tweets.** An exchange is one customer tweet plus the
  brand's reply, with split replies (the brand continuing itself within 15 min) merged.
  - 24,557 XboxSupport tweets become 20,213 exchanges, and 18,549 are usable after dropping
    non-English, near-empty, "DM sent" and duplicate tweets.
  - Those come from 12,703 threads (about 1.5 per thread), so splits must be per thread.
  - Only 4,413 got a substantive reply, and that is the grounding pool.

  Evidence: `results/brand_validation.md`.
- **[P1] Outcome heuristics are too sparse to evaluate against.** 439 exchanges end with the
  customer confirming a fix, but a hand check found most were fixed through other channels. Only
  about 80–100 show a public reply that demonstrably worked, and 58% get no customer answer at
  all. Outcome labels may only nudge retrieval re-ranking; evaluation relies on human golden
  labels and the judge.
- **[P1] The codebook needs a "vague / needs more info" intent, and the golden set needs a
  stratified slice.** Keyword draft intents leave 42% of usable tweets unmatched, mostly vague
  help requests and context-dependent follow-ups. The rarest intents (bans, codes,
  subscriptions) would get only about 3 examples each in a 120-item random slice.
- **[P1] Analysis lives in plain, rerunnable scripts with hand-checked heuristics.**
  - `scripts/eda.py` and `scripts/validate_brand.py` regenerate their reports deterministically.
    Hand-written conclusions sit in a block the scripts preserve on rerun.
  - Every keyword metric was spot-checked on samples and tightened when it misfired. For example,
    T-Mobile's "substantive" replies were really DM invitations.
  - The raw CSV is read with pandas' C engine: 106,891 tweets contain quoted newlines that
    pyarrow's reader rejects.
- **[P2] One exchange = one merged customer message + one merged brand reply, with context.**
  - Split tweets are merged on both sides: the brand continuing itself within 15 min, and the
    customer's own consecutive tweets. Parts are ordered by time, then reply-chain depth, then
    their `1/2` markers.
  - Context is the parent chain as logical turns: the opener plus the last 2 turns, and no turn
    more than 7 days old. A split brand reply is always shown whole.
  - Result: 18,712 usable exchanges, 0.9% more than the Phase 1 funnel.

  Evidence: `results/phase2_data_report.md`, `results/reconstruction_samples.md`.
- **[P2] Strict thread-level time split at 2017-11-15.**
  - Threads starting on or after that date go to holdout. Earlier threads go to train, except
    exchanges written after the date in revived threads, which are `excluded` (117).
  - Every train exchange precedes every holdout thread, and no thread is in both. Both rules
    are tested.
  - The split is 69/31. The holdout is the final ~2.5 weeks, so some topic drift is real.
- **[P2] `substantive` is a retrieval heuristic, not ground truth.** It decides only which train
  replies may enter the grounding corpus (`retrieval_eligible`: 2,711 rows).
  - It is a keyword rule: a guidance cue in a sentence that isn't a DM request, in a reply that
    isn't wholly canned.
  - Hand-sample precision is about 60%, because clarifying questions and status updates that say
    "try", "update" or "steps" slip in.
  - It must never be an evaluation target or a reply-quality label, and retrieval must re-rank
    rather than trust it.
- **[P2] Weak labels are train-only and carry a confidence; customer cues are features.**
  - `weak_outcome`, `outcome_confidence`, `next_customer_text` and `brand_escalation_evidence`
    use the future or the reference reply, so they are null outside train (tested).
  - `customer_escalation_signals` come from the model's input and are kept on every split.
- **[P2] Held-out DM replies heavily reuse training templates.** Customer messages barely
  overlap: only 5 holdout messages have a train near-duplicate (char TF-IDF cosine ≥ 0.95), and
  those are barred from dev and golden. Brand replies are different:

  | Holdout reply type | Reuse a train template |
  |---|---|
  | DM deflection | 690 of 1,331 (52%) |
  | Other | 752 of 3,223 (23%) |
  | Substantive | 66 of 1,249 (5%) |

  So scoring a drafted reply against the historical one rewards copying a canned DM template.
  Reply-quality results must be sliced by `reply_template_in_train`, and a copied DM template
  never counts as a good grounded answer.
- **[P2] Hand inspection of reconstructed exchanges found six bugs the tests had missed.** Each
  fix below has a unit test. Evidence: `results/reconstruction_samples.md`.
- **[P2] Bug 1: split parts posted in the same second came out of order.** Decision: order parts
  by time, then reply-chain depth, then their `1 ^JL` / `2/2` marker. Misordered merged replies
  fell from 108 to 9 of 3,604. The 9 left keep time order: the brand posted part 2 first, or
  re-posted a cut-off tweet.
- **[P2] Bug 2: context showed only half of a split brand reply.** The customer had answered part
  2, and part 1 wasn't on the parent chain. Decision: a brand turn in context always shows the
  whole merged reply. 56 of 6,218 brand turns are still fragments, where part 1 isn't anchored.
- **[P2] Bug 3: replies to brand announcements counted as follow-ups.** Decision: a follow-up
  must answer a brand *reply*. Answering a brand tweet that replies to nobody is a first contact,
  with the announcement kept as context. About 900 exchanges were reclassified.
- **[P2] Bug 4: revived threads.** A 2017 message answering a 2014 tweet carried 2014 context,
  and because its thread started early it landed in train despite being written after the split
  date. Decisions: context turns more than 7 days older than the message are dropped (163
  contexts cut), and exchanges written after the split date in earlier threads are `excluded`
  (117).
- **[P2] Bug 5: DM requests counted as substantive** ("…so we can have you try a few steps",
  "Can you DM us what you see when you try…"). Decision: guidance must sit in a sentence that
  isn't a DM request, and phrases about the customer's own attempts don't count. Substantive
  replies that also ask for a DM fell from 488 to 226.
- **[P2] Bug 6: sign-offs glued to the text** (`details?^EZ`, `.^IS`) stayed in clean replies
  after a fix meant to protect "Wi-Fi". The integrity test caught it during the same review.
  Decision: a `^` tag needs no space before it; `*`, `/` and `-` tags still do. Leftover markers
  fell from 0.57% to below the test's 0.5% limit.
- **[P3] Taxonomy v1 is frozen: 11 primary intents and 4 conversation states.**
  - It was curated by hand around distinct reply and escalation strategies. Clustering was only
    exploratory evidence.
  - The codebook (`data/codebook.md`) is generated from `data/taxonomy/taxonomy_v1.yaml`, and
    `tests/test_taxonomy_frozen.py` pins the names. Changing them means a new version and
    relabelling.
- **[P3] Conversation state is scored separately from intent.** Closing and social messages carry
  no intent and are scored as state accuracy, so easy "thanks!" messages can't inflate intent
  scores. S1: `acknowledgement_closing` requires that no unresolved issue remains. "Will try
  tonight" and "I'll get back to you" are `issue_followup`.
- **[P3] Exactly one primary intent is scored.** T0 picks it for multi-issue messages: the higher
  default risk wins, and ties go to the issue mentioned first. `secondary_intents`, `subtype` and
  `event_tag` are internal and never scored.
- **[P3] v1 merges.** `software_game_app` and `entitlements_subscriptions_codes` stay merged, with
  internal subtypes. `product_info_feedback` stays merged. Controllers stay in `hardware_devices`.
  `purchases_billing_orders` stays separate because it always escalates.
- **[P3] Risk and escalation are an overlay, not intents.** Hacked accounts, anger and threats are
  risk rules applied on top of any intent. `account_access_profile` has default risk medium, not
  high, so general how-to questions can still be auto-handled.
- **[P3] The escalation policy was calibrated on a 40-item dev set before freezing.** 16 random +
  24 targeted at the six behaviours in the codebook, drawn blind from the holdout. The golden set
  is not sampled until the policy is frozen, and it must exclude every dev thread.
- **[P3] Dev labels are ChatGPT drafts reviewed and approved by the project owner, not blind human
  labels.** The plan asked for no model pre-fill. For dev, which only tunes the policy, this was
  accepted. It does make agreement with the draft partly circular, because the drafts applied the
  draft rules, so the calibration mostly shows that the rules can be applied consistently. Fixes
  made after review are recorded in each item's `notes`. The golden set should get a blind human
  first pass, because the judge–human agreement result depends on it.
- **[P3] Escalation policy frozen after dev calibration (2026-09-11).** Evidence:
  `results/escalation/dev_calibration.md`, from `scripts/calibrate_escalation.py`.
  - **C1, the one change in behaviour:** "the steps already failed" is split out of
    `repeat_contact`. Failed steps escalate on any intent (STEPS_FAILED). A stated repeat contact on
    its own only raises the risk to medium. Read literally, the draft auto-handled D26, D31 and D35,
    which the labels escalate. D01 (repeat contact only) is labelled auto.
  - **C2–C6 only tighten the wording:**
    - a new `STEPS_FAILED` reason code
    - `REPLY_FAILED_CHECKS` reserved for the agent's own failed reply validation
    - `strong_anger` needs profanity, abuse or a threat to leave
    - explicit hardware-repair and account-specific triggers
    - a definition of the `prior_clarification` cue
  - **Untested on dev, kept as drafted:**
    - a second vague message after a clarification escalates (no dev item was vague after one)
    - low confidence (a Phase 7 threshold)
    - OUT_OF_SCOPE
  - **The main cost of C1 is escalation volume.** Watch the precision of STEPS_FAILED escalations on
    golden.
- **[P3] Dev item D12 (`2802886`) is Portuguese and stays in the dev set.** It got past the
  heuristic language filter. Its English function words ("of", "the") come from the game title
  *Symphony of the Night*, so they tie the Portuguese ones ("não", "por") at 2–2, and a tweet is
  dropped only when the foreign count is strictly higher.
  - D12 is not redrawn: removing inconvenient items after the draw would bias the dev set.
  - It is labelled per the codebook like any other item, and shows that non-English tweets reach
    the eval pool. The golden set will get the same handling and be sliced by language.
- **[P3] The 150-row coding sample is discovery evidence, not gold.** It is from train, coded by
  one person while drafting, so it can never enter dev or golden.
- **[P3] Evaluation metrics were fixed before any labels were collected:**
  - state accuracy and macro-F1
  - intent macro-F1 conditional on intent-bearing gold states, plus per-intent F1 and a confusion
    matrix
  - escalation precision and recall, plus must-escalate recall
  - joint routing correctness
- **[P3] Temporal risk is recorded, not hidden.** In the discovery sample, many intents lean on
  train-period events: 5 of 7 purchases cases (the Friday the 13th sale, One X pre-orders), and 5
  of 12 connectivity and 5 of 14 entitlements cases. Golden results will be sliced by event-tied
  vs not.
