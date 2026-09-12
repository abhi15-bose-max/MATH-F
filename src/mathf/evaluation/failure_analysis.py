"""
Failure analysis: not just "how many proofs passed" but "how did the
system fail" (MASTER PROMPT section 21).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any, Dict, List


def analyze_failures(trajectories: List[Dict[str, Any]]) -> Dict[str, Any]:
    failure_counts: Counter = Counter()
    unsolved_problems: List[str] = []
    problems_needing_retries: List[Dict[str, Any]] = []
    attempts_for_solved: List[int] = []
    generator_failure_counts: Dict[str, Counter] = defaultdict(Counter)
    repeated_failure_status: Dict[str, Counter] = {}

    for traj in trajectories:
        problem_id = traj.get("problem_id")
        generator = traj.get("generator", "unknown")
        solved = bool(traj.get("solved", False))
        attempts = traj.get("attempts", [])

        statuses_this_problem: Counter = Counter()
        for a in attempts:
            v = a.get("verification", {})
            status = v.get("status", "UNKNOWN")
            if not v.get("verified"):
                failure_counts[status] += 1
                generator_failure_counts[generator][status] += 1
                statuses_this_problem[status] += 1

        if statuses_this_problem:
            repeated_failure_status[problem_id] = statuses_this_problem

        if solved:
            solved_at = next(
                (a["attempt"] for a in attempts if a.get("verification", {}).get("verified")),
                None,
            )
            if solved_at is not None:
                attempts_for_solved.append(solved_at)
                if solved_at > 1:
                    problems_needing_retries.append(
                        {"problem_id": problem_id, "attempts_needed": solved_at}
                    )
        else:
            unsolved_problems.append(problem_id)

    repeated_failures = {
        pid: dict(counter)
        for pid, counter in repeated_failure_status.items()
        if sum(counter.values()) > 1 and len(counter) == 1
        # same failure status repeated 2+ times with no other status seen
    }

    return {
        "failure_counts_by_status": dict(failure_counts),
        "unsolved_problems": unsolved_problems,
        "problems_needing_retries": problems_needing_retries,
        "average_attempts_for_solved": (
            round(statistics.mean(attempts_for_solved), 4) if attempts_for_solved else None
        ),
        "repeated_identical_failure_problems": repeated_failures,
        "generator_specific_failure_patterns": {
            gen: dict(counts) for gen, counts in generator_failure_counts.items()
        },
    }


def format_failure_report(report: Dict[str, Any]) -> str:
    lines = ["Failure analysis", "=================", ""]
    lines.append("Failures by status:")
    for status, count in sorted(report["failure_counts_by_status"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {status}: {count}")
    lines.append("")
    lines.append(f"Unsolved problems ({len(report['unsolved_problems'])}):")
    for pid in report["unsolved_problems"]:
        lines.append(f"  - {pid}")
    lines.append("")
    lines.append(f"Problems that needed retries ({len(report['problems_needing_retries'])}):")
    for entry in report["problems_needing_retries"]:
        lines.append(f"  - {entry['problem_id']}: solved after {entry['attempts_needed']} attempts")
    lines.append("")
    lines.append(f"Average attempts for solved problems: {report['average_attempts_for_solved']}")
    lines.append("")
    lines.append("Generator-specific failure patterns:")
    for gen, counts in report["generator_specific_failure_patterns"].items():
        lines.append(f"  {gen}: {counts}")
    return "\n".join(lines)
