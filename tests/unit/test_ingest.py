"""Tests for pure ingest validation."""

from __future__ import annotations

import pytest

from gerry.core.ingest import (
    IngestError,
    content_hash,
    safe_filename,
    slugify,
    validate_upload,
)

JPEG = b"\xff\xd8" + b"padding" * 100 + b"\xff\xd9"


class TestSafeFilename:
    def test_plain_name_untouched(self):
        assert safe_filename("DSC01234.jpg") == "DSC01234.jpg"

    @pytest.mark.parametrize("ch", ["#", "%", "|", "[", "]", " ", "*"])
    def test_strips_problem_characters(self, ch):
        out = safe_filename(f"photo{ch}1.jpg")
        assert ch not in out

    def test_strips_path_separators(self):
        assert "/" not in safe_filename("../../etc/passwd.jpg")

    def test_collapses_runs_of_unsafe_chars(self):
        assert safe_filename("a###b.jpg") == "a_b.jpg"

    def test_transliterates_accents(self):
        assert safe_filename("café.jpg") == "cafe.jpg"

    def test_truncates_very_long_names(self):
        assert len(safe_filename("x" * 500 + ".jpg")) <= 200

    def test_rejects_name_that_reduces_to_nothing(self):
        with pytest.raises(IngestError, match="nothing"):
            safe_filename("###")


class TestContentHash:
    def test_is_deterministic(self):
        assert content_hash(b"abc") == content_hash(b"abc")

    def test_differs_for_different_bytes(self):
        assert content_hash(b"abc") != content_hash(b"abd")

    def test_is_hex_sha256(self):
        h = content_hash(b"abc")
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


class TestValidateUpload:
    def test_accepts_a_jpeg(self):
        a = validate_upload("DSC1.jpg", JPEG)
        assert a.original_name == "DSC1.jpg"
        assert a.size_bytes == len(JPEG)
        assert len(a.content_hash) == 64

    def test_accepts_jpeg_extension_variants(self):
        for name in ("a.jpg", "a.JPG", "a.jpeg", "a.JPEG"):
            assert validate_upload(name, JPEG).size_bytes > 0

    def test_rejects_empty(self):
        with pytest.raises(IngestError, match="empty"):
            validate_upload("a.jpg", b"")

    def test_rejects_non_jpeg_extension(self):
        with pytest.raises(IngestError, match="only JPEG"):
            validate_upload("a.png", JPEG)

    def test_rejects_wrong_magic_bytes(self):
        # a PNG renamed to .jpg must not reach the model
        with pytest.raises(IngestError, match="not a JPEG"):
            validate_upload("a.jpg", b"\x89PNG\r\n\x1a\n" + b"x" * 50)

    def test_rejects_oversized(self):
        with pytest.raises(IngestError, match="exceeds"):
            validate_upload("a.jpg", b"\xff\xd8" + b"x" * (26 * 1024 * 1024))

    def test_normalises_the_stored_name(self):
        assert validate_upload("my photo#2.jpg", JPEG).safe_name == "my_photo_2.jpg"

    def test_same_bytes_same_hash_across_names(self):
        assert (
            validate_upload("a.jpg", JPEG).content_hash
            == validate_upload("b.jpg", JPEG).content_hash
        )


class TestSlugify:
    def test_basic(self):
        assert slugify("Dunstan Head Shots") == "dunstan-head-shots"

    def test_collapses_punctuation(self):
        assert slugify("Les Misérables -- Act I!") == "les-miserables-act-i"

    def test_empty_falls_back(self):
        assert slugify("!!!") == "untitled"

    def test_truncates(self):
        assert len(slugify("word " * 100)) <= 60

    def test_is_url_safe(self):
        s = slugify("Café / Bar #3")
        assert all(c.isalnum() or c == "-" for c in s)
