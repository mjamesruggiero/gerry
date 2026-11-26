"""Tests for the pure parts of the golden-set tooling."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from build_golden_set import select_frames


def paths(n: int) -> list[Path]:
    return [Path(f"DSC{i:05d}.ARW") for i in range(n)]


class TestSelectFrames:
    def test_empty_input(self):
        assert select_frames([], 10) == []

    def test_zero_limit(self):
        assert select_frames(paths(50), 0) == []

    def test_fewer_files_than_limit_returns_all(self):
        files = paths(5)
        assert select_frames(files, 10) == files

    def test_respects_limit(self):
        assert len(select_frames(paths(500), 75)) == 75

    def test_spreads_across_the_shoot(self):
        # even spacing: should reach deep into the shoot, not just the head
        picked = select_frames(paths(100), 10)
        assert picked[0] == Path("DSC00000.ARW")
        assert picked[-1].stem > "DSC00080"

    def test_is_deterministic(self):
        files = paths(200)
        assert select_frames(files, 25) == select_frames(files, 25)

    def test_no_duplicates(self):
        picked = select_frames(paths(200), 50)
        assert len(set(picked)) == len(picked)
