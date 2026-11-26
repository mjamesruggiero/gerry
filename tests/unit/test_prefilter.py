"""Tests for the pure pre-filter logic."""

from __future__ import annotations

import numpy as np
import pytest

from gerry.core.prefilter import (
    assess_quality,
    exposure_fractions,
    group_near_duplicates,
    hamming_distance,
    variance_of_laplacian,
)

rng = np.random.default_rng(1234)


def sharp_image(size: int = 64) -> np.ndarray:
    """High-frequency checkerboard -> large Laplacian variance."""
    img = np.zeros((size, size), dtype=np.uint8)
    img[::2, ::2] = 255
    img[1::2, 1::2] = 255
    return img


def flat_image(size: int = 64, value: int = 128) -> np.ndarray:
    return np.full((size, size), value, dtype=np.uint8)


class TestVarianceOfLaplacian:
    def test_flat_image_has_zero_variance(self):
        assert variance_of_laplacian(flat_image()) == pytest.approx(0.0)

    def test_sharp_image_scores_higher_than_flat(self):
        assert variance_of_laplacian(sharp_image()) > variance_of_laplacian(flat_image())

    def test_rejects_non_2d(self):
        with pytest.raises(ValueError, match="2-D"):
            variance_of_laplacian(np.zeros((8, 8, 3), dtype=np.uint8))

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            variance_of_laplacian(np.zeros((0, 0), dtype=np.uint8))

    def test_tiny_image_returns_zero(self):
        # smaller than the 3x3 kernel -> no valid positions
        assert variance_of_laplacian(np.zeros((2, 2), dtype=np.uint8)) == 0.0


class TestExposure:
    def test_mid_grey_has_no_clipping(self):
        shadows, highlights = exposure_fractions(flat_image(value=128))
        assert shadows == 0.0
        assert highlights == 0.0

    def test_all_black_is_fully_clipped_shadows(self):
        shadows, highlights = exposure_fractions(flat_image(value=0))
        assert shadows == 1.0
        assert highlights == 0.0

    def test_all_white_is_fully_clipped_highlights(self):
        shadows, highlights = exposure_fractions(flat_image(value=255))
        assert shadows == 0.0
        assert highlights == 1.0

    def test_half_and_half(self):
        img = np.vstack([flat_image(32, 0), flat_image(32, 255)])
        shadows, highlights = exposure_fractions(img)
        assert shadows == pytest.approx(0.5)
        assert highlights == pytest.approx(0.5)


class TestAssessQuality:
    def test_flat_image_is_blurry(self):
        assert assess_quality(flat_image()).is_blurry

    def test_sharp_image_is_not_blurry(self):
        assert not assess_quality(sharp_image()).is_blurry

    def test_blown_out_frame_is_poorly_exposed(self):
        assert assess_quality(flat_image(value=255)).is_poorly_exposed

    def test_auto_reject_requires_both_failures(self):
        # white frame: poorly exposed AND flat (blurry) -> auto reject
        assert assess_quality(flat_image(value=255)).auto_reject
        # sharp, well exposed -> keep for the model
        assert not assess_quality(sharp_image()).auto_reject


class TestHammingDistance:
    def test_identical_hashes(self):
        assert hamming_distance("ffff", "ffff") == 0

    def test_single_bit(self):
        assert hamming_distance("0000", "0001") == 1

    def test_all_bits(self):
        assert hamming_distance("0000", "ffff") == 16

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="length mismatch"):
            hamming_distance("ff", "ffff")


class TestGroupNearDuplicates:
    def test_empty_input(self):
        assert group_near_duplicates({}) == []

    def test_single_frame_is_its_own_group(self):
        groups = group_near_duplicates({"a.jpg": "0000"})
        assert len(groups) == 1
        assert groups[0].members == ["a.jpg"]

    def test_identical_frames_group_together(self):
        groups = group_near_duplicates({"a.jpg": "ffff", "b.jpg": "ffff"})
        assert len(groups) == 1
        assert groups[0].members == ["a.jpg", "b.jpg"]

    def test_distant_frames_stay_separate(self):
        groups = group_near_duplicates({"a.jpg": "0000", "b.jpg": "ffff"}, max_distance=8)
        assert len(groups) == 2

    def test_transitive_chaining(self):
        # a~b and b~c (each 4 bits apart) but a~c is 8 apart:
        # single-linkage should still merge all three.
        hashes = {"a.jpg": "0000", "b.jpg": "000f", "c.jpg": "00ff"}
        groups = group_near_duplicates(hashes, max_distance=4)
        assert len(groups) == 1
        assert groups[0].members == ["a.jpg", "b.jpg", "c.jpg"]

    def test_is_deterministic(self):
        hashes = {"c.jpg": "ffff", "a.jpg": "ffff", "b.jpg": "0000"}
        first = group_near_duplicates(hashes)
        second = group_near_duplicates(hashes)
        assert [g.members for g in first] == [g.members for g in second]
