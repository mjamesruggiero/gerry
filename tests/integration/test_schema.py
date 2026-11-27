"""Schema round-trips against a real Postgres."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gerry.store.schema import Frame, ModelRequest, Score, Shoot, ShootStatus, Verdict

pytestmark = pytest.mark.integration


def make_shoot(session: Session, name: str = "test shoot") -> Shoot:
    shoot = Shoot(id=str(uuid.uuid4()), name=name, status=ShootStatus.QUEUED)
    session.add(shoot)
    session.flush()
    return shoot


def make_frame(session: Session, shoot: Shoot, filename: str = "DSC001.jpg") -> Frame:
    frame = Frame(
        id=str(uuid.uuid4()),
        shoot_id=shoot.id,
        filename=filename,
        s3_key=f"uploads/{shoot.id}/{filename}",
    )
    session.add(frame)
    session.flush()
    return frame


class TestShoot:
    def test_round_trip(self, session: Session):
        shoot = make_shoot(session, "dunstan headshots")
        found = session.scalar(select(Shoot).where(Shoot.id == shoot.id))
        assert found is not None
        assert found.name == "dunstan headshots"
        assert found.status == ShootStatus.QUEUED
        assert found.created_at is not None

    def test_frames_relationship(self, session: Session):
        shoot = make_shoot(session)
        make_frame(session, shoot, "a.jpg")
        make_frame(session, shoot, "b.jpg")
        session.refresh(shoot)
        assert {f.filename for f in shoot.frames} == {"a.jpg", "b.jpg"}


class TestFrame:
    def test_prefilter_fields_default_empty(self, session: Session):
        frame = make_frame(session, make_shoot(session))
        assert frame.phash is None
        assert frame.duplicate_group is None
        assert frame.auto_rejected is False

    def test_stores_prefilter_output(self, session: Session):
        frame = make_frame(session, make_shoot(session))
        frame.phash = "ff00ff00ff00ff00"
        frame.duplicate_group = 3
        frame.blur_score = 42.5
        frame.auto_rejected = True
        session.flush()
        session.refresh(frame)
        assert frame.duplicate_group == 3
        assert frame.blur_score == pytest.approx(42.5)
        assert frame.auto_rejected is True

    def test_cascade_delete_removes_frames(self, session: Session):
        shoot = make_shoot(session)
        make_frame(session, shoot)
        session.delete(shoot)
        session.flush()
        assert session.scalars(select(Frame).where(Frame.shoot_id == shoot.id)).all() == []


class TestScore:
    def test_model_verdict_round_trip(self, session: Session):
        frame = make_frame(session, make_shoot(session))
        session.add(
            Score(
                frame_id=frame.id,
                verdict=Verdict.KEEP,
                reason="sharp, eyes open",
                prompt_version="cull_v1",
            )
        )
        session.flush()
        score = session.scalar(select(Score).where(Score.frame_id == frame.id))
        assert score is not None
        assert score.verdict == Verdict.KEEP
        assert score.final_verdict == Verdict.KEEP

    def test_human_override_wins(self, session: Session):
        frame = make_frame(session, make_shoot(session))
        score = Score(frame_id=frame.id, verdict=Verdict.REJECT, prompt_version="cull_v1")
        session.add(score)
        session.flush()
        assert score.final_verdict == Verdict.REJECT

        score.override_verdict = Verdict.KEEP
        session.flush()
        # the override is the feedback signal that feeds the golden set
        assert score.final_verdict == Verdict.KEEP

    def test_one_score_per_frame(self, session: Session):
        frame = make_frame(session, make_shoot(session))
        session.add(Score(frame_id=frame.id, verdict=Verdict.KEEP, prompt_version="v1"))
        session.flush()

        # Use a savepoint so the expected failure doesn't poison the outer
        # transaction the fixture rolls back.
        with pytest.raises(IntegrityError), session.begin_nested():
            session.add(Score(frame_id=frame.id, verdict=Verdict.MAYBE, prompt_version="v1"))
            session.flush()


class TestModelRequest:
    def test_ledger_row_round_trip(self, session: Session):
        req = ModelRequest(
            frame_id=None,
            provider="anthropic",
            model="claude-sonnet-4-5",
            prompt_version="cull_v1",
            input_tokens=1500,
            output_tokens=120,
            cost_usd=0.0057,
            latency_ms=2300,
        )
        session.add(req)
        session.flush()
        found = session.scalar(select(ModelRequest).where(ModelRequest.id == req.id))
        assert found is not None
        assert found.cost_usd == pytest.approx(0.0057)
        assert found.succeeded is True

    def test_failed_calls_are_recorded(self, session: Session):
        """Failed attempts still cost money, so they must appear in the ledger."""
        req = ModelRequest(
            provider="anthropic",
            model="claude-sonnet-4-5",
            prompt_version="cull_v1",
            input_tokens=1500,
            output_tokens=0,
            cost_usd=0.0045,
            latency_ms=900,
            succeeded=False,
            error="schema validation failed",
        )
        session.add(req)
        session.flush()
        assert req.succeeded is False
        assert req.cost_usd > 0

    def test_total_spend_is_summable(self, session: Session):
        for cents in (0.001, 0.002, 0.003):
            session.add(
                ModelRequest(provider="anthropic", model="m", prompt_version="v1", cost_usd=cents)
            )
        session.flush()
        rows = session.scalars(select(ModelRequest)).all()
        assert sum(r.cost_usd for r in rows) == pytest.approx(0.006)
