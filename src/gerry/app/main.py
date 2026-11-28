"""FastAPI application: upload, review, gallery, cost dashboard.

Thin HTTP layer. Routes validate input, call into core (pure) or store/worker
(I/O), and render. Business logic does not live here.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from gerry import __version__
from gerry.core.ingest import IngestError, validate_upload
from gerry.settings import get_settings, load_yaml_config
from gerry.store import repository as repo
from gerry.store.db import init_engine, session_scope, wait_for_database
from gerry.store.objects import upload_key
from gerry.store.schema import Base, ShootStatus

logger = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start-up: configure logging and the database.

    A database failure is logged but not fatal -- /healthz must still answer,
    so a bad DB doesn't present as a dead deploy.
    """
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    try:
        engine = init_engine(settings.database_url)
        # Fly stops idle Postgres; the first connection wakes it but the boot
        # takes ~20s. Wait rather than serving 500s during that window.
        if wait_for_database(engine):
            Base.metadata.create_all(engine)
            logger.info("database ready")
        else:
            logger.error("database did not come up; /healthz will still answer")
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.error("database unavailable at startup: %s", exc)
    yield


app = FastAPI(title="Gerry", version=__version__, lifespan=lifespan)


@dataclass
class FrameView:
    """What a template needs about one frame."""

    id: str
    filename: str
    url: str
    verdict: str
    quality: float | None
    duplicate_group: int | None
    score: Any
    overridden: bool = False
    auto_rejected: bool = False


def _config() -> dict[str, Any]:
    return load_yaml_config()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. Dependency-free so it works during incidents."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
        "git_sha": settings.git_sha,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> RedirectResponse:
    return RedirectResponse("/shoots", status_code=302)


@app.get("/shoots", response_class=HTMLResponse)
def shoots_index(request: Request) -> Any:
    with session_scope() as session:
        shoots = repo.list_shoots(session)
        return TEMPLATES.TemplateResponse(request, "shoots.html", {"shoots": shoots})


@app.post("/shoots")
async def create_shoot(
    name: str = Form(...), files: list[UploadFile] = File(...)
) -> RedirectResponse:
    """Accept an upload, store the frames, and queue processing."""
    cfg = _config()
    settings = get_settings()
    prefix = cfg.get("s3", {}).get("upload_prefix", "uploads/")

    accepted: dict[str, bytes] = {}
    rejected: list[str] = []
    for upload in files:
        data = await upload.read()
        try:
            ok = validate_upload(upload.filename or "unnamed", data)
        except IngestError as exc:
            rejected.append(str(exc))
            continue
        accepted[ok.safe_name] = data

    if not accepted:
        raise HTTPException(400, f"no usable files. {'; '.join(rejected[:5])}")
    if rejected:
        logger.warning("rejected %d of %d uploads", len(rejected), len(files))

    with session_scope() as session:
        shoot = repo.create_shoot(session, name)
        for filename in sorted(accepted):
            repo.add_frame(
                session,
                shoot,
                filename,
                upload_key(prefix, shoot.id, filename),
            )
        repo.set_status(session, shoot, ShootStatus.QUEUED)
        shoot_id = shoot.id

    logger.info("shoot %s created with %d frames", shoot_id, len(accepted))
    from gerry.worker.runner import enqueue

    enqueue(shoot_id, accepted, settings, cfg)
    return RedirectResponse(f"/shoots/{shoot_id}", status_code=303)


def _frame_views(shoot: Any, threshold: float | None = None) -> list[FrameView]:
    """Build template views, optionally re-thresholding on the fly.

    Quality scores are stored per frame, so changing the cut point is a pure
    recomputation -- no model calls, no cost.
    """
    from gerry.core.threshold_view import ScoredItem, verdict_at
    from gerry.worker.runner import frame_url

    views = []
    for f in sorted(shoot.frames, key=lambda x: x.filename):
        if threshold is None:
            verdict = (
                f.score.final_verdict if f.score else ("reject" if f.auto_rejected else "unscored")
            )
        else:
            verdict = verdict_at(
                ScoredItem(
                    filename=f.filename,
                    quality=f.quality,
                    auto_rejected=f.auto_rejected,
                    override=(f.score.override_verdict if f.score else None),
                ),
                threshold,
            )
        views.append(
            FrameView(
                id=f.id,
                filename=f.filename,
                url=frame_url(f.s3_key),
                verdict=verdict,
                quality=f.quality,
                duplicate_group=f.duplicate_group,
                score=f.score,
                overridden=bool(f.score and f.score.override_verdict),
            )
        )
    return views


