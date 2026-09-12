# Golden set: labelling and reconciliation protocol

The golden set is the evaluation set behind every headline number. It is labelled **human first**.
Model labels come afterwards, as a second opinion, and never replace the human labels silently.

## Files

| file | layer | who writes it | editable? |
|---|---|---|---|
| `golden_sample_key.csv` | sample | `scripts/sample_golden.py` | never (regenerate only before labelling starts) |
| `golden_labeling_sheet.md` | reading copy | `scripts/sample_golden.py` | never |
| `golden_labeling_sheet.csv` | **1. primary human gold** | the project owner | until finished; then locked by `golden.lock` |
| `golden.lock` | lock | written once labelling is finished | never |
| `golden_llm_labels.csv` | **2. LLM second opinion** | a script, after the lock | regenerated only by that script |
| `golden_adjudication.csv` | adjudication log | human, one row per resolved disagreement | append-only |
| `golden_final.csv` | **3. final adjudicated gold** | generated from layers 1 + log | never by hand |

## Sampling

- 200 holdout items, drawn only after the taxonomy and the escalation policy were frozen:
  - **120 random**, drawn first, so this slice is unbiased.
  - **80 stratified**: 10 each for account security, enforcement, support complaints,
    purchases/billing, codes/subscriptions, vague messages, anger, and follow-ups that report
    failed steps. Strata are keyword candidate finders, not labels. Metrics are reported per slice.
- **Exclusions:**
  - every dev thread
  - any near-duplicate (char TF-IDF cosine ≥ 0.95) of a train message or a dev message
  - more than one item per thread
  - near-duplicate pairs inside golden
- The sheet is blind: no slice, no historical brand reply, no model labels.

## Step 1: primary human labels (the project owner)

1. Read `golden_labeling_sheet.md` (context and message, plus a quick reference to the frozen
   codebook). The full rules are in `data/codebook.md`.
2. In `golden_labeling_sheet.csv`, fill the **scored** columns for all 200 rows:
   - `conversation_state`
   - `intent` (blank for `acknowledgement_closing` and `social_offtopic`)
   - `escalate` (`yes` / `no`)
   - `label_confidence` (`high` / `medium` / `low`)
3. The reference columns are optional and never scored: `secondary_intents`, `risk_level`,
   `reason_code`, `cue_*` and `notes`. Use `notes` for ambiguous cases.
4. **Don't look at Claude or ChatGPT labels for these items until all 200 are done.** Asking a
   model about the codebook in general is fine; asking it to label golden items is not.
5. Don't reorder rows or edit `golden_id` / `record_id`.
6. When finished, fill in the labelling log below. Then the sheet is locked: its SHA-256 goes
   into `golden.lock`, and `tests/test_golden_integrity.py` fails if the file ever changes.

## Step 2: LLM second opinion

After the lock, an LLM labels the same 200 items with the same codebook. It does not see the human
labels, and its output goes to `golden_llm_labels.csv` with the model name and codebook version.

## Step 3: adjudication

- Every item where a scored field differs between layers 1 and 2 is reviewed.
- Each resolution is one row in `golden_adjudication.csv`:
  - `golden_id`, `field`, `human`, `llm`
  - `final`
  - `decided_by`, `rationale`
- "Human label kept" is a valid outcome and is recorded as well.
- `golden_final.csv` is generated from the human file plus the log, and is never edited by hand.

## How the report uses the layers

- Headline metrics use **final adjudicated labels**. The same metrics are also reported against the
  **primary human labels** as a sensitivity check.
- Human–LLM agreement is reported per scored field (percent agreement and Cohen's κ), together with
  how many labels adjudication changed and in which direction.
- The LLM judge (Phase 9) is validated against the human layer, never against LLM labels.

## Rules for using golden

- **Evaluation only.** Golden items are never used to train, as few-shot examples, in the retrieval
  index, or to tune prompts, thresholds or rules.
- Error analysis may read golden results. Any change it prompts is reported as a post-hoc change,
  and it is re-checked on dev rather than on golden.

## Dev set provenance, for contrast

The 40 dev items (`dev_labeling_sheet.csv`) were labelled differently: ChatGPT drafted them with the
codebook and the project context, and the project owner reviewed and approved them. Those drafts
applied the same rules the calibration tested, so the dev calibration's 40/40 agreement is partly
circular and is **not** independent validation. Golden is labelled human-first for exactly this
reason.

## Labelling log

- **Labeller:** the project owner, alone, without seeing any model-generated labels.
- **Dates:** finished 2026-09-12. Codebook version: v1 (taxonomy and escalation frozen 2026-09-11).
- **Fields:** only the four scored fields were kept (`conversation_state`, `intent`, `escalate`,
  `label_confidence`). The optional cue, risk and reason columns were dropped; nothing is scored on
  them.
- **Checked** with `scripts/check_golden_labels.py` (read-only): 0 blocking problems. It found an
  invalid byte in one intent cell and 6 blank cells, and the labeller fixed them before the lock.
- **Locked:** `golden.lock` holds the SHA-256 of the sheet, and `tests/test_golden_integrity.py`
  fails if the file changes.
- **Self-consistency was not measured.** The planned 30-item blind re-label was dropped for time,
  so single-labeller repeatability (κ) is unknown. The report must say so. Human–LLM agreement is
  the only labelling-reliability number we will have.

## Known human-vs-policy divergences (deliberate, not errors)

Three items are labelled `escalate = no` although the frozen policy escalates every
`purchases_billing_orders` case (rule b):

| item | message | labeller's reasoning |
|---|---|---|
| G064 | "how do I initiate a digital refund?" | a how-to question; a policy explanation answers it safely |
| G079 | "I would like to refund my order of Fallout 4, would that be possible?" | same: explain the refund rules first |
| G179 | "I can't purchase any items for my avatar" | first-line help is appropriate before a handoff |

Escalation is appropriate if the issue repeats or turns into a dispute. The labels stand, the
policy stays frozen for this evaluation, and the agent will be scored wrong on these three items.
The mismatch is reported as a **policy over-escalation finding**, never reconciled away.
