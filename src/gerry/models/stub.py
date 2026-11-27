"""A deterministic VisionScorer for tests and offline development.

Not a mock in the unittest sense -- a real implementation of the interface
that returns reproducible verdicts without network access. Also demonstrates
that the interface genuinely supports swapping providers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from gerry.models.base import FrameScore, Usage

VERDICT_CYCLE = ("keep", "maybe", "reject")


@dataclass
class StubScorer:
    """Verdict derived from a hash of the image bytes: stable, no network."""

    model: str = "stub-v0"
    prompt_version_name: str = "cull_v1"
    calls: list[int] = field(default_factory=list)

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def prompt_version(self) -> str:
        return self.prompt_version_name

    def score(self, image_bytes: bytes, media_type: str = "image/jpeg") -> FrameScore:
        self.calls.append(len(image_bytes))
        digest = hashlib.sha256(image_bytes).digest()
        verdict = VERDICT_CYCLE[digest[0] % len(VERDICT_CYCLE)]
        return FrameScore(
            verdict=verdict,
            reason=f"stub verdict derived from content hash ({verdict})",
            keywords=["stub", "test"],
            alt_text="A placeholder description produced by the stub scorer.",
            usage=Usage(input_tokens=1000, output_tokens=50, cost_usd=0.0, latency_ms=1),
            prompt_version=self.prompt_version_name,
            model=self.model,
        )
