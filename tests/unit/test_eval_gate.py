"""Tests for the merge gate. A gate that can't fail is theatre, so the
failing paths get the most attention."""

from __future__ import annotations

import json

from gerry.evals.gate import (
    GateThresholds,
    check_gate,
    format_pr_comment,
    load_baseline,
)
from gerry.evals.metrics import ConfusionCounts, EvalResult

THRESHOLDS = GateThresholds(min_keep_precision=0.80, max_cost_increase_pct=20.0)


def result(
    precision: float = 0.9,
    cost_per_100: float = 0.74,
    n: int = 100,
    recall: float = 0.9,
    agreement: float = 0.85,
    confusion: ConfusionCounts | None = None,
) -> EvalResult:
    return EvalResult(
        n=n,
        keep_precision=precision,
        keep_recall=recall,
        agreement=agreement,
        cost_total_usd=cost_per_100 * n / 100,
        cost_per_100_usd=cost_per_100,
        p95_latency_ms=3200,
        confusion=confusion or ConfusionCounts(45, 5, 5, 45),
    )


class TestPrecisionGate:
    def test_passes_above_floor(self):
        assert check_gate(result(precision=0.85), THRESHOLDS).passed

    def test_fails_below_floor(self):
        d = check_gate(result(precision=0.70), THRESHOLDS)
        assert not d.passed
        assert d.failures[0].check == "keep_precision"
        assert "0.700" in d.failures[0].message

    def test_exactly_at_floor_passes(self):
        assert check_gate(result(precision=0.80), THRESHOLDS).passed

    def test_just_below_floor_fails(self):
        assert not check_gate(result(precision=0.7999), THRESHOLDS).passed


class TestCostGate:
    def test_no_baseline_skips_cost_check(self):
        # First run: nothing to compare against. Don't guess.
        d = check_gate(result(cost_per_100=99.0), THRESHOLDS, baseline=None)
        assert d.passed

    def test_cost_increase_within_limit_passes(self):
        base = result(cost_per_100=1.00)
        d = check_gate(result(cost_per_100=1.15), THRESHOLDS, baseline=base)  # +15%
        assert d.passed

    def test_cost_increase_over_limit_fails(self):
        base = result(cost_per_100=1.00)
        d = check_gate(result(cost_per_100=1.30), THRESHOLDS, baseline=base)  # +30%
        assert not d.passed
        assert d.failures[0].check == "cost_per_100"
        assert "30.0%" in d.failures[0].message

    def test_cost_decrease_always_passes(self):
        base = result(cost_per_100=1.00)
        assert check_gate(result(cost_per_100=0.40), THRESHOLDS, baseline=base).passed

    def test_exactly_at_limit_passes(self):
        base = result(cost_per_100=1.00)
        assert check_gate(result(cost_per_100=1.20), THRESHOLDS, baseline=base).passed

    def test_zero_baseline_cost_is_skipped(self):
        base = result(cost_per_100=0.0)
        assert check_gate(result(cost_per_100=5.0), THRESHOLDS, baseline=base).passed


class TestBothFail:
    def test_reports_every_failure_not_just_the_first(self):
        base = result(cost_per_100=1.00)
        d = check_gate(result(precision=0.5, cost_per_100=2.00), THRESHOLDS, baseline=base)
        assert not d.passed
        assert {f.check for f in d.failures} == {"keep_precision", "cost_per_100"}
        assert "FAIL" in d.summary()


class TestPRComment:
    def test_pass_renders_green(self):
        d = check_gate(result(), THRESHOLDS)
        text = format_pr_comment(result(), d)
        assert "✅" in text and "Eval gate passed" in text

    def test_fail_lists_blocking_issues(self):
        r = result(precision=0.5)
        text = format_pr_comment(r, check_gate(r, THRESHOLDS))
        assert "❌" in text
        assert "Blocking issues" in text
        assert "keep-precision" in text

    def test_includes_baseline_diff(self):
        base = result(precision=0.90)
        now = result(precision=0.85)
        text = format_pr_comment(now, check_gate(now, THRESHOLDS, base), baseline=base)
        assert "▼" in text  # precision moved down
        assert "0.850" in text and "0.900" in text

    def test_surfaces_false_keeps(self):
        r = result(confusion=ConfusionCounts(40, 7, 3, 50))
        text = format_pr_comment(r, check_gate(r, THRESHOLDS))
        assert "7 false keeps" in text


class TestLoadBaseline:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_baseline(tmp_path / "nope.json") is None

    def test_malformed_file_returns_none(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        assert load_baseline(p) is None

    def test_round_trips_a_saved_result(self, tmp_path):
        p = tmp_path / "baseline.json"
        p.write_text(json.dumps(result(precision=0.88, cost_per_100=0.74).as_dict()))
        loaded = load_baseline(p)
        assert loaded is not None
        assert loaded.keep_precision == 0.88
        assert loaded.cost_per_100_usd == 0.74