@app.get("/shoots/{shoot_id}", response_class=HTMLResponse)
def review(request: Request, shoot_id: str, threshold: float | None = None) -> Any:
    """Review a shoot, optionally at a different keep threshold.

    The slider re-thresholds an already-scored shoot for free, so the
    operating point is something to explore by feel on real work rather than
    guess at in config (ADR 0003).
    """
    from gerry.core.threshold_view import ScoredItem, suggest_thresholds

    cfg = _config()
    default_t = float(cfg.get("scoring", {}).get("keep_threshold", 83))
    active = default_t if threshold is None else threshold

    with session_scope() as session:
        shoot = repo.get_shoot(session, shoot_id)
        if shoot is None:
            raise HTTPException(404, "no such shoot")
        frames = _frame_views(shoot, active)
        items = [
            ScoredItem(
                filename=f.filename,
                quality=f.quality,
                auto_rejected=f.auto_rejected,
                override=(f.score.override_verdict if f.score else None),
            )
            for f in shoot.frames
        ]
        return TEMPLATES.TemplateResponse(
            request,
            "review.html",
            {
                "shoot": shoot,
                "frames": frames,
                "keep_count": sum(1 for f in frames if f.verdict == "keep"),
                "threshold": active,
                "default_threshold": default_t,
                "curve": suggest_thresholds(items),
            },
        )


@app.post("/frames/{frame_id}/override", response_class=HTMLResponse)
def override(request: Request, frame_id: str, verdict: str) -> Any:
    """Record a human override and re-render just that card.

    Overrides are the feedback loop: each one is a candidate addition to the
    golden set.
    """
    if verdict not in {"keep", "maybe", "reject"}:
        raise HTTPException(400, f"invalid verdict: {verdict}")
    with session_scope() as session:
        score = repo.override_verdict(session, frame_id, verdict)
        if score is None:
            raise HTTPException(404, "no score for that frame")
        frame = score.frame
        from gerry.worker.runner import frame_url

        view = FrameView(
            id=frame.id,
            filename=frame.filename,
            url=frame_url(frame.s3_key),
            verdict=verdict,
            quality=frame.quality,
            duplicate_group=frame.duplicate_group,
            score=score,
            overridden=True,
        )
        return TEMPLATES.TemplateResponse(request, "_card.html", {"f": view})


@app.get("/shoots/{shoot_id}/gallery", response_class=HTMLResponse)
def gallery(request: Request, shoot_id: str, threshold: float | None = None) -> Any:
    """Client-facing gallery of approved frames, via expiring signed URLs."""
    cfg = _config()
    ttl = int(cfg.get("s3", {}).get("signed_url_ttl_seconds", 604800))
    active = (
        float(cfg.get("scoring", {}).get("keep_threshold", 83)) if threshold is None else threshold
    )
    with session_scope() as session:
        shoot = repo.get_shoot(session, shoot_id)
        if shoot is None:
            raise HTTPException(404, "no such shoot")
        frames = [f for f in _frame_views(shoot, active) if f.verdict == "keep"]
        return TEMPLATES.TemplateResponse(
            request,
            "gallery.html",
            {
                "shoot": shoot,
                "frames": [
                    {
                        "filename": f.filename,
                        "url": f.url,
                        "alt_text": (f.score.alt_text if f.score else f.filename),
                    }
                    for f in frames
                ],
                "ttl_days": ttl // 86400,
            },
        )


@app.get("/costs", response_class=HTMLResponse)
def costs(request: Request) -> Any:
    cfg = _config()
    scoring = cfg.get("scoring", {})
    with session_scope() as session:
        return TEMPLATES.TemplateResponse(
            request,
            "costs.html",
            {
                "s": repo.spend_summary(session),
                "model": scoring.get("model", "?"),
                "prompt_version": scoring.get("prompt_version", "?"),
                "keep_threshold": scoring.get("keep_threshold", "?"),
            },
        )
