"""Human-vs-judge agreement on ordinal 1-5 ratings.

Reported per dimension, because a single headline number would hide that a judge can track a human
closely on conciseness and not at all on safety:

- **quadratic-weighted kappa** -- ordinal, so 5-vs-4 costs far less than 5-vs-1, and chance-corrected.
- **exact** and **within-1** agreement -- plain, readable, and honest about a 5-point scale where
  neighbouring scores are barely distinguishable.
- **signed bias** (judge minus human) -- catches a systematically generous judge, which kappa alone
  can miss.

Percentile bootstrap CIs use the same machinery and seed as `src/eval/metrics.py`. With a
calibration set of ~15 items these intervals are wide, and that is the point: they stop a single
flattering kappa from being read as proof the judge works.

scipy is not a declared dependency here, so weighting comes from sklearn.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.metrics import cohen_kappa_score

BOOTSTRAP = 10_000
SEED = 42


@dataclass(frozen=True)
class Agreement:
    """One dimension's agreement, with the interval that says how much to trust it."""
    dimension: str
    n: int
    weighted_kappa: float
    kappa_ci: tuple[float, float]
    exact: float
    within_one: float
    bias: float
    human_mean: float
    judge_mean: float


def weighted_kappa(human: np.ndarray, judge: np.ndarray) -> float:
    """Quadratic-weighted kappa. NaN when either side used a single value, where kappa is undefined."""
    if len(human) == 0 or len(np.unique(human)) < 2 or len(np.unique(judge)) < 2:
        return float("nan")
    return float(cohen_kappa_score(human, judge, weights="quadratic",
                                   labels=[1, 2, 3, 4, 5]))


def _bootstrap_kappa(human: np.ndarray, judge: np.ndarray, n_boot: int, seed: int
                     ) -> tuple[float, float]:
    if len(human) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(human), len(human))
        value = weighted_kappa(human[idx], judge[idx])
        if not np.isnan(value):
            draws.append(value)
    if not draws:
        return (float("nan"), float("nan"))
    return tuple(float(v) for v in np.percentile(draws, [2.5, 97.5]))


def score_agreement(dimension: str, human: list[int], judge: list[int], *,
                    n_boot: int = BOOTSTRAP, seed: int = SEED) -> Agreement:
    h, j = np.asarray(human, dtype=float), np.asarray(judge, dtype=float)
    if len(h) != len(j):
        raise ValueError(f"{dimension}: {len(h)} human ratings but {len(j)} judge ratings")
    gap = np.abs(h - j)
    return Agreement(
        dimension=dimension,
        n=len(h),
        weighted_kappa=weighted_kappa(h, j),
        kappa_ci=_bootstrap_kappa(h, j, n_boot, seed),
        exact=float((gap == 0).mean()) if len(h) else float("nan"),
        within_one=float((gap <= 1).mean()) if len(h) else float("nan"),
        bias=float((j - h).mean()) if len(h) else float("nan"),
        human_mean=float(h.mean()) if len(h) else float("nan"),
        judge_mean=float(j.mean()) if len(h) else float("nan"))


def agreement_table(rows: list[Agreement]) -> list[str]:
    lines = ["| dimension | n | weighted κ [95% CI] | exact | within 1 | bias (judge−human) | "
             "human mean | judge mean |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        kappa = "–" if np.isnan(r.weighted_kappa) else f"{r.weighted_kappa:.2f}"
        ci = ("–" if np.isnan(r.kappa_ci[0])
              else f"[{r.kappa_ci[0]:.2f}–{r.kappa_ci[1]:.2f}]")
        lines.append(f"| `{r.dimension}` | {r.n} | {kappa} {ci} | {r.exact:.0%} | "
                     f"{r.within_one:.0%} | {r.bias:+.2f} | {r.human_mean:.2f} | "
                     f"{r.judge_mean:.2f} |")
    return lines


__all__ = ["Agreement", "score_agreement", "agreement_table", "weighted_kappa"]
