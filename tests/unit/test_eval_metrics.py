"""Tests for the eval metrics. These decide whether code can merge, so they
get adversarial treatment -- especially the degenerate cases."""

from __future__ import annotations

import pytest

from gerry.evals.metrics import (
    ConfusionCounts,
    agreement,
    confusion_for_keep,
    evaluate,
    percentile,
    precision,
    recall,
)


class TestConfusionForKeep:
    def test_perfect_agreement(self):
        pred = {"a": "keep", "b": "reject"}
        c = confusion_for_keep(pred, pred)
        assert (c.true_positive, c.false_positive, c.false_negative, c.true_negative) == (
            1,
            0,
            0,
            1,
        )

    def test_false_positive_is_the_costly_case(self):
        # predicted keep, actually reject -> a bad frame reaches the client
        c = confusion_for_keep({"a": "keep"}, {"a": "reject"})
        assert c.false_positive == 1
        assert c.true_positive == 0

    def test_maybe_is_not_keep_on_either_side(self):
        c = confusion_for_keep({"a": "maybe"}, {"a": "maybe"})
        assert c.true_negative == 1
        assert c.true_positive == 0

    def test_ignores_frames_missing_from_either_side(self):
        c = confusion_for_keep({"a": "keep", "b": "keep"}, {"a": "keep"})
        assert c.total == 1

    def test_empty_inputs(self):
        assert confusion_for_keep({}, {}).total == 0


class TestPrecisionRecall:
    def test_precision_basic(self):
        assert precision(ConfusionCounts(true_positive=3, false_positive=1)) == 0.75

    def test_recall_basic(self):
        assert recall(ConfusionCounts(true_positive=3, false_negative=1)) == 0.75

    def test_precision_is_one_when_nothing_predicted_keep(self):
        # Vacuous but correct: no keeps means no bad keeps.
        assert precision(ConfusionCounts(true_negative=10)) == 1.0

    def test_recall_catches_the_degenerate_case(self):
        # The model rejected everything: precision looks perfect...
        counts = ConfusionCounts(
            true_positive=0, false_positive=0, false_negative=10, true_negative=5
        )
        assert precision(counts) == 1.0
        # ...but recall exposes it. This is why the gate needs both.
        assert recall(counts) == 0.0

    def test_perfect_scores(self):
        counts = ConfusionCounts(true_positive=5, true_negative=5)
        assert precision(counts) == 1.0
        assert recall(counts) == 1.0


class TestAgreement:
    def test_all_match(self):
        pred = {"a": "keep", "b": "maybe", "c": "reject"}
        assert agreement(pred, pred) == 1.0

    def test_none_match(self):
        assert agreement({"a": "keep"}, {"a": "reject"}) == 0.0

    def test_partial(self):
        pred = {"a": "keep", "b": "keep"}
        lab = {"a": "keep", "b": "reject"}
        assert agreement(pred, lab) == 0.5

    def test_empty_is_zero_not_one(self):
        # No overlap means we learned nothing; 0.0 avoids a vacuous pass.
        assert agreement({}, {}) == 0.0


class TestPercentile:
    def test_empty(self):
        assert percentile([], 95) == 0

    def test_single_value(self):
        assert percentile([42], 95) == 42

    def test_p95_of_hundred(self):
        assert percentile(list(range(1, 101)), 95) == 95

    def test_p50_median_ish(self):
        assert percentile([10, 20, 30, 40], 50) == 20

    def test_max_at_100(self):
        assert percentile([1, 5, 9], 100) == 9

    def test_unsorted_input(self):
        assert percentile([100, 1, 50], 100) == 100

    def test_invalid_pct(self):
        with pytest.raises(ValueError, match="pct"):
            percentile([1], 0)


