"""Anthropic Claude implementation of VisionScorer."""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass

from anthropic import Anthropic
from anthropic.types import (
    Base64ImageSourceParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
)

from gerry.models.base import (
    FrameScore,
    ScoringError,
    Usage,
    compute_cost,
    load_prompt,
    parse_score_response,
)

logger = logging.getLogger(__name__)


@dataclass
class ClaudeScorer:
    """Scores frames with a Claude vision model.

    The network call is the only impure part; parsing and costing are pure
    helpers from models.base, so they're tested without spending money.
    """

    client: Anthropic
    model: str = "claude-sonnet-4-5"
    prompt_version_name: str = "cull_v1"
    input_per_mtok: float = 3.00
    output_per_mtok: float = 15.00
    max_tokens: int = 512

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def prompt_version(self) -> str:
        return self.prompt_version_name

    def score(self, image_bytes: bytes, media_type: str = "image/jpeg") -> FrameScore:
        """Score one frame. Raises ScoringError if the reply is unusable."""
        prompt = load_prompt(self.prompt_version_name)
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")

        image_block = ImageBlockParam(
            type="image",
            source=Base64ImageSourceParam(
                type="base64",
                media_type=media_type,  # type: ignore[typeddict-item]
                data=encoded,
            ),
        )
        text_block = TextBlockParam(type="text", text=prompt)
        message: MessageParam = {
            "role": "user",
            "content": [image_block, text_block],
        }

        started = time.perf_counter()
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[message],
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens
        usage = Usage(
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=compute_cost(
                in_tok,
                out_tok,
                input_per_mtok=self.input_per_mtok,
                output_per_mtok=self.output_per_mtok,
            ),
            latency_ms=latency_ms,
        )

        blocks = [b for b in response.content if b.type == "text"]
        if not blocks:
            raise ScoringError("response contained no text block")

        logger.info(
            "scored frame: model=%s prompt=%s in=%d out=%d cost=$%.5f %dms",
            self.model,
            self.prompt_version_name,
            in_tok,
            out_tok,
            usage.cost_usd,
            latency_ms,
        )
        return parse_score_response(
            blocks[0].text,
            prompt_version=self.prompt_version_name,
            model=self.model,
            usage=usage,
        )
