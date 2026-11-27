"""The CI gate: decide whether an eval result is allowed to merge.

Two independent checks, both pure:

  1. keep-precision must not fall below an absolute floor
  2. cost per 100 images must not rise more than N% versus the baseline

Separating "compute the metrics" (metrics.py) from "decide pass/fail" (here)
means the thresholds can be tested without running a single model call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gerry.evals.metrics import EvalResult


@dataclass(frozen=True)
class GateThresholds:
    min_keep_precision: float = 0.80
    max_cost_increase_pct: float = 20.0


@dataclass(frozen=True)
class GateFailure:
    check: str
    message: str


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    failures: list[GateFailure]

    def summary(self) -> str:
        if self.passed:
            return "PASS"
        return "FAIL: " + "; ".join(f.message for f in self.failures)


def check_gate(
    result: EvalResult,
    thresholds: GateThresholds,
    baseline: EvalResult | None = None,
) -> GateDecision:
    """Evaluate the merge gate. Pure.

    `baseline` is main's most recent result. When absent (first run, or no
    stored baseline) the cost check is skipped rather than guessed at.
    """
    failures: list[GateFailure] = []

    if result.keep_precision < thresholds.min_keep_precision:
        failures.append(
            GateFailure(
                check="keep_precision",
                message=(
                    f"keep-precision {result.keep_precision:.3f} is below the "
                    f"floor of {thresholds.min_keep_precision:.3f}"
                ),
            )
        )

    if baseline is not None and baseline.cost_per_100_usd > 0:
        increase = (
            (result.cost_per_100_usd - baseline.cost_per_100_usd) / baseline.cost_per_100_usd * 100
        )
        if increase > thresholds.max_cost_increase_pct:
            failures.append(
                GateFailure(
                    check="cost_per_100",
                    message=(
                        f"cost/100 rose {increase:.1f}% "
                        f"(${baseline.cost_per_100_usd:.4f} -> "
                        f"${result.cost_per_100_usd:.4f}), limit is "
                        f"{thresholds.max_cost_increase_pct:.0f}%"
                    ),
                )
            )

    return GateDecision(passed=not failures, failures=failures)


def format_pr_comment(
    result: EvalResult, decision: GateDecision, baseline: EvalResult | None = None
) -> str:
    """Render a markdown metrics diff for a PR comment. Pure."""
    status = "✅ **Eval gate passed**" if decision.passed else "❌ **Eval gate failed**"
    lines = [
        status,
        "",
        f"`n = {result.n}` frames",
        "",
        "| metric | this run | baseline | change |",
        "|---|---|---|---|",
    ]

    def row(
        name: str,
        now: float,
        before: float | None,
        fmt: str = "{:.3f}",
        higher_is_better: bool = True,
    ) -> str:
        if before is None:
            return f"| {name} | {fmt.format(now)} | — | — |"
        delta = now - before
        arrow = "" if abs(delta) < 1e-9 else ("▲" if delta > 0 else "▼")
        good = (delta > 0) == higher_is_better
        marker = "" if abs(delta) < 1e-9 else (" ✅" if good else " ⚠️")
        return (
            f"| {name} | {fmt.format(now)} | {fmt.format(before)} | "
            f"{arrow} {fmt.format(abs(delta))}{marker} |"
        )

    b = baseline
    lines += [
        row("keep-precision", result.keep_precision, b.keep_precision if b else None),
        row("keep-recall", result.keep_recall, b.keep_recall if b else None),
        row("agreement", result.agreement, b.agreement if b else None),
        row(
            "cost / 100 imgs",
            result.cost_per_100_usd,
            b.cost_per_100_usd if b else None,
            "${:.4f}",
            higher_is_better=False,
        ),
        row(
            "p95 latency (ms)",
            float(result.p95_latency_ms),
            float(b.p95_latency_ms) if b else None,
            "{:.0f}",
            higher_is_better=False,
        ),
    ]

    c = result.confusion
    lines += [
        "",
        f"<sub>keep: {c.true_positive} correct, **{c.false_positive} false keeps**, "
        f"{c.false_negative} missed</sub>",
    ]

    if not decision.passed:
        lines += ["", "**Blocking issues:**"]
        lines += [f"- {f.message}" for f in decision.failures]

    return "\n".join(lines)


def load_baseline(path: Path) -> EvalResult | None:
    """Read a stored baseline result, or None if absent/unreadable."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    from gerry.evals.metrics import ConfusionCounts

    return EvalResult(
        n=int(data.get("n", 0)),
        keep_precision=float(data.get("keep_precision", 0.0)),
        keep_recall=float(data.get("keep_recall", 0.0)),
        agreement=float(data.get("agreement", 0.0)),
        cost_total_usd=float(data.get("cost_total_usd", 0.0)),
        cost_per_100_usd=float(data.get("cost_per_100_usd", 0.0)),
        p95_latency_ms=int(data.get("p95_latency_ms", 0)),
        confusion=ConfusionCounts(),
    )
