#!/usr/bin/env python3
"""Convert RAW frames from real shoots into a JPEG golden set for labeling.

The app itself only handles JPEG (RAW is out of scope for v1), but the shoots
on disk are ARW/NEF. macOS `sips` converts them natively, so the tedious part
is automated and only the labeling judgment is left to a human.

Side-effecting by nature (reads shoots, writes JPEGs). The selection logic is
kept pure and tested separately.

Example:
    python tools/build_golden_set.py \\
        --shoot /Volumes/scrappy/photos/2026/2026_02_15_dunstan_head_shots \\
        --shoot /Volumes/scrappy/photos/2026/2026_07_12_les_miserables \\
        --out data/golden/images --per-shoot 75
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("build_golden_set")

RAW_SUFFIXES = {".arw", ".nef", ".raf", ".cr2", ".cr3", ".dng"}


def find_raw_files(shoot: Path) -> list[Path]:
    """All RAW frames in a shoot, sorted for determinism."""
    return sorted(p for p in shoot.rglob("*") if p.is_file() and p.suffix.lower() in RAW_SUFFIXES)


def select_frames(files: list[Path], limit: int) -> list[Path]:
    """Pick up to `limit` frames, evenly spaced across the shoot. Pure.

    Even spacing beats taking the first N: a shoot's opening frames are often
    test shots, and we want bursts from throughout the session.
    """
    if limit <= 0 or not files:
        return []
    if len(files) <= limit:
        return list(files)
    step = len(files) / limit
    return [files[int(i * step)] for i in range(limit)]


def convert(src: Path, dest: Path, max_px: int) -> bool:
    """RAW -> JPEG via macOS sips. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", "-Z", str(max_px), str(src), "--out", str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("convert failed %s: %s", src.name, result.stderr.strip()[:120])
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--shoot", type=Path, action="append", required=True, help="Shoot directory (repeatable)"
    )
    ap.add_argument(
        "--out", type=Path, default=Path("data/golden/images"), help="Output directory for JPEGs"
    )
    ap.add_argument("--per-shoot", type=int, default=75, help="Max frames to take from each shoot")
    ap.add_argument("--max-px", type=int, default=2048, help="Longest edge of the output JPEG")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if sys.platform != "darwin":
        logger.error("requires macOS (uses sips)")
        return 2

    total_ok = total_fail = 0
    for shoot in args.shoot:
        if not shoot.is_dir():
            logger.warning("skipping missing shoot: %s", shoot)
            continue
        raws = find_raw_files(shoot)
        picked = select_frames(raws, args.per_shoot)
        logger.info("%s: %d raw frames, taking %d", shoot.name, len(raws), len(picked))

        for src in picked:
            # Prefix with the shoot name so provenance survives in one flat dir
            dest = args.out / f"{shoot.name}__{src.stem}.jpg"
            if dest.exists():
                continue
            if convert(src, dest, args.max_px):
                total_ok += 1
            else:
                total_fail += 1

    logger.info("converted %d frames (%d failures) -> %s", total_ok, total_fail, args.out)
    logger.info("next: python tools/label.py --images %s", args.out)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
