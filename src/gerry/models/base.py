"""The VisionScorer interface and its data types.

Everything model-specific lives behind this interface so the provider can be
swapped by config. The parsing and cost arithmetic here are pure, which is
what lets the eval harness be tested without spending money.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts"

VALID_VERDICTS = frozenset({"keep", "maybe", "reject"})


class ScoringError(Exception):
    """The model produced something unusable."""


@dataclass(frozen=True)
class Usage:
    """Token counts and cost for one model call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


@dataclass(frozen=True)
class FrameScore:
    """A validated verdict for one frame."""

    verdict: str
    reason: str
    keywords: list[str] = field(default_factory=list)
    alt_text: str = ""
    usage: Usage = field(default_factory=Usage)
    prompt_version: str = "unknown"
    model: str = "unknown"


class VisionScorer(Protocol):
    """What the pipeline needs from a vision model."""

    @property
    def model_name(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    def score(self, image_bytes: bytes, media_type: str = "image/jpeg") -> FrameScore: ...


# --- pure helpers -----------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def strip_code_fences(text: str) -> str:
    """Remove markdown fences a model may add despite instructions. Pure."""
    return _FENCE.sub("", text).strip()


def parse_score_response(
    text: str,
    *,
    prompt_version: str = "unknown",
    model: str = "unknown",
    usage: Usage | None = None,
) -> FrameScore:
    """Parse and validate the model's JSON reply. Pure.

    Raises ScoringError on anything unusable, so the caller can retry or fall
    back to 'unscored' rather than writing a bogus verdict to the database.
    """
    cleaned = strip_code_fences(text)
    if not cleaned:
        raise ScoringError("empty response")

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ScoringError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ScoringError(f"expected a JSON object, got {type(data).__name__}")

    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VALID_VERDICTS:
        raise ScoringError(f"invalid verdict: {data.get('verdict')!r}")

    raw_keywords = data.get("keywords", [])
    if isinstance(raw_keywords, str):
        keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
    elif isinstance(raw_keywords, list):
        keywords = [str(k).strip().lower() for k in raw_keywords if str(k).strip()]
    else:
        keywords = []

    return FrameScore(
        verdict=verdict,
        reason=str(data.get("reason", "")).strip(),
        keywords=keywords,
        alt_text=str(data.get("alt_text", "")).strip(),
        usage=usage or Usage(),
        prompt_version=prompt_version,
        model=model,
    )


def load_prompt(version: str, prompt_dir: Path = PROMPT_DIR) -> str:
    """Read a versioned prompt file, dropping its YAML front matter.

    Prompts are versioned files in the repo so a change is reviewable in a
    diff and the eval job can be triggered by touching them.
    """
    path = prompt_dir / f"{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt file for version {version!r}: {path}")
    text = path.read_text()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


def compute_cost(
    input_tokens: int,
    output_tokens: int,
    *,
    input_per_mtok: float,
    output_per_mtok: float,
) -> float:
    """Cost in USD from token counts and a price table. Pure.

    Prices come from config, never hardcoded, so a provider price change is
    a config edit rather than a code change.
    """
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts cannot be negative")
    return (input_tokens / 1_000_000) * input_per_mtok + (
        output_tokens / 1_000_000
    ) * output_per_mtok
