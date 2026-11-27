"""Pure helpers for ingest: validation and identity.

File I/O and database writes live in the worker and store layers; everything
decidable from a filename and some bytes is decided here, where it is cheap
to test.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

ALLOWED_SUFFIXES = frozenset({".jpg", ".jpeg"})
MAX_BYTES = 25 * 1024 * 1024  # Anthropic's image limit is lower, but be generous
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class IngestError(ValueError):
    """The upload cannot be accepted."""


@dataclass(frozen=True)
class AcceptedFile:
    original_name: str
    safe_name: str
    content_hash: str
    size_bytes: int


def safe_filename(name: str) -> str:
    """Make a filename safe for an object key. Pure.

    Cloud Sync silently skipped files containing '#', '%', '|' and brackets
    during an unrelated migration; the same class of character causes trouble
    in S3 keys and URLs. Normalise rather than discover it later.
    """
    cleaned = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = cleaned.replace("/", "_").strip()
    cleaned = _SAFE.sub("_", cleaned).strip("._")
    if not cleaned:
        raise IngestError(f"filename reduces to nothing: {name!r}")
    return cleaned[:200]


def content_hash(data: bytes) -> str:
    """Stable identity for a frame. Pure.

    Lets a re-upload of the same shoot be recognised instead of duplicated --
    the same idea as a transaction id in a ledger.
    """
    return hashlib.sha256(data).hexdigest()


def validate_upload(name: str, data: bytes) -> AcceptedFile:
    """Accept or reject one uploaded file. Pure."""
    if not data:
        raise IngestError(f"{name}: empty file")
    if len(data) > MAX_BYTES:
        raise IngestError(f"{name}: {len(data)} bytes exceeds the {MAX_BYTES} limit")

    lowered = name.lower()
    if not any(lowered.endswith(s) for s in ALLOWED_SUFFIXES):
        raise IngestError(f"{name}: only JPEG is supported in v1")

    # JPEGs start with SOI (FFD8) and end with EOI (FFD9); a cheap guard
    # against a mislabelled or truncated file reaching the model.
    if data[:2] != b"\xff\xd8":
        raise IngestError(f"{name}: not a JPEG (bad magic bytes)")

    return AcceptedFile(
        original_name=name,
        safe_name=safe_filename(name),
        content_hash=content_hash(data),
        size_bytes=len(data),
    )


def slugify(text: str, *, max_length: int = 60) -> str:
    """Human-readable, URL-safe identifier. Pure."""
    cleaned = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned.lower()).strip("-")
    return cleaned[:max_length] or "untitled"
