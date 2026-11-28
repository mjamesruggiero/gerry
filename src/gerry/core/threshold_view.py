"""Re-thresholding an already-scored shoot.

Quality scores are stored per frame, so changing the keep/reject cut point
is a pure recomputation -- no model calls, no cost. That makes the operating
point something a photographer can explore by feel on a real shoot rather
than guess at in a config file.

Pure functions; the route layer supplies the frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoredItem:
    """Minimal view of a frame for threshold arithmetic."""

    filename: str
    quality: float | None
    auto_rejected: bool = False
    override: str | None = None


@dataclass(frozen=True)
class ThresholdSummary:
    """What a given cut point would yield for this shoot."""

    threshold: float
    keep: int
    not_keep: int
    unscored: int
    overridden: int

    @property
    def total(self) -> int:
        return self.keep + self.not_keep + self.unscored

    @property
    def keep_pct(self) -> float:
        scored = self.keep + self.not_keep
        return 100.0 * self.keep / scored if scored else 0.0


def verdict_at(item: ScoredItem, threshold: float) -> str:
    """Verdict for one frame at a given threshold. Pure.

    Precedence, highest first:
      1. a human override -- always wins, that's the point of overriding
      2. auto-rejection by the free pre-filter
      3. the model's score against the threshold
    """
    if item.override:
        return item.override
    if item.auto_rejected:
        return "reject"
    if item.quality is None:
        return "unscored"
    return "keep" if item.quality >= threshold else "reject"


def summarise(items: Sequence[ScoredItem], threshold: float) -> ThresholdSummary:
    """Counts at one threshold. Pure."""
    keep = not_keep = unscored = overridden = 0
    for item in items:
        if item.override:
            overridden += 1
        match verdict_at(item, threshold):
            case "keep":
                keep += 1
            case "unscored":
                unscored += 1
            case _:
                not_keep += 1
    return ThresholdSummary(threshold, keep, not_keep, unscored, overridden)


def suggest_thresholds(
    items: Sequence[ScoredItem], candidates: Sequence[float] | None = None
) -> list[ThresholdSummary]:
    """Summaries across candidate cut points, for the UI to render. Pure."""
    if candidates is None:
        candidates = [float(t) for t in range(30, 96, 5)]
    return [summarise(items, t) for t in candidates]
