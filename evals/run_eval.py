#!/usr/bin/env python3
"""Run the golden set through a scorer and apply the merge gate.

    # offline, free -- proves the harness works
    python evals/run_eval.py --scorer stub

    # real model; costs money (~$0.74 per 100 frames)
    python evals/run_eval.py --scorer claude --limit 50

Writes result JSON and a markdown PR comment, and exits non-zero when the
gate fails -- which is what blocks the merge.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gerry.evals.gate import (
    GateThresholds,
    check_gate,
    format_pr_comment,
    load_baseline,
)
from gerry.evals.metrics import evaluate
from gerry.models.base import ScoringError, VisionScorer
from gerry.models.stub import StubScorer

logger = logging.getLogger("eval")


def load_labels(path: Path) -> dict[str, str]:
    """filename -> label from the hand-labeled golden set."""
    if not path.exists():
        raise FileNotFoundError(
            f"no labels at {path}. Build the golden set first:\n"
            "  python tools/build_golden_set.py --shoot <dir>\n"
            "  python tools/label.py"
        )
    with path.open(newline="") as fh:
        return {r["filename"]: r["label"].strip().lower() for r in csv.DictReader(fh)}


def build_scorer(name: str, prompt_version: str | None = None) -> VisionScorer:
    """Instantiate a scorer by name -- the config-driven swap in practice."""
    if name == "stub":
        return StubScorer()
    if name == "claude":
        from anthropic import Anthropic

        from gerry.models.claude import ClaudeScorer

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("ANTHROPIC_API_KEY is required for --scorer claude")
        scorer = ClaudeScorer(client=Anthropic(api_key=key))
        if prompt_version:
            scorer.prompt_version_name = prompt_version
        return scorer
    raise SystemExit(f"unknown scorer: {name!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scorer", default="stub", choices=["stub", "claude"])
    ap.add_argument("--images", type=Path, default=Path("data/golden/images"))
    ap.add_argument("--labels", type=Path, default=Path("data/golden/labels.csv"))
    ap.add_argument("--baseline", type=Path, default=Path("evals/baseline.json"))
    ap.add_argument("--out", type=Path, default=Path("evals/last_result.json"))
    ap.add_argument("--comment-out", type=Path, default=Path("evals/pr_comment.md"))
    ap.add_argument(
        "--predictions-out",
        type=Path,
        default=Path("evals/last_predictions.csv"),
        help="Per-frame predictions, so failures can be analysed without paying to re-run the eval",
    )
    ap.add_argument("--limit", type=int, default=0, help="0 = all frames")
    ap.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Parallel model calls. I/O-bound, so this is mostly "
        "bounded by provider rate limits, not local CPU.",
    )
    ap.add_argument(
        "--prompt-version", default=None, help="Override the prompt version (e.g. cull_v2)"
    )
    ap.add_argument("--min-precision", type=float, default=0.75)
    ap.add_argument("--min-auc", type=float, default=0.60)
    ap.add_argument("--max-cost-increase", type=float, default=20.0)
    ap.add_argument(
        "--keep-threshold",
        type=float,
        default=None,
        help="Quality score at/above which a frame is 'keep'. "
        "When set, overrides the model's own verdict -- the "
        "ranking is the model's job, the cut point is ours.",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )

    labels = load_labels(args.labels)
    names = sorted(labels)
    if args.limit:
        names = names[: args.limit]
    logger.info("evaluating %d frames with scorer=%s", len(names), args.scorer)

    scorer = build_scorer(args.scorer, args.prompt_version)
    predicted: dict[str, str] = {}
    costs: list[float] = []
    latencies: list[int] = []
    failures = 0
    qualities: dict[str, float] = {}
    lock = Lock()
    done = 0

    def score_one(name: str) -> None:
        nonlocal failures, done
        image_path = args.images / name
        if not image_path.exists():
            logger.warning("missing image, skipping: %s", name)
            return
        try:
            score = scorer.score(image_path.read_bytes())
            with lock:
                predicted[name] = score.verdict
                if score.quality is not None:
                    qualities[name] = score.quality
                costs.append(score.usage.cost_usd)
                latencies.append(score.usage.latency_ms)
        except (ScoringError, OSError) as exc:
            # A model failure must never silently become a verdict.
            with lock:
                failures += 1
                predicted[name] = "unscored"
            logger.warning("scoring failed for %s: %s", name, exc)
        with lock:
            done += 1
            if done % 50 == 0:
                logger.info("  %d/%d (spend so far $%.4f)", done, len(names), sum(costs))

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(score_one, n) for n in names]
        for f in as_completed(futures):
            f.result()

    # Apply our own threshold to the model's ranking, when we have scores.
    if args.keep_threshold is not None and qualities:
        overridden = {
            name: ("keep" if qualities.get(name, -1.0) >= args.keep_threshold else "reject")
            for name in predicted
            if name in qualities
        }
        predicted.update(overridden)
        logger.info(
            "applied keep-threshold %.0f to %d scored frames", args.keep_threshold, len(overridden)
        )

    result = evaluate(
        predicted, labels, costs_usd=costs, latencies_ms=latencies, scores=qualities or None
    )
    baseline = load_baseline(args.baseline)
    thresholds = GateThresholds(
        min_auc=args.min_auc,
        min_keep_precision=args.min_precision,
        max_cost_increase_pct=args.max_cost_increase,
    )
    decision = check_gate(result, thresholds, baseline)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result.as_dict(), indent=2) + "\n")

    # Per-frame detail: an eval you can't inspect only tells you *that*
    # something regressed, not what.
    with args.predictions_out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["filename", "predicted", "labeled", "correct", "quality"])
        for name in sorted(predicted):
            pred, truth = predicted[name], labels.get(name, "")
            writer.writerow([name, pred, truth, int(pred == truth), qualities.get(name, "")])
    comment = format_pr_comment(result, decision, baseline)
    args.comment_out.write_text(comment + "\n")

    print("\n" + comment + "\n")
    if failures:
        logger.warning("%d frames could not be scored (recorded as 'unscored')", failures)
    logger.info("total spend this run: $%.4f", result.cost_total_usd)

    return 0 if decision.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
