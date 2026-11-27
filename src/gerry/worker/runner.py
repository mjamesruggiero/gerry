"""Job execution: store frames, run the pipeline, persist results.

v1 runs jobs in a background thread rather than a separate worker process.
That is a deliberate scope choice: a real queue (Redis/SQS) is the right
answer at scale, but it adds infrastructure this project does not yet need,
and the job boundary here is already a single function call -- so swapping
in a queue later means changing `enqueue`, not the pipeline.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import boto3

from gerry.settings import Settings
from gerry.store import repository as repo
from gerry.store.db import session_scope
from gerry.store.objects import S3Store
from gerry.store.schema import ShootStatus
from gerry.worker.pipeline import process_shoot

logger = logging.getLogger(__name__)

_s3_client: Any = None


def s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        settings = Settings()
        _s3_client = boto3.client(
            "s3",
            region_name=settings.s3_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
    return _s3_client


def frame_url(key: str, ttl: int = 604800) -> str:
    """Signed, expiring URL. The bucket stays private."""
    settings = Settings()
    try:
        return str(
            s3_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket, "Key": key},
                ExpiresIn=ttl,
            )
        )
    except Exception as exc:  # pragma: no cover - network/credentials
        logger.warning("could not sign %s: %s", key, exc)
        return ""


def enqueue(
    shoot_id: str, frames: dict[str, bytes], settings: Settings, cfg: dict[str, Any]
) -> None:
    """Start processing in the background so the upload request returns fast."""
    thread = threading.Thread(target=_run, args=(shoot_id, frames, settings, cfg), daemon=True)
    thread.start()


def _build_scorer(cfg: dict[str, Any], settings: Settings) -> Any:
    from anthropic import Anthropic

    from gerry.models.claude import ClaudeScorer
    from gerry.models.stub import StubScorer

    scoring = cfg.get("scoring", {})
    if not settings.anthropic_api_key:
        logger.warning("no ANTHROPIC_API_KEY; falling back to the stub scorer")
        return StubScorer()
    return ClaudeScorer(
        client=Anthropic(api_key=settings.anthropic_api_key),
        model=scoring.get("model", "claude-sonnet-4-5"),
        prompt_version_name=scoring.get("prompt_version", "cull_v4"),
    )


def _run(shoot_id: str, frames: dict[str, bytes], settings: Settings, cfg: dict[str, Any]) -> None:
    """Upload to S3, run the pipeline, persist scores and the cost ledger."""
    scoring = cfg.get("scoring", {})
    prefilter = cfg.get("prefilter", {})
    store = S3Store(client=s3_client(), bucket=settings.s3_bucket)

    try:
        with session_scope() as session:
            shoot = repo.get_shoot(session, shoot_id)
            if shoot is None:
                logger.error("shoot %s vanished before processing", shoot_id)
                return
            keys = {f.filename: f.s3_key for f in shoot.frames}
            ids = {f.filename: f.id for f in shoot.frames}
            repo.set_status(session, shoot, ShootStatus.PREFILTERING)

        for filename, data in frames.items():
            if filename in keys:
                store.put(keys[filename], data)

        with session_scope() as session:
            shoot = repo.get_shoot(session, shoot_id)
            if shoot:
                repo.set_status(session, shoot, ShootStatus.SCORING)

        results = process_shoot(
            frames,
            _build_scorer(cfg, settings),
            keep_threshold=float(scoring.get("keep_threshold", 83)),
            phash_distance=int(prefilter.get("phash_distance", 8)),
            blur_threshold=float(prefilter.get("blur_threshold", 100.0)),
            clipped_fraction=float(prefilter.get("clipped_fraction", 0.25)),
        )

        with session_scope() as session:
            shoot = repo.get_shoot(session, shoot_id)
            if shoot is None:
                return
            by_name = {f.filename: f for f in shoot.frames}
            for r in results:
                frame = by_name.get(r.filename)
                if frame is None:
                    continue
                frame.phash = r.phash
                frame.blur_score = r.blur_score
                frame.auto_rejected = r.auto_rejected
                frame.duplicate_group = r.duplicate_group
                repo.record_score(
                    session,
                    frame,
                    verdict=r.verdict,
                    quality=r.quality,
                    reason=r.reason,
                    keywords=r.keywords,
                    alt_text=r.alt_text,
                    prompt_version=scoring.get("prompt_version", "cull_v4"),
                )
                if r.cost_usd:
                    repo.record_model_request(
                        session,
                        frame_id=ids.get(r.filename),
                        provider="anthropic",
                        model=scoring.get("model", "claude-sonnet-4-5"),
                        prompt_version=scoring.get("prompt_version", "cull_v4"),
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd=r.cost_usd,
                        latency_ms=r.latency_ms,
                        succeeded=r.verdict != "unscored",
                    )
            repo.set_status(session, shoot, ShootStatus.READY)
        logger.info("shoot %s ready", shoot_id)

    except Exception:
        logger.exception("processing failed for shoot %s", shoot_id)
        with session_scope() as session:
            shoot = repo.get_shoot(session, shoot_id)
            if shoot:
                repo.set_status(session, shoot, ShootStatus.FAILED)
