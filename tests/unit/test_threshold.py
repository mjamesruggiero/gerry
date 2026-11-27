"""Tests for threshold selection (ADR 0003)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from gerry.evals.threshold import (
    best_f1,
    best_threshold_for_precision,
    evaluate_threshold,
    format_sweep,
    sweep,
)

# 10 frames: scores correlate with labels but imperfectly
SCORES = {
    "a": 95.0,
    "b": 90.0,
    "c": 85.0,
    "d": 70.0,
    "e": 65.0,
    "f": 55.0,
    "g": 40.0,
    "h": 30.0,
    "i": 20.0,
    "j": 10.0,
}
LABELS = {
    "a": "keep",
    "b": "keep",
    "c": "keep",
    "d": "reject",
    "e": "keep",
    "f": "reject",
    "g": "reject",
    "h": "reject",
    "i": "reject",
    "j": "reject",
}


class TestEvaluateThreshold:
    def test_high_threshold_is_precise(self):
        p = evaluate_threshold(SCORES, LABELS, 85.0)
        assert p.predicted_keeps == 3  # a, b, c
        assert p.precision == 1.0  # all three really are keeps
        assert p.recall == 0.75  # missed e

    def test_low_threshold_catches_everything(self):
        p = evaluate_threshold(SCORES, LABELS, 0.0)
        assert p.predicted_keeps == 10
        assert p.recall == 1.0
        assert p.precision == 0.4  # 4 keeps of 10

    def test_threshold_above_all_scores(self):
        p = evaluate_threshold(SCORES, LABELS, 100.0)
        assert p.predicted_keeps == 0
        assert p.is_degenerate

    def test_boundary_is_inclusive(self):
        # a score exactly at the threshold counts as keep
        assert evaluate_threshold({"x": 70.0}, {"x": "keep"}, 70.0).predicted_keeps == 1

    def test_ignores_frames_missing_from_either_side(self):
        assert evaluate_threshold({"a": 90.0, "zz": 90.0}, {"a": "keep"}, 50.0).predicted_keeps == 1


class TestSweep:
    def test_covers_the_range(self):
        pts = sweep(SCORES, LABELS, 0, 100, 25)
        assert [p.threshold for p in pts] == [0, 25, 50, 75, 100]

    def test_recall_is_monotonically_non_increasing(self):
        pts = sweep(SCORES, LABELS, 0, 100, 10)
        recalls = [p.recall for p in pts]
        assert all(a >= b for a, b in pairwise(recalls))

    def test_rejects_bad_step(self):
        with pytest.raises(ValueError, match="step"):
            sweep(SCORES, LABELS, step=0)


class TestBestThresholdForPrecision:
    def test_finds_a_qualifying_point(self):
        pts = sweep(SCORES, LABELS, 0, 100, 5)
        best = best_threshold_for_precision(pts, 0.75, min_predicted_keeps=3)
        assert best is not None
        assert best.precision >= 0.75

    def test_maximises_recall_among_qualifiers(self):
        pts = sweep(SCORES, LABELS, 0, 100, 5)
        best = best_threshold_for_precision(pts, 0.60, min_predicted_keeps=3)
        others = [p for p in pts if p.precision >= 0.60 and p.predicted_keeps >= 3]
        assert best is not None
        assert best.recall == max(o.recall for o in others)

    def test_returns_none_when_target_unreachable(self):
        # nothing can reach precision 1.0 with >= 8 keeps on this data
        pts = sweep(SCORES, LABELS, 0, 100, 5)
        assert best_threshold_for_precision(pts, 1.0, min_predicted_keeps=8) is None

    def test_guards_the_degenerate_corner(self):
        # a threshold keeping 1 correct frame shows precision 1.0 but is useless
        pts = sweep(SCORES, LABELS, 0, 100, 5)
        best = best_threshold_for_precision(pts, 0.9, min_predicted_keeps=3)
        if best is not None:
            assert best.predicted_keeps >= 3


class TestBestF1:
    def test_picks_the_balanced_point(self):
        pts = sweep(SCORES, LABELS, 0, 100, 5)
        best = best_f1(pts, min_predicted_keeps=3)
        assert best is not None
        viable = [p for p in pts if p.predicted_keeps >= 3]
        assert best.f1 == max(p.f1 for p in viable)

    def test_none_when_nothing_viable(self):
        assert best_f1(sweep(SCORES, LABELS, 0, 100, 5), min_predicted_keeps=999) is None


class TestFormatSweep:
    def test_renders_rows_and_marks_qualifiers(self):
        out = format_sweep(sweep(SCORES, LABELS, 0, 100, 25), 0.75)
        assert "precision" in out
        assert "meets target" in out
