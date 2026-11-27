"""Best-of-group selection.

The model judges each frame in isolation, which cannot replicate the
comparative judgement a photographer makes inside a burst (see ADR 0001).
This module supplies the missing comparison: within a near-duplicate group,
promote the strongest frame and demote its redundant siblings.

Pure functions -- the model has already run by the time these are called.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Ordering for "which verdict is stronger"
VERDICT_RANK = {"keep": 3, "maybe": 2, "reject": 1, "unscored": 0}


@dataclass(frozen=True)
class ScoredFrame:
    """A frame after per-frame model scoring, before group reconciliation."""

    filename: str
    verdict: str
    blur_score: float = 0.0
    group_id: int | None = None


@dataclass(frozen=True)
class GroupDecision:
    """Final verdicts for one duplicate group."""

    group_id: int | None
    winner: str | None
    verdicts: dict[str, str]


def rank_within_group(frames: Sequence[ScoredFrame]) -> list[ScoredFrame]:
    """Order frames best-first. Pure and deterministic.

    Primary key is the model's verdict (a `keep` beats a `maybe`); ties break
    on sharpness, which is a cheap objective signal the pre-filter already
    computed. Filename breaks remaining ties so the result is stable.
    """
    return sorted(
        frames,
        key=lambda f: (-VERDICT_RANK.get(f.verdict, 0), -f.blur_score, f.filename),
    )


def resolve_group(frames: Sequence[ScoredFrame], *, demote_to: str = "maybe") -> GroupDecision:
    """Keep the best frame in a burst; demote redundant siblings.

    A group member only gets demoted if it was going to be a `keep`. Frames
    the model already rejected stay rejected -- being redundant doesn't make
    a blurry frame worse.
    """
    if not frames:
        return GroupDecision(group_id=None, winner=None, verdicts={})

    ordered = rank_within_group(frames)
    winner = ordered[0]
    verdicts: dict[str, str] = {winner.filename: winner.verdict}

    for frame in ordered[1:]:
        if frame.verdict == "keep":
            # Technically fine, but a better near-identical frame exists.
            verdicts[frame.filename] = demote_to
        else:
            verdicts[frame.filename] = frame.verdict

    return GroupDecision(group_id=frames[0].group_id, winner=winner.filename, verdicts=verdicts)


def apply_group_selection(
    frames: Sequence[ScoredFrame], *, demote_to: str = "maybe"
) -> dict[str, str]:
    """Reconcile per-frame verdicts across all duplicate groups. Pure.

    Frames with `group_id is None` are singletons and pass through untouched.
    """
    singletons = [f for f in frames if f.group_id is None]
    grouped: dict[int, list[ScoredFrame]] = {}
    for f in frames:
        if f.group_id is not None:
            grouped.setdefault(f.group_id, []).append(f)

    out: dict[str, str] = {f.filename: f.verdict for f in singletons}
    for _gid, members in sorted(grouped.items()):
        out.update(resolve_group(members, demote_to=demote_to).verdicts)
    return out


def attach_groups(
    verdicts: Mapping[str, str],
    groups: Mapping[str, int],
    blur: Mapping[str, float] | None = None,
) -> list[ScoredFrame]:
    """Build ScoredFrames from separate verdict/group/blur maps. Pure."""
    blur = blur or {}
    return [
        ScoredFrame(
            filename=name,
            verdict=verdict,
            blur_score=blur.get(name, 0.0),
            group_id=groups.get(name),
        )
        for name, verdict in sorted(verdicts.items())
    ]
