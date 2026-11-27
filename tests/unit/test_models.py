"""Tests for the model layer: parsing, costing, prompts, and the stub.

No network and no spend -- the pure helpers are what make that possible.
"""

from __future__ import annotations

import pytest

from gerry.models.base import (
    FrameScore,
    ScoringError,
    Usage,
    VisionScorer,
    compute_cost,
    load_prompt,
    parse_score_response,
    strip_code_fences,
)
from gerry.models.stub import StubScorer

GOOD = """{"verdict": "keep", "reason": "sharp with open eyes",
           "keywords": ["portrait", "studio"], "alt_text": "A seated portrait."}"""


class TestStripCodeFences:
    def test_plain_json_untouched(self):
        assert strip_code_fences('{"a": 1}') == '{"a": 1}'

    def test_removes_json_fence(self):
        assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_removes_bare_fence(self):
        assert strip_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'


class TestParseScoreResponse:
    def test_parses_a_good_response(self):
        score = parse_score_response(GOOD, prompt_version="cull_v1", model="m")
        assert score.verdict == "keep"
        assert score.reason == "sharp with open eyes"
        assert score.keywords == ["portrait", "studio"]
        assert score.prompt_version == "cull_v1"

    def test_tolerates_code_fences(self):
        assert parse_score_response(f"```json\n{GOOD}\n```").verdict == "keep"

    def test_normalizes_verdict_case_and_space(self):
        assert parse_score_response('{"verdict": "  KEEP  "}').verdict == "keep"

    @pytest.mark.parametrize("verdict", ["keep", "maybe", "reject"])
    def test_accepts_each_valid_verdict(self, verdict):
        assert parse_score_response(f'{{"verdict": "{verdict}"}}').verdict == verdict

    def test_rejects_unknown_verdict(self):
        with pytest.raises(ScoringError, match="invalid verdict"):
            parse_score_response('{"verdict": "excellent"}')

    def test_rejects_missing_verdict(self):
        with pytest.raises(ScoringError, match="invalid verdict"):
            parse_score_response('{"reason": "nice"}')

    def test_rejects_invalid_json(self):
        with pytest.raises(ScoringError, match="invalid JSON"):
            parse_score_response("not json at all")

    def test_rejects_empty(self):
        with pytest.raises(ScoringError, match="empty"):
            parse_score_response("   ")

    def test_rejects_json_array(self):
        with pytest.raises(ScoringError, match="expected a JSON object"):
            parse_score_response('["keep"]')

    def test_keywords_as_comma_string(self):
        score = parse_score_response('{"verdict": "keep", "keywords": "a, b ,c"}')
        assert score.keywords == ["a", "b", "c"]

    def test_keywords_absent_defaults_empty(self):
        assert parse_score_response('{"verdict": "keep"}').keywords == []

    def test_keywords_wrong_type_defaults_empty(self):
        assert parse_score_response('{"verdict": "keep", "keywords": 42}').keywords == []

    def test_usage_is_attached(self):
        usage = Usage(input_tokens=10, output_tokens=5, cost_usd=0.001, latency_ms=99)
        assert parse_score_response(GOOD, usage=usage).usage.cost_usd == 0.001


class TestComputeCost:
    def test_zero_tokens_is_free(self):
        assert compute_cost(0, 0, input_per_mtok=3.0, output_per_mtok=15.0) == 0.0

    def test_known_values(self):
        # 1M input @ $3 + 1M output @ $15
        assert compute_cost(
            1_000_000, 1_000_000, input_per_mtok=3.0, output_per_mtok=15.0
        ) == pytest.approx(18.0)

    def test_typical_frame(self):
        cost = compute_cost(1500, 120, input_per_mtok=3.0, output_per_mtok=15.0)
        assert cost == pytest.approx(0.0063, abs=1e-6)

    def test_scales_to_100_images(self):
        per_frame = compute_cost(1500, 120, input_per_mtok=3.0, output_per_mtok=15.0)
        assert per_frame * 100 == pytest.approx(0.63, abs=1e-3)

    def test_negative_tokens_raise(self):
        with pytest.raises(ValueError, match="negative"):
            compute_cost(-1, 0, input_per_mtok=3.0, output_per_mtok=15.0)


class TestLoadPrompt:
    def test_loads_and_strips_front_matter(self):
        text = load_prompt("cull_v1")
        assert "You are assisting a professional photographer" in text
        assert "version: cull_v1" not in text  # front matter removed

    def test_contains_the_rubric_and_output_contract(self):
        text = load_prompt("cull_v1")
        for expected in ("Focus on subject", "verdict", "alt_text", "JSON"):
            assert expected in text

    def test_missing_version_raises(self):
        with pytest.raises(FileNotFoundError, match="no prompt file"):
            load_prompt("does_not_exist")


class TestStubScorer:
    def test_satisfies_the_interface(self):
        scorer: VisionScorer = StubScorer()
        assert scorer.model_name == "stub-v0"
        assert scorer.prompt_version == "cull_v1"

    def test_returns_a_valid_verdict(self):
        score = StubScorer().score(b"some image bytes")
        assert isinstance(score, FrameScore)
        assert score.verdict in {"keep", "maybe", "reject"}

    def test_is_deterministic(self):
        a = StubScorer().score(b"identical")
        b = StubScorer().score(b"identical")
        assert a.verdict == b.verdict

    def test_different_bytes_can_differ(self):
        verdicts = {StubScorer().score(f"img{i}".encode()).verdict for i in range(30)}
        assert len(verdicts) > 1  # exercises more than one branch

    def test_records_calls(self):
        scorer = StubScorer()
        scorer.score(b"abc")
        scorer.score(b"defgh")
        assert scorer.calls == [3, 5]

    def test_costs_nothing(self):
        assert StubScorer().score(b"x").usage.cost_usd == 0.0
