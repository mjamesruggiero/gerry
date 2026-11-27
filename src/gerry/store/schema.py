"""Database schema.

One row per frame, one row per model request. The scores table is the
product; the model_requests table is the cost/latency ledger that makes
"spend known to the cent" answerable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Verdict(StrEnum):
    KEEP = "keep"
    MAYBE = "maybe"
    REJECT = "reject"
    UNSCORED = "unscored"  # model failed; needs manual review


class ShootStatus(StrEnum):
    UPLOADING = "uploading"
    QUEUED = "queued"
    PREFILTERING = "prefiltering"
    SCORING = "scoring"
    READY = "ready"
    FAILED = "failed"


class Shoot(Base):
    __tablename__ = "shoots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default=ShootStatus.UPLOADING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    frames: Mapped[list[Frame]] = relationship(back_populates="shoot", cascade="all, delete-orphan")


class Frame(Base):
    __tablename__ = "frames"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    shoot_id: Mapped[str] = mapped_column(ForeignKey("shoots.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(512))
    s3_key: Mapped[str] = mapped_column(String(1024))

    # deterministic pre-filter output (no model cost)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duplicate_group: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_rejected: Mapped[bool] = mapped_column(default=False)

    # Model's 0-100 deliverability score. Stored on the frame (not the score
    # row) because the pipeline thresholds it to produce the verdict, and we
    # want to re-threshold historical shoots without re-scoring them.
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    shoot: Mapped[Shoot] = relationship(back_populates="frames")
    score: Mapped[Score | None] = relationship(
        back_populates="frame", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (Index("ix_frames_shoot_group", "shoot_id", "duplicate_group"),)


class Score(Base):
    """Model verdict for a frame, plus any human override."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    frame_id: Mapped[str] = mapped_column(ForeignKey("frames.id", ondelete="CASCADE"), unique=True)

    verdict: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    alt_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Human override -- the feedback loop that feeds the golden set.
    override_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    frame: Mapped[Frame] = relationship(back_populates="score")

    @property
    def final_verdict(self) -> str:
        """Human override wins when present."""
        return self.override_verdict or self.verdict


class ModelRequest(Base):
    """Cost/latency ledger: one row per model call.

    Separate from Score because a single frame may take several attempts,
    and failed attempts still cost money.
    """

    __tablename__ = "model_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    frame_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    succeeded: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_model_requests_created", "created_at"),)
