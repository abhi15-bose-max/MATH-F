"""
Metrics computation over a set of trajectories (as produced by
`mathf.logging.trajectory.load_all_trajectories`, or directly as
`Trajectory` objects).

All functions here accept plain dicts (the JSON shape written by
`Trajectory.to_dict()`) so metrics can be computed either in-process
right after a run, or later from disk against saved trajectory files
without re-importing dataclasses.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Dict, List


def _attempts_list(trajectory: Dict[str, Any]) -> List[Dict[str, Any]]:
    return trajectory.get("attempts", [])


def compute_metrics(trajectories: List[Dict[str, Any]], max_attempts: int = 5) -> Dict[str, Any]:
    total = len(trajectories)
    if total == 0:
        return {"total_problems": 0}

    first_attempt_successes = 0
    final_successes = 0
    attempts_used_solved: List[int] = []
    timeout_count = 0
    malformed_candidate_count = 0
    duplicate_count = 0
    total_verifier_runtime = 0.0
    success_after: Counter = Counter()  # success_after_attempt_N -> cumulative count

    for traj in trajectories:
        attempts = _attempts_list(traj)
        solved = bool(traj.get("solved", False))
        solved_at: int | None = None

        for a in attempts:
            v = a.get("verification", {})
            status = v.get("status")
            if status == "TIMEOUT":
                timeout_count += 1
            if status == "MALFORMED_CANDIDATE":
                malformed_candidate_count += 1
            if a.get("duplicate"):
                duplicate_count += 1
            total_verifier_runtime += float(v.get("runtime_seconds", 0.0) or 0.0)
            if v.get("verified") and solved_at is None:
                solved_at = a.get("attempt")

        if solved and solved_at is not None:
            final_successes += 1
            attempts_used_solved.append(solved_at)
            if solved_at == 1:
                first_attempt_successes += 1

    for n in range(1, max_attempts + 1):
        success_after[n] = sum(1 for a in attempts_used_solved if a <= n)

    metrics: Dict[str, Any] = {
        "total_problems": total,
        "first_attempt_successes": first_attempt_successes,
        "final_successes": final_successes,
        "first_attempt_success_rate": round(first_attempt_successes / total, 4),
        "final_success_rate": round(final_successes / total, 4),
        "average_attempts": (
            round(statistics.mean(attempts_used_solved), 4) if attempts_used_solved else None
        ),
        "median_attempts": (
            round(statistics.median(attempts_used_solved), 4) if attempts_used_solved else None
        ),
        "timeout_count": timeout_count,
        "malformed_candidate_count": malformed_candidate_count,
        "duplicate_count": duplicate_count,
        "total_verifier_runtime_seconds": round(total_verifier_runtime, 4),
    }
    for n in range(1, max_attempts + 1):
        metrics[f"success_after_attempt_{n}"] = success_after[n]

    return metrics


def format_metrics_report(metrics: Dict[str, Any]) -> str:
    if metrics.get("total_problems", 0) == 0:
        return "No trajectories to report on."
    lines = [
        f"Problems: {metrics['total_problems']}",
        "",
        f"First-attempt success: {metrics['first_attempt_successes']}/{metrics['total_problems']}"
        f"  ({metrics['first_attempt_success_rate']:.1%})",
        f"Final success:         {metrics['final_successes']}/{metrics['total_problems']}"
        f"  ({metrics['final_success_rate']:.1%})",
        f"Average attempts (solved only): {metrics['average_attempts']}",
        f"Median attempts (solved only):  {metrics['median_attempts']}",
        f"Timeouts: {metrics['timeout_count']}",
        f"Malformed candidates: {metrics['malformed_candidate_count']}",
        f"Duplicate candidates: {metrics['duplicate_count']}",
        f"Total verifier runtime: {metrics['total_verifier_runtime_seconds']:.2f}s",
        "",
        "Cumulative success by attempt:",
    ]
    n = 1
    while f"success_after_attempt_{n}" in metrics:
        lines.append(f"  after attempt {n}: {metrics[f'success_after_attempt_{n}']}")
        n += 1
    return "\n".join(lines)
