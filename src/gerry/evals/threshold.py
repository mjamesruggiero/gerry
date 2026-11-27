"""Choosing the decision threshold from data.

v1-v3 showed that rewording the prompt moves the precision/recall operating
point without improving discrimination (ADR 0003). So the model is asked to
*rank* frames with a 0-100 quality score, and the cut point between keep and
not-keep is chosen here, against the golden set.

That makes the operating point an explicit, tunable decision rather than an
emergent property of prompt wording. Pure functions throughout -- the sweep
runs offline on stored scores, at no model cost.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdPoint:
    """Performance at one candidate cut point."""

    threshold: float
    predicted_keeps: int
    precision: float
    recall: float
    f1: float

    @property
    def is_degenerate(self) -> bool:
        """Precision is vacuously 1.0 when almost nothing is kept."""
        return self.predicted_keeps == 0


def evaluate_threshold(
    scores: Mapping[str, float], labels: Mapping[str, str], threshold: float
) -> ThresholdPoint:
    """Precision/recall if we called `keep` at or above `threshold`. Pure."""
    shared = sorted(set(scores) & set(labels))
    tp = fp = fn = 0
    for name in shared:
        predicted_keep = scores[name] >= threshold
        actual_keep = labels[name] == "keep"
        if predicted_keep and actual_keep:
            tp += 1
        elif predicted_keep:
            fp += 1
        elif actual_keep:
            fn += 1

    pk = tp + fp
    precision = tp / pk if pk else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return ThresholdPoint(threshold, pk, precision, recall, f1)


def sweep(
    scores: Mapping[str, float],
    labels: Mapping[str, str],
    start: float = 0.0,
    stop: float = 100.0,
    step: float = 5.0,
) -> list[ThresholdPoint]:
    """Performance across a range of candidate thresholds. Pure."""
    if step <= 0:
        raise ValueError("step must be positive")
    points: list[ThresholdPoint] = []
    t = start
    while t <= stop:
        points.append(evaluate_threshold(scores, labels, t))
        t += step
    return points


def best_threshold_for_precision(
    points: list[ThresholdPoint],
    target_precision: float,
    *,
    min_predicted_keeps: int = 10,
) -> ThresholdPoint | None:
    """Lowest threshold meeting the precision target, maximising recall.

    `min_predicted_keeps` guards the degenerate corner where a very high
    threshold keeps two frames, both correct, and reports precision 1.0.
    That is technically true and operationally useless.

    Returns None when no threshold reaches the target -- a real answer,
    meaning the target is unachievable with this model and prompt.
    """
    viable = [
        p
        for p in points
        if p.precision >= target_precision and p.predicted_keeps >= min_predicted_keeps
    ]
    if not viable:
        return None
    return max(viable, key=lambda p: (p.recall, -p.threshold))


def best_f1(
    points: list[ThresholdPoint], *, min_predicted_keeps: int = 10
) -> ThresholdPoint | None:
    """The balanced operating point, for comparison."""
    viable = [p for p in points if p.predicted_keeps >= min_predicted_keeps]
    if not viable:
        return None
    return max(viable, key=lambda p: (p.f1, -p.threshold))


def format_sweep(points: list[ThresholdPoint], target_precision: float) -> str:
    """Render the sweep as a readable table. Pure."""
    lines = [
        f"{'thresh':>7} {'keeps':>6} {'precision':>10} {'recall':>8} {'F1':>7}",
        "-" * 42,
    ]
    for p in points:
        marker = (
            "  <- meets target" if p.precision >= target_precision and not p.is_degenerate else ""
        )
        lines.append(
            f"{p.threshold:>7.0f} {p.predicted_keeps:>6} {p.precision:>10.3f} "
            f"{p.recall:>8.3f} {p.f1:>7.3f}{marker}"
        )
    return "\n".join(lines)
