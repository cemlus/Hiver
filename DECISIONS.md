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
