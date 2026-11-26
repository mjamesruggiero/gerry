"""Deterministic pre-filter: near-duplicate grouping and technical quality checks.

Pure functions only -- no file or network I/O. Callers load pixels and pass
them in. This is the zero-model-cost tier of the pipeline, so it must be
cheap, deterministic, and thoroughly tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class QualityReport:
    """Technical assessment of a single frame."""

    blur_score: float  # variance of Laplacian; higher = sharper
    clipped_shadows: float  # fraction of pixels at/near 0
    clipped_highlights: float  # fraction of pixels at/near 255
    is_blurry: bool
    is_poorly_exposed: bool

    @property
    def auto_reject(self) -> bool:
        """Obvious technical failure -- skip the model entirely."""
        return self.is_blurry and self.is_poorly_exposed


@dataclass
class DuplicateGroup:
    """A cluster of near-identical frames (e.g. a burst)."""

    group_id: int
    members: list[str] = field(default_factory=list)


def variance_of_laplacian(gray: np.ndarray) -> float:
    """Focus measure: variance of the Laplacian. Higher = sharper.

    Uses an explicit 3x3 kernel so the result is reproducible and has no
    OpenCV dependency.
    """
    if gray.ndim != 2:
        raise ValueError(f"expected 2-D grayscale array, got shape {gray.shape}")
    if gray.size == 0:
        raise ValueError("empty image")

    kernel = np.array([[0.0, 1.0, 0.0], [1.0, -4.0, 1.0], [0.0, 1.0, 0.0]])
    img = gray.astype(np.float64)
    h, w = img.shape
    if h < 3 or w < 3:
        return 0.0

    # 'valid' 2-D convolution via stride tricks
    windows = np.lib.stride_tricks.sliding_window_view(img, (3, 3))
    conv = np.einsum("ijkl,kl->ij", windows, kernel)
    return float(conv.var())


def exposure_fractions(gray: np.ndarray, tolerance: int = 2) -> tuple[float, float]:
    """Return (clipped_shadows, clipped_highlights) as fractions of all pixels."""
    if gray.size == 0:
        raise ValueError("empty image")
    total = gray.size
    shadows = float(np.count_nonzero(gray <= tolerance) / total)
    highlights = float(np.count_nonzero(gray >= 255 - tolerance) / total)
    return shadows, highlights


def assess_quality(
    gray: np.ndarray,
    *,
    blur_threshold: float = 100.0,
    clipped_fraction: float = 0.25,
) -> QualityReport:
    """Score one frame's technical quality. Pure."""
    blur = variance_of_laplacian(gray)
    shadows, highlights = exposure_fractions(gray)
    return QualityReport(
        blur_score=blur,
        clipped_shadows=shadows,
        clipped_highlights=highlights,
        is_blurry=blur < blur_threshold,
        is_poorly_exposed=max(shadows, highlights) > clipped_fraction,
    )


def hamming_distance(a: str, b: str) -> int:
    """Bitwise distance between two equal-length hex perceptual hashes."""
    if len(a) != len(b):
        raise ValueError(f"hash length mismatch: {len(a)} vs {len(b)}")
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def group_near_duplicates(hashes: dict[str, str], *, max_distance: int = 8) -> list[DuplicateGroup]:
    """Cluster frames whose perceptual hashes are within `max_distance`.

    Single-linkage via union-find: A~B and B~C puts all three together, which
    is what we want for a burst that drifts gradually.

    Deterministic: input keys are sorted, so group ids are stable across runs.
    """
    keys = sorted(hashes)
    parent = {k: k for k in keys}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if hamming_distance(hashes[a], hashes[b]) <= max_distance:
                union(a, b)

    clusters: dict[str, list[str]] = {}
    for k in keys:
        clusters.setdefault(find(k), []).append(k)

    return [
        DuplicateGroup(group_id=i, members=sorted(members))
        for i, (_root, members) in enumerate(sorted(clusters.items()))
    ]
