"""Tests for the pure key-construction logic."""

from __future__ import annotations

import pytest

from gerry.store.objects import gallery_key, upload_key


class TestUploadKey:
    def test_basic(self):
        assert upload_key("uploads/", "shoot-1", "DSC01.jpg") == "uploads/shoot-1/DSC01.jpg"

    def test_normalizes_trailing_slash(self):
        assert upload_key("uploads", "s", "a.jpg") == upload_key("uploads/", "s", "a.jpg")

    def test_requires_shoot_id(self):
        with pytest.raises(ValueError, match="shoot_id"):
            upload_key("uploads/", "", "a.jpg")

    def test_requires_filename(self):
        with pytest.raises(ValueError, match="filename"):
            upload_key("uploads/", "s", "")


class TestGalleryKey:
    def test_basic(self):
        assert gallery_key("galleries/", "abc123", "x.jpg") == "galleries/abc123/x.jpg"

    def test_requires_slug(self):
        with pytest.raises(ValueError, match="gallery_slug"):
            gallery_key("galleries/", "", "x.jpg")

    def test_keys_are_distinct_between_tiers(self):
        assert upload_key("uploads/", "s", "a.jpg") != gallery_key("galleries/", "s", "a.jpg")
