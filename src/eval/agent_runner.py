"""Run the routing agent over a list of evaluation items and collect run statistics.

Evaluation glue only: the pipeline itself is `src/core/route.py`. Failures are recorded rather than
swallowed, so a partial run can never be mistaken for a complete one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.contracts import AgentOutput, GoldenExample, finalize
from src.core.route import route
from src.ports.protocols import LLMClient


@dataclass
class AgentRun:
    outputs: list[AgentOutput] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    traces: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.failures


def run_agent(examples: list[GoldenExample], llm: LLMClient, *, confidence_threshold: float,
              union_cues: bool = False, system: str = "agent", attempts: int = 3,
              sleep: float = 0.0) -> AgentRun:
    run = AgentRun()
    for example in examples:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                state = route(example.request, llm, confidence_threshold=confidence_threshold,
                              union_cues=union_cues)
                run.outputs.append(finalize(state, system=system,
                                            model_versions={"agent": getattr(llm, "model", "?")}))
                run.latencies_ms.append(state.latency_ms)
                run.traces[example.request.request_id] = state.trace
                break
            except Exception as error:          # noqa: BLE001 - recorded, never hidden
                last_error = error
                if attempt < attempts:
                    time.sleep(sleep * attempt)
        else:
            run.failures.append((example.request.request_id,
                                 f"{type(last_error).__name__}: {str(last_error)[:160]}"))
        if sleep:
            time.sleep(sleep)
    return run
