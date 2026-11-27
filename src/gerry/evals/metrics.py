"""Eval metrics. Pure -- no I/O, no model calls.

The gate that blocks merges is only as trustworthy as these functions, so
they are deliberately simple and exhaustively tested.

Why keep-precision is the headline metric: a false "keep" puts a bad frame in
front of a paying client, while a false "reject" only buries a good one that
the photographer reviews anyway. The costs are asymmetric, so the gate is too.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

VERDICTS = ("keep", "maybe", "reject")


@dataclass(frozen=True)
class ConfusionCounts:
    """Binary confusion matrix for the 'keep' decision."""

    true_positive: int = 0  # predicted keep, labeled keep
    false_positive: int = 0  # predicted keep, NOT labeled keep  <- the costly one
    false_negative: int = 0  # labeled keep, not predicted keep
    true_negative: int = 0

    @property
    def total(self) -> int:
        return self.true_positive + self.false_positive + self.false_negative + self.true_negative


@dataclass(frozen=True)
class EvalResult:
    """Everything the CI gate needs to make a pass/fail decision."""

    n: int
    keep_precision: float
    keep_recall: float
    agreement: float
    cost_total_usd: float
    cost_per_100_usd: float
    p95_latency_ms: int
    confusion: ConfusionCounts

    def as_dict(self) -> dict[str, float | int]:
        return {
            "n": self.n,
            "keep_precision": round(self.keep_precision, 4),
            "keep_recall": round(self.keep_recall, 4),
            "agreement": round(self.agreement, 4),
            "cost_total_usd": round(self.cost_total_usd, 4),
            "cost_per_100_usd": round(self.cost_per_100_usd, 4),
            "p95_latency_ms": self.p95_latency_ms,
        }


def confusion_for_keep(predicted: Mapping[str, str], labeled: Mapping[str, str]) -> ConfusionCounts:
    """Binary confusion counts over frames present in both mappings. Pure."""
    shared = sorted(set(predicted) & set(labeled))
    tp = fp = fn = tn = 0
    for key in shared:
        p_keep = predicted[key] == "keep"
        l_keep = labeled[key] == "keep"
        if p_keep and l_keep:
            tp += 1
        elif p_keep and not l_keep:
            fp += 1
        elif not p_keep and l_keep:
            fn += 1
        else:
            tn += 1
    return ConfusionCounts(tp, fp, fn, tn)


def precision(counts: ConfusionCounts) -> float:
    """Of the frames we called keep, how many should have been kept?

    Vacuously 1.0 when nothing was predicted keep -- you cannot send a client
    a bad frame if you sent none. Recall is what catches that degenerate case.
    """
    denom = counts.true_positive + counts.false_positive
    return 1.0 if denom == 0 else counts.true_positive / denom


def recall(counts: ConfusionCounts) -> float:
    """Of the frames that should have been kept, how many did we find?"""
    denom = counts.true_positive + counts.false_negative
    return 1.0 if denom == 0 else counts.true_positive / denom


def agreement(predicted: Mapping[str, str], labeled: Mapping[str, str]) -> float:
    """Exact three-way match rate across keep/maybe/reject. Pure."""
    shared = sorted(set(predicted) & set(labeled))
    if not shared:
        return 0.0
    hits = sum(1 for k in shared if predicted[k] == labeled[k])
    return hits / len(shared)


def percentile(values: list[int], pct: float) -> int:
    """Nearest-rank percentile. Pure, dependency-free, deterministic."""
    if not values:
        return 0
    if not 0 < pct <= 100:
        raise ValueError("pct must be in (0, 100]")
    ordered = sorted(values)
    rank = max(1, int(-(-pct / 100 * len(ordered) // 1)))  # ceil
    return ordered[min(rank, len(ordered)) - 1]


def evaluate(
    predicted: Mapping[str, str],
    labeled: Mapping[str, str],
    costs_usd: list[float] | None = None,
    latencies_ms: list[int] | None = None,
) -> EvalResult:
    """Aggregate predictions against ground truth. Pure."""
    counts = confusion_for_keep(predicted, labeled)
    costs = costs_usd or []
    latencies = latencies_ms or []
    n = counts.total
    total_cost = sum(costs)
    return EvalResult(
        n=n,
        keep_precision=precision(counts),
        keep_recall=recall(counts),
        agreement=agreement(predicted, labeled),
        cost_total_usd=total_cost,
        cost_per_100_usd=(total_cost / n * 100) if n else 0.0,
        p95_latency_ms=percentile(latencies, 95),
        confusion=counts,
    )
