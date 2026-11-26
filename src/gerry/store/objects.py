"""S3 object storage: uploads and signed gallery links.

Thin I/O boundary. Key construction is pure and tested; everything that
touches the network is a small, obvious wrapper.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3.client import S3Client

logger = logging.getLogger(__name__)


def upload_key(prefix: str, shoot_id: str, filename: str) -> str:
    """Object key for an ingested frame. Pure.

    Grouping by shoot keeps listings cheap and makes lifecycle rules per-shoot
    straightforward.
    """
    if not shoot_id:
        raise ValueError("shoot_id is required")
    if not filename:
        raise ValueError("filename is required")
    return f"{prefix.rstrip('/')}/{shoot_id}/{filename}"


def gallery_key(prefix: str, gallery_slug: str, filename: str) -> str:
    """Object key for an approved, client-facing frame. Pure."""
    if not gallery_slug:
        raise ValueError("gallery_slug is required")
    if not filename:
        raise ValueError("filename is required")
    return f"{prefix.rstrip('/')}/{gallery_slug}/{filename}"


class ObjectStore(Protocol):
    """What the app needs from storage. Lets tests substitute a fake."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def signed_url(self, key: str, ttl_seconds: int) -> str: ...


@dataclass
class S3Store:
    """Real S3 implementation."""

    client: S3Client
    bucket: str

    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        logger.info("put s3://%s/%s (%d bytes)", self.bucket, key, len(data))
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def signed_url(self, key: str, ttl_seconds: int = 604800) -> str:
        """Time-limited URL. The bucket stays private; this is how clients see images."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )
