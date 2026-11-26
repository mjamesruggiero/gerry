#!/usr/bin/env python3
"""Report the share of agent-authored commits, and how they fare.

Ties the AI-assisted development story to measurable outcomes: if agent
commits get reverted more often than human ones, that's a finding worth
reporting honestly.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("attribution")

AGENT_TRAILER = "Co-Authored-By: pi"


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    agent_authored: bool
    is_revert: bool


def parse_log(raw: str) -> list[Commit]:
    """Parse `git log` output into Commit records. Pure."""
    commits: list[Commit] = []
    for block in raw.split("\x00"):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        sha = lines[0].strip()
        subject = lines[1].strip() if len(lines) > 1 else ""
        body = "\n".join(lines[2:])
        commits.append(
            Commit(
                sha=sha,
                subject=subject,
                agent_authored=AGENT_TRAILER in body,
                is_revert=subject.lower().startswith("revert"),
            )
        )
    return commits


def summarize(commits: list[Commit]) -> dict[str, float | int]:
    """Aggregate counts and rates. Pure."""
    total = len(commits)
    agent = [c for c in commits if c.agent_authored]
    human = [c for c in commits if not c.agent_authored]
    return {
        "total": total,
        "agent": len(agent),
        "human": len(human),
        "agent_share_pct": round(100 * len(agent) / total, 1) if total else 0.0,
        "reverts_total": sum(c.is_revert for c in commits),
        "reverts_agent": sum(c.is_revert for c in agent),
        "reverts_human": sum(c.is_revert for c in human),
    }


def git_log() -> str:
    """Side-effecting: shell out to git."""
    return subprocess.run(
        ["git", "log", "--format=%H%n%s%n%b%x00"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    stats = summarize(parse_log(git_log()))
    print("\n  Commit attribution")
    print("  " + "-" * 34)
    print(f"  total commits      : {stats['total']}")
    print(f"  agent-authored     : {stats['agent']} ({stats['agent_share_pct']}%)")
    print(f"  human-authored     : {stats['human']}")
    print(f"  reverts (total)    : {stats['reverts_total']}")
    print(f"    of agent commits : {stats['reverts_agent']}")
    print(f"    of human commits : {stats['reverts_human']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
