"""Tests for re-thresholding a scored shoot."""

from __future__ import annotations

from itertools import pairwise

from gerry.core.threshold_view import (
    ScoredItem,
    suggest_thresholds,
    summarise,
    verdict_at,
)


def item(q: float | None, *, auto: bool = False, override: str | None = None) -> ScoredItem:
    return ScoredItem("f.jpg", q, auto_rejected=auto, override=override)


class TestVerdictAt:
    def test_above_threshold_keeps(self):
        assert verdict_at(item(90), 83) == "keep"

    def test_below_threshold_rejects(self):
        assert verdict_at(item(50), 83) == "reject"

    def test_boundary_is_inclusive(self):
        assert verdict_at(item(83), 83) == "keep"

    def test_unscored_stays_unscored(self):
        assert verdict_at(item(None), 83) == "unscored"

    def test_auto_rejected_stays_rejected_however_high_the_score(self):
        assert verdict_at(item(99, auto=True), 10) == "reject"

    def test_override_beats_the_threshold(self):
        assert verdict_at(item(10, override="keep"), 83) == "keep"

    def test_override_beats_auto_rejection(self):
        # The photographer's call is final -- that's what overriding means.
        assert verdict_at(item(5, auto=True, override="keep"), 83) == "keep"

    def test_lowering_the_threshold_can_only_add_keeps(self):
        it = item(60)
        assert verdict_at(it, 83) == "reject"
        assert verdict_at(it, 43) == "keep"


class TestSummarise:
    def test_counts_split_correctly(self):
        items = [item(90), item(85), item(40), item(None)]
        s = summarise(items, 83)
        assert (s.keep, s.not_keep, s.unscored) == (2, 1, 1)
        assert s.total == 4

    def test_keep_pct_excludes_unscored(self):
        # 1 keep of 2 scored frames = 50%, not 33%
        s = summarise([item(90), item(10), item(None)], 83)
        assert s.keep_pct == 50.0

    def test_keep_pct_on_empty_is_zero_not_a_crash(self):
        assert summarise([], 83).keep_pct == 0.0

    def test_counts_overrides(self):
        s = summarise([item(90, override="reject"), item(90)], 83)
        assert s.overridden == 1
        assert s.keep == 1

    def test_lower_threshold_never_reduces_keeps(self):
        items = [item(float(q)) for q in range(0, 100, 7)]
        assert summarise(items, 40).keep >= summarise(items, 80).keep


class TestSuggestThresholds:
    def test_default_range(self):
        out = suggest_thresholds([item(50)])
        assert out[0].threshold == 30
        assert out[-1].threshold == 95

    def test_keeps_are_monotonically_non_increasing(self):
        items = [item(float(q)) for q in range(10, 100, 3)]
        counts = [s.keep for s in suggest_thresholds(items)]
        assert all(a >= b for a, b in pairwise(counts))

    def test_accepts_custom_candidates(self):
        out = suggest_thresholds([item(50)], candidates=[43.0, 83.0])
        assert [s.threshold for s in out] == [43.0, 83.0]
