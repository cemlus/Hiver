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
