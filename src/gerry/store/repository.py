"""Database reads and writes for shoots, frames, scores, and the cost ledger.

All SQL lives here. Callers work with ORM objects; the thin wrapper keeps
query construction out of the route handlers.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from gerry.store.schema import Frame, ModelRequest, Score, Shoot, ShootStatus

logger = logging.getLogger(__name__)


def create_shoot(session: Session, name: str) -> Shoot:
    shoot = Shoot(id=str(uuid.uuid4()), name=name, status=ShootStatus.UPLOADING)
    session.add(shoot)
    session.flush()
    return shoot


def add_frame(session: Session, shoot: Shoot, filename: str, s3_key: str) -> Frame:
    frame = Frame(id=str(uuid.uuid4()), shoot_id=shoot.id, filename=filename, s3_key=s3_key)
    session.add(frame)
    session.flush()
    return frame


def get_shoot(session: Session, shoot_id: str) -> Shoot | None:
    return session.scalar(
        select(Shoot)
        .where(Shoot.id == shoot_id)
        .options(selectinload(Shoot.frames).selectinload(Frame.score))
    )


def list_shoots(session: Session, limit: int = 50) -> list[Shoot]:
    return list(session.scalars(select(Shoot).order_by(Shoot.created_at.desc()).limit(limit)))


def set_status(session: Session, shoot: Shoot, status: str) -> None:
    shoot.status = status
    session.flush()


def record_score(
    session: Session,
    frame: Frame,
    *,
    verdict: str,
    quality: float | None,
    reason: str,
    keywords: list[str] | None,
    alt_text: str,
    prompt_version: str,
) -> Score:
    score = Score(
        frame_id=frame.id,
        verdict=verdict,
        reason=reason,
        keywords=",".join(keywords or []),
        alt_text=alt_text,
        prompt_version=prompt_version,
    )
    frame.quality = quality
    session.add(score)
    session.flush()
    return score


def override_verdict(session: Session, frame_id: str, verdict: str) -> Score | None:
    """Record a human override.

    These are the feedback signal: every override is a candidate addition to
    the golden set, which is how the eval set grows from real use.
    """
    from datetime import UTC, datetime

    score = session.scalar(select(Score).where(Score.frame_id == frame_id))
    if score is None:
        return None
    score.override_verdict = verdict
    score.overridden_at = datetime.now(UTC)
    session.flush()
    logger.info("override: frame=%s %s -> %s", frame_id, score.verdict, verdict)
    return score


def record_model_request(
    session: Session,
    *,
    frame_id: str | None,
    provider: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    latency_ms: int,
    succeeded: bool = True,
    error: str | None = None,
) -> None:
    """Append to the cost ledger. Failed calls are recorded too -- they cost money."""
    session.add(
        ModelRequest(
            frame_id=frame_id,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            succeeded=succeeded,
            error=error,
        )
    )


def total_spend(session: Session) -> float:
    """Every dollar ever spent on model calls."""
    return float(session.scalar(select(func.coalesce(func.sum(ModelRequest.cost_usd), 0.0))) or 0.0)


def spend_summary(session: Session) -> dict[str, float | int]:
    """Figures for the cost dashboard."""
    row = session.execute(
        select(
            func.count(ModelRequest.id),
            func.coalesce(func.sum(ModelRequest.cost_usd), 0.0),
            func.coalesce(func.sum(ModelRequest.input_tokens), 0),
            func.coalesce(func.sum(ModelRequest.output_tokens), 0),
            func.coalesce(func.avg(ModelRequest.latency_ms), 0.0),
        )
    ).one()
    failed = session.scalar(
        select(func.count(ModelRequest.id)).where(ModelRequest.succeeded.is_(False))
    )
    calls = int(row[0])
    return {
        "calls": calls,
        "failed_calls": int(failed or 0),
        "total_usd": float(row[1]),
        "input_tokens": int(row[2]),
        "output_tokens": int(row[3]),
        "avg_latency_ms": float(row[4]),
        "cost_per_100": (float(row[1]) / calls * 100) if calls else 0.0,
    }