class TestEvaluate:
    def test_aggregates_everything(self):
        pred = {"a": "keep", "b": "keep", "c": "reject", "d": "maybe"}
        lab = {"a": "keep", "b": "reject", "c": "reject", "d": "maybe"}
        r = evaluate(pred, lab, costs_usd=[0.01] * 4, latencies_ms=[100, 200, 300, 400])
        assert r.n == 4
        assert r.keep_precision == 0.5  # 1 of 2 keeps was right
        assert r.keep_recall == 1.0  # found the only real keep
        assert r.agreement == 0.75  # 3 of 4 exact matches
        assert r.cost_total_usd == pytest.approx(0.04)
        assert r.cost_per_100_usd == pytest.approx(1.0)
        assert r.p95_latency_ms == 400

    def test_cost_per_100_scales(self):
        pred = lab = {str(i): "keep" for i in range(10)}
        r = evaluate(pred, lab, costs_usd=[0.0074] * 10)
        assert r.cost_per_100_usd == pytest.approx(0.74, abs=1e-6)

    def test_empty_is_safe(self):
        r = evaluate({}, {})
        assert r.n == 0
        assert r.cost_per_100_usd == 0.0

    def test_as_dict_is_json_friendly(self):
        r = evaluate({"a": "keep"}, {"a": "keep"}, costs_usd=[0.01], latencies_ms=[5])
        d = r.as_dict()
        assert set(d) == {
            "n",
            "keep_precision",
            "keep_recall",
            "agreement",
            "auc",
            "cost_total_usd",
            "cost_per_100_usd",
            "p95_latency_ms",
        }


class TestRocAuc:
    """AUC is the primary gate metric because it's threshold-independent."""

    def test_perfect_ranking(self):
        from gerry.evals.metrics import roc_auc

        scores = {"a": 90.0, "b": 80.0, "c": 20.0, "d": 10.0}
        labels = {"a": "keep", "b": "keep", "c": "reject", "d": "reject"}
        assert roc_auc(scores, labels) == 1.0

    def test_inverted_ranking(self):
        from gerry.evals.metrics import roc_auc

        scores = {"a": 10.0, "b": 20.0, "c": 80.0, "d": 90.0}
        labels = {"a": "keep", "b": "keep", "c": "reject", "d": "reject"}
        assert roc_auc(scores, labels) == 0.0

    def test_all_tied_is_chance(self):
        from gerry.evals.metrics import roc_auc

        scores = {"a": 50.0, "b": 50.0, "c": 50.0, "d": 50.0}
        labels = {"a": "keep", "b": "keep", "c": "reject", "d": "reject"}
        assert roc_auc(scores, labels) == 0.5

    def test_is_invariant_to_monotonic_rescaling(self):
        # The point of AUC: shifting/scaling scores must not change it.
        from gerry.evals.metrics import roc_auc

        labels = {"a": "keep", "b": "keep", "c": "reject", "d": "reject"}
        base = {"a": 90.0, "b": 70.0, "c": 40.0, "d": 10.0}
        shifted = {k: v / 2 + 100 for k, v in base.items()}
        assert roc_auc(base, labels) == roc_auc(shifted, labels)

    def test_no_positives_returns_chance(self):
        from gerry.evals.metrics import roc_auc

        assert roc_auc({"a": 5.0}, {"a": "reject"}) == 0.5

    def test_maybe_counts_as_not_keep(self):
        from gerry.evals.metrics import roc_auc

        scores = {"a": 90.0, "b": 10.0}
        assert roc_auc(scores, {"a": "keep", "b": "maybe"}) == 1.0

    def test_evaluate_includes_auc_when_scores_given(self):
        pred = {"a": "keep", "b": "reject"}
        lab = {"a": "keep", "b": "reject"}
        r = evaluate(pred, lab, scores={"a": 90.0, "b": 10.0})
        assert r.auc == 1.0

    def test_evaluate_defaults_to_chance_without_scores(self):
        r = evaluate({"a": "keep"}, {"a": "keep"})
        assert r.auc == 0.5
