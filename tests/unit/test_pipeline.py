"""Tests for the shoot-processing pipeline (model stubbed, no network)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from gerry.models.base import FrameScore, ScoringError, Usage
from gerry.worker.pipeline import process_shoot


def jpeg(
    colour: tuple[int, int, int] = (120, 90, 60), size: int = 128, noise: bool = True
) -> bytes:
    """A real JPEG; `noise` makes it sharp enough to pass the blur check."""
    img = Image.new("RGB", (size, size), colour)
    if noise:
        px = img.load()
        for x in range(0, size, 2):
            for y in range(0, size, 2):
                px[x, y] = (255, 255, 255)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


class FakeScorer:
    """Returns a fixed quality score; records what it was asked to score."""

    def __init__(self, quality: float = 90.0, fail: bool = False):
        self.quality = quality
        self.fail = fail
        self.seen: list[int] = []

    model_name = "fake"
    prompt_version = "cull_v4"

    def score(self, image_bytes: bytes, media_type: str = "image/jpeg") -> FrameScore:
        self.seen.append(len(image_bytes))
        if self.fail:
            raise ScoringError("simulated failure")
        return FrameScore(
            verdict="keep",
            reason="fake",
            quality=self.quality,
            usage=Usage(input_tokens=2000, output_tokens=100, cost_usd=0.0075, latency_ms=3000),
        )


class TestThresholdApplication:
    def test_score_above_threshold_is_kept(self):
        out = process_shoot({"a.jpg": jpeg()}, FakeScorer(quality=90), keep_threshold=83)
        assert out[0].verdict == "keep"
        assert out[0].quality == 90

    def test_score_below_threshold_is_rejected(self):
        out = process_shoot({"a.jpg": jpeg()}, FakeScorer(quality=50), keep_threshold=83)
        assert out[0].verdict == "reject"

    def test_boundary_is_inclusive(self):
        out = process_shoot({"a.jpg": jpeg()}, FakeScorer(quality=83), keep_threshold=83)
        assert out[0].verdict == "keep"

    def test_our_threshold_overrides_the_model_verdict(self):
        # FakeScorer always says "keep"; a low score must still reject (ADR 0003)
        out = process_shoot({"a.jpg": jpeg()}, FakeScorer(quality=10), keep_threshold=83)
        assert out[0].verdict == "reject"


class TestPrefilterSavesMoney:
    def test_blown_out_blank_frame_is_auto_rejected_without_scoring(self):
        # auto_reject needs BOTH failures: flat AND badly exposed. A pure white
        # frame is both. (A flat mid-grey frame is only blurry, and a blurry
        # well-exposed frame may be deliberate motion blur -- so it still gets
        # scored.)
        scorer = FakeScorer()
        out = process_shoot({"white.jpg": jpeg(colour=(255, 255, 255), noise=False)}, scorer)
        assert out[0].auto_rejected
        assert out[0].verdict == "reject"
        assert scorer.seen == []  # the model was never called -> no cost
        assert out[0].cost_usd == 0.0

    def test_flat_but_well_exposed_frame_still_gets_scored(self):
        # Deliberate motion blur must not be auto-rejected on sharpness alone.
        scorer = FakeScorer()
        out = process_shoot({"flat.jpg": jpeg(noise=False)}, scorer)
        assert not out[0].auto_rejected
        assert len(scorer.seen) == 1

    def test_good_frames_do_reach_the_model(self):
        scorer = FakeScorer()
        process_shoot({"a.jpg": jpeg()}, scorer, blur_threshold=0.0)
        assert len(scorer.seen) == 1


class TestFailureHandling:
    def test_scoring_failure_becomes_unscored_not_a_verdict(self):
        out = process_shoot({"a.jpg": jpeg()}, FakeScorer(fail=True), blur_threshold=0.0)
        assert out[0].verdict == "unscored"
        assert "scoring failed" in out[0].reason

    def test_undecodable_file_is_handled(self):
        out = process_shoot({"bad.jpg": b"\xff\xd8not really a jpeg"}, FakeScorer())
        assert out[0].verdict == "reject"
        assert "undecodable" in out[0].reason

    def test_one_bad_frame_does_not_abort_the_shoot(self):
        out = process_shoot(
            {"bad.jpg": b"\xff\xd8junk", "good.jpg": jpeg()},
            FakeScorer(),
            blur_threshold=0.0,
        )
        assert len(out) == 2
        assert {r.verdict for r in out} == {"reject", "keep"}


class TestGroupingAndAccounting:
    def test_identical_frames_share_a_duplicate_group(self):
        data = jpeg()
        out = process_shoot({"a.jpg": data, "b.jpg": data}, FakeScorer(), blur_threshold=0.0)
        groups = {r.duplicate_group for r in out}
        assert groups != {None}
        assert len({r.duplicate_group for r in out}) == 1

    def test_grouping_does_not_change_verdicts(self):
        # ADR 0002: grouping is presentation metadata, not a verdict
        data = jpeg()
        out = process_shoot(
            {"a.jpg": data, "b.jpg": data},
            FakeScorer(quality=90),
            blur_threshold=0.0,
            keep_threshold=83,
        )
        assert all(r.verdict == "keep" for r in out)

    def test_cost_is_recorded_per_frame(self):
        out = process_shoot(
            {"a.jpg": jpeg(), "b.jpg": jpeg((10, 20, 30))}, FakeScorer(), blur_threshold=0.0
        )
        assert sum(r.cost_usd for r in out) == pytest.approx(0.015)

    def test_results_are_sorted_and_complete(self):
        out = process_shoot(
            {"c.jpg": jpeg(), "a.jpg": jpeg(), "b.jpg": jpeg()}, FakeScorer(), blur_threshold=0.0
        )
        assert [r.filename for r in out] == ["a.jpg", "b.jpg", "c.jpg"]

    def test_empty_shoot(self):
        assert process_shoot({}, FakeScorer()) == []
