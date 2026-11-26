#!/usr/bin/env python3
"""Label the golden set: keep / maybe / reject, one frame at a time.

Opens each image in Preview, waits for a single keystroke, appends to a CSV.
Resumable -- already-labeled frames are skipped, so you can stop any time.

These labels are the ground truth the eval gate measures the model against,
so they are the most valuable artifact in the repo. The CSV is committed;
the images are not (see .gitignore).

Example:
    python tools/label.py --images data/golden/images --labels data/golden/labels.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import subprocess
import sys
import termios
import tty
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("label")

VALID = {"k": "keep", "m": "maybe", "r": "reject"}
FIELDNAMES = ["filename", "label", "labeled_at"]


def load_existing(labels_path: Path) -> dict[str, str]:
    """Filenames already labeled -> label. Lets the session resume."""
    if not labels_path.exists():
        return {}
    with labels_path.open(newline="") as fh:
        return {r["filename"]: r["label"] for r in csv.DictReader(fh)}


def append_label(labels_path: Path, filename: str, label: str) -> None:
    """Append one row, writing a header if the file is new."""
    is_new = not labels_path.exists()
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    with labels_path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "filename": filename,
                "label": label,
                "labeled_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )


def read_key() -> str:
    """Read a single keypress without waiting for Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1).lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def summarize(counts: dict[str, int]) -> str:
    total = sum(counts.values()) or 1
    return "  ".join(
        f"{name}={counts.get(name, 0)} ({100 * counts.get(name, 0) / total:.0f}%)"
        for name in ("keep", "maybe", "reject")
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--images", type=Path, default=Path("data/golden/images"))
    ap.add_argument("--labels", type=Path, default=Path("data/golden/labels.csv"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.images.is_dir():
        logger.error("no such directory: %s -- run build_golden_set.py first", args.images)
        return 2

    images = sorted(p for p in args.images.glob("*.jpg"))
    done = load_existing(args.labels)
    todo = [p for p in images if p.name not in done]

    counts: dict[str, int] = {}
    for label in done.values():
        counts[label] = counts.get(label, 0) + 1

    print(f"\n  {len(images)} images, {len(done)} labeled, {len(todo)} remaining")
    print("  [k] keep   [m] maybe   [r] reject   [u] undo-skip   [q] quit\n")

    if not todo:
        print(f"  All labeled.  {summarize(counts)}\n")
        return 0

    viewer = None
    try:
        for i, img in enumerate(todo, start=1):
            if viewer:
                viewer.terminate()
            viewer = subprocess.Popen(
                ["qlmanage", "-p", str(img)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"  [{i}/{len(todo)}] {img.name[:70]:<70}", end="", flush=True)

            while True:
                key = read_key()
                if key == "q":
                    print("\n\n  Stopped.  " + summarize(counts) + "\n")
                    return 0
                if key == "u":
                    print(" skipped")
                    break
                if key in VALID:
                    label = VALID[key]
                    append_label(args.labels, img.name, label)
                    counts[label] = counts.get(label, 0) + 1
                    print(f" -> {label}")
                    break
                # ignore anything else and keep waiting
    finally:
        if viewer:
            viewer.terminate()

    print(f"\n  Done.  {summarize(counts)}")
    print(f"  Labels: {args.labels}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
