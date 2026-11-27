"""Shoot processing pipeline: pre-filter, score, threshold.

Side-effecting orchestration. Each step it calls is pure or a thin adapter,
so this module stays a readable sequence rather than a place logic hides.

Order matters: the deterministic tier runs first and costs nothing, so every
frame it rejects is a frame the model is never paid to look at.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import imagehash
import numpy as np
from PIL import Image

from gerry.core.prefilter import assess_quality, group_near_duplicates
from gerry.models.base import ScoringError, VisionScorer

logger = logging.getLogger(__name__)


@dataclass
class FrameResult:
    """Everything known about one frame after processing."""

    filename: str
    phash: str
    blur_score: float
    auto_rejected: bool
    duplicate_group: int | None = None
    quality: float | None = None
    verdict: str = "unscored"
    reason: str = ""
    keywords: list[str] | None = None
    alt_text: str = ""
    cost_usd: float = 0.0
    latency_ms: int = 0


def analyse_image(
    data: bytes, *, blur_threshold: float, clipped_fraction: float
) -> tuple[str, float, bool]:
    """Perceptual hash + technical quality for one frame.

    Returns (phash, blur_score, auto_rejected). Thin wrapper: decoding is I/O-ish,
    the judgement is pure (gerry.core.prefilter).
    """
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        phash = str(imagehash.phash(im))
        grey = np.asarray(im.convert("L").resize((256, 256)))
    report = assess_quality(grey, blur_threshold=blur_threshold, clipped_fraction=clipped_fraction)
    return phash, report.blur_score, report.auto_reject


def process_shoot(
    frames: dict[str, bytes],
    scorer: VisionScorer,
    *,
    keep_threshold: float = 83.0,
    phash_distance: int = 8,
    blur_threshold: float = 100.0,
    clipped_fraction: float = 0.25,
) -> list[FrameResult]:
    """Run the full pipeline over one shoot's frames.

    1. Deterministic pre-filter (free): hash, blur, exposure.
    2. Near-duplicate grouping (free), for review-UI presentation.
    3. Vision scoring (metered) -- skipped for auto-rejected frames.
    4. Apply OUR keep threshold to the model's score (ADR 0003): the model
       ranks, we decide where the line is.
    """
    results: dict[str, FrameResult] = {}
    hashes: dict[str, str] = {}

    for name, data in sorted(frames.items()):
        try:
            phash, blur, auto_reject = analyse_image(
                data, blur_threshold=blur_threshold, clipped_fraction=clipped_fraction
            )
        except (OSError, ValueError) as exc:
            logger.warning("could not decode %s: %s", name, exc)
            results[name] = FrameResult(name, "", 0.0, True, reason=f"undecodable: {exc}")
            continue
        hashes[name] = phash
        results[name] = FrameResult(name, phash, blur, auto_reject)

    # Grouping is presentation metadata, not a verdict (ADR 0002).
    for group in group_near_duplicates(hashes, max_distance=phash_distance):
        if len(group.members) > 1:
            for member in group.members:
                results[member].duplicate_group = group.group_id

    skipped = sum(1 for r in results.values() if r.auto_rejected)
    if skipped:
        logger.info("pre-filter auto-rejected %d/%d frames before scoring", skipped, len(results))

    for name, result in results.items():
        if result.auto_rejected:
            result.verdict = "reject"
            result.reason = result.reason or "failed the technical pre-filter"
            continue
        try:
            score = scorer.score(frames[name])
        except ScoringError as exc:
            # Never let a model failure become a silent verdict.
            result.verdict = "unscored"
            result.reason = f"scoring failed: {exc}"
            logger.warning("scoring failed for %s: %s", name, exc)
            continue

        result.quality = score.quality
        result.reason = score.reason
        result.keywords = score.keywords
        result.alt_text = score.alt_text
        result.cost_usd = score.usage.cost_usd
        result.latency_ms = score.usage.latency_ms
        result.verdict = (
            ("keep" if score.quality >= keep_threshold else "reject")
            if score.quality is not None
            else score.verdict
        )

    total = sum(r.cost_usd for r in results.values())
    kept = sum(1 for r in results.values() if r.verdict == "keep")
    logger.info("processed %d frames: %d keep, $%.4f", len(results), kept, total)
    return [results[name] for name in sorted(results)]
