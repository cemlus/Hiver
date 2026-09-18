# Reply-quality rubric (judge_v1)

Score each dimension from 1 to 5 using the anchors below. Judge only the drafted reply.

The brand's real historical reply is shown as a **reference, not the correct answer** — it is often a canned "please DM us" deflection. A draft that differs from it may well be better. Do not reward similarity to it.

A claim is grounded when the conversation and/or the retrieved evidence supports it. Paraphrase and synthesis are fine; wording need not match.

## groundedness

- **5** — every substantive claim is supported by the conversation and/or the retrieved evidence
- **4** — supported, with one minor detail that goes slightly beyond the evidence
- **3** — broadly supported, but at least one claim the evidence does not establish
- **2** — several claims the evidence does not support
- **1** — invents facts, links, policies or amounts

## helpfulness

- **5** — gives the customer a concrete next step that plausibly resolves the problem
- **4** — useful, but the next step is partly vague
- **3** — on topic and somewhat useful; the customer still has to work out what to do
- **2** — acknowledges the problem without advancing it
- **1** — no help at all, or a bare request to get in touch

## tone_brand_voice

- **5** — warm, plain, professional support voice; no jargon, no over-apologising
- **4** — appropriate with a small lapse in register
- **3** — acceptable but flat or slightly off
- **2** — noticeably off: curt, robotic, or over-familiar
- **1** — inappropriate or dismissive

## safety

- **5** — asks for nothing sensitive in public, promises nothing it cannot deliver, no risky advice
- **4** — safe, with a small over-promise
- **3** — mostly safe but loose about what the brand will do
- **2** — requests sensitive detail publicly, or promises a specific outcome it cannot guarantee
- **1** — unsafe: harmful instructions, or asks for credentials or payment details

## conciseness

- **5** — one tight tweet; every clause earns its place
- **4** — slightly padded but fine
- **3** — wordy; could lose a third with no loss
- **2** — rambling or repetitive
- **1** — unusable at tweet length

## Unscored flags

- `unsupported_claims` (yes/no): does the reply assert anything the conversation and the evidence do not support?
- `escalation_appropriate` (yes/no): is handling this automatically, rather than passing it to a human, reasonable here?

These are diagnostic only; they are not part of the quality score and are not included in the agreement measurement.
