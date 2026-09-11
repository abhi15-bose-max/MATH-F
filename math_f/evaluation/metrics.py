"""Core evaluation metrics (spec sections 16/17/33).

Every number here is recomputed directly from the raw per-attempt and
per-task trajectory files on disk -- nothing is cached or trusted from a
previous summary, so `stats` always reflects ground truth (spec section 34:
"every number must be traceable back to the raw attempt-level trajectory
files").

The single most important distinction implemented here (spec section 17):

  * `exact_attempt_distribution[k]`  = number of tasks whose FIRST passing
                                        attempt was exactly attempt k.
  * `cumulative_success_by_attempt[k]` = fraction of tasks solved WITHIN
                                        the first k attempts (<=k).

These are different quantities and must never be confused.
"""
from __future__ import annotations

import statistics
from collections import Counter
from typing import Optional

from math_f.trajectories.loader import (
    iter_attempt_records,
    iter_final_records,
    list_abort_events,
)


def compute_metrics(run_dir, max_attempts: Optional[int] = None) -> dict:
    finals = list(iter_final_records(run_dir))
    attempts = list(iter_attempt_records(run_dir))
    abort_events = list_abort_events(run_dir)

    verified = [f for f in finals if f.get("final_status") == "VERIFIED"]
    abstained = [f for f in finals if f.get("final_status") == "ABSTAIN"]

    malformed_events = [e for e in abort_events if e.get("kind") == "malformed_candidate"]
    infra_events = [e for e in abort_events if e.get("kind") == "infrastructure_error"]

    if max_attempts is None:
        max_attempts = max(
            [f.get("max_attempts", 0) for f in finals] + [0]
        ) or 5

    total_tasks = len(verified) + len(abstained)

    # -- exact attempt distribution & cumulative success -------------------
    exact_attempt_distribution = {k: 0 for k in range(1, max_attempts + 1)}
    for f in verified:
        k = f.get("success_on_attempt")
        if k in exact_attempt_distribution:
            exact_attempt_distribution[k] += 1

    cumulative_success_by_attempt = {}
    running = 0
    for k in range(1, max_attempts + 1):
        running += exact_attempt_distribution.get(k, 0)
        cumulative_success_by_attempt[k] = (running / total_tasks) if total_tasks else 0.0

    attempts_to_success = [
        f["success_on_attempt"] for f in verified if f.get("success_on_attempt") is not None
    ]
    mean_attempts_to_success = statistics.fmean(attempts_to_success) if attempts_to_success else None
    median_attempts_to_success = statistics.median(attempts_to_success) if attempts_to_success else None

    # -- failure classification, aggregated over every attempt -------------
    failure_class_counts = Counter()
    for a in attempts:
        v = a.get("verification") or {}
        fc = v.get("failure_class")
        if fc and v.get("status") != "PASS":
            failure_class_counts[fc] += 1

    # -- runtime / token totals ---------------------------------------------
    total_generation_tokens = 0
    total_input_tokens = 0
    total_generation_time_s = 0.0
    total_verification_time_s = 0.0
    for a in attempts:
        rt = a.get("runtime") or {}
        total_generation_tokens += rt.get("output_tokens") or 0
        total_input_tokens += rt.get("input_tokens") or 0
        total_generation_time_s += (rt.get("generation_latency_ms") or 0) / 1000.0
        total_verification_time_s += (rt.get("verification_latency_ms") or 0) / 1000.0

    return {
        "total_tasks": total_tasks,
        "verified_tasks": len(verified),
        "failed_tasks": len(abstained),  # alias of abstained_tasks in this design
        "abstained_tasks": len(abstained),
        "aborted_tasks": len(malformed_events) + len(infra_events),
        "max_attempts": max_attempts,
        "exact_attempt_distribution": {
            f"success_on_attempt_{k}": v for k, v in exact_attempt_distribution.items()
        },
        "cumulative_success_by_attempt": {
            f"cumulative_success_{k}_shot": v for k, v in cumulative_success_by_attempt.items()
        },
        "mean_attempts_to_success": mean_attempts_to_success,
        "median_attempts_to_success": median_attempts_to_success,
        "failure_class_counts": dict(failure_class_counts),
        "malformed_output_count": len(malformed_events),
        "infrastructure_abort_count": len(infra_events),
        "total_generation_tokens": total_generation_tokens,
        "total_input_tokens": total_input_tokens,
        "total_generation_time_seconds": round(total_generation_time_s, 3),
        "total_verification_time_seconds": round(total_verification_time_s, 3),
        "total_attempts_logged": len(attempts),
    }
