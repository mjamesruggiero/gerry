"""Tests for best-of-group selection (ADR 0001)."""

from __future__ import annotations

from gerry.core.selection import (
    ScoredFrame,
    apply_group_selection,
    attach_groups,
    rank_within_group,
    resolve_group,
)


def f(name: str, verdict: str, blur: float = 0.0, group: int | None = 1) -> ScoredFrame:
    return ScoredFrame(filename=name, verdict=verdict, blur_score=blur, group_id=group)


class TestRankWithinGroup:
    def test_keep_outranks_maybe_outranks_reject(self):
        ordered = rank_within_group([f("c", "reject"), f("a", "keep"), f("b", "maybe")])
        assert [x.filename for x in ordered] == ["a", "b", "c"]

    def test_sharpness_breaks_verdict_ties(self):
        ordered = rank_within_group([f("dull", "keep", 10.0), f("sharp", "keep", 900.0)])
        assert ordered[0].filename == "sharp"

    def test_filename_breaks_remaining_ties(self):
        ordered = rank_within_group([f("b", "keep", 5.0), f("a", "keep", 5.0)])
        assert [x.filename for x in ordered] == ["a", "b"]

    def test_unscored_ranks_last(self):
        ordered = rank_within_group([f("u", "unscored"), f("r", "reject")])
        assert ordered[-1].filename == "u"

    def test_empty(self):
        assert rank_within_group([]) == []


class TestResolveGroup:
    def test_single_frame_group_is_untouched(self):
        d = resolve_group([f("only", "keep")])
        assert d.winner == "only"
        assert d.verdicts == {"only": "keep"}

    def test_burst_keeps_one_and_demotes_the_rest(self):
        # The BMX case: model says keep to everything in the burst.
        frames = [f("a", "keep", 100.0), f("b", "keep", 500.0), f("c", "keep", 50.0)]
        d = resolve_group(frames)
        assert d.winner == "b"  # sharpest
        assert d.verdicts == {"b": "keep", "a": "maybe", "c": "maybe"}

    def test_only_one_keep_survives(self):
        frames = [f(n, "keep", float(i)) for i, n in enumerate("abcde")]
        verdicts = resolve_group(frames).verdicts
        assert sum(1 for v in verdicts.values() if v == "keep") == 1

    def test_rejects_stay_rejected(self):
        # Redundancy doesn't make a blurry frame worse.
        d = resolve_group([f("good", "keep", 500.0), f("blurry", "reject", 5.0)])
        assert d.verdicts["blurry"] == "reject"

    def test_group_of_all_rejects_promotes_nothing(self):
        d = resolve_group([f("a", "reject"), f("b", "reject")])
        assert set(d.verdicts.values()) == {"reject"}

    def test_demote_target_is_configurable(self):
        d = resolve_group([f("a", "keep", 9.0), f("b", "keep", 1.0)], demote_to="reject")
        assert d.verdicts["b"] == "reject"

    def test_empty_group(self):
        d = resolve_group([])
        assert d.winner is None and d.verdicts == {}


class TestApplyGroupSelection:
    def test_singletons_pass_through(self):
        frames = [f("a", "keep", group=None), f("b", "reject", group=None)]
        assert apply_group_selection(frames) == {"a": "keep", "b": "reject"}

    def test_multiple_groups_resolved_independently(self):
        frames = [
            f("g1a", "keep", 100.0, group=1),
            f("g1b", "keep", 200.0, group=1),
            f("g2a", "keep", 300.0, group=2),
            f("g2b", "keep", 50.0, group=2),
        ]
        out = apply_group_selection(frames)
        assert out == {"g1b": "keep", "g1a": "maybe", "g2a": "keep", "g2b": "maybe"}

    def test_mixed_singletons_and_groups(self):
        frames = [
            f("solo", "keep", group=None),
            f("b1", "keep", 10.0, group=7),
            f("b2", "keep", 20.0, group=7),
        ]
        out = apply_group_selection(frames)
        assert out["solo"] == "keep"
        assert sum(1 for k, v in out.items() if k.startswith("b") and v == "keep") == 1

    def test_is_deterministic(self):
        frames = [f("a", "keep", 5.0), f("b", "keep", 5.0), f("c", "keep", 5.0)]
        assert apply_group_selection(frames) == apply_group_selection(frames)

    def test_empty(self):
        assert apply_group_selection([]) == {}


class TestAttachGroups:
    def test_builds_scored_frames(self):
        frames = attach_groups(
            {"a.jpg": "keep", "b.jpg": "reject"},
            {"a.jpg": 1, "b.jpg": 1},
            {"a.jpg": 500.0},
        )
        assert len(frames) == 2
        assert frames[0].filename == "a.jpg"
        assert frames[0].blur_score == 500.0
        assert frames[1].blur_score == 0.0  # missing blur defaults

    def test_ungrouped_frames_get_none(self):
        frames = attach_groups({"x.jpg": "keep"}, {})
        assert frames[0].group_id is None

    def test_round_trip_through_selection(self):
        verdicts = {"a.jpg": "keep", "b.jpg": "keep"}
        groups = {"a.jpg": 1, "b.jpg": 1}
        blur = {"a.jpg": 10.0, "b.jpg": 900.0}
        out = apply_group_selection(attach_groups(verdicts, groups, blur))
        assert out == {"b.jpg": "keep", "a.jpg": "maybe"}
