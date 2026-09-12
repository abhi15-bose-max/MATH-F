"""
ExperimentRunner: the generic retry/search loop.

    problem -> generator.generate() -> candidate -> verifier.verify()
        -> result -> [PASS: finish] / [FAIL: feedback -> next candidate]

This is the only place in the codebase that coordinates a
CandidateGenerator with a FormalVerifier. It depends on nothing beyond
the abstract interfaces in `mathf.core.interfaces`, so swapping either
component (a different tactic search, an ATP-backed generator, an AI
generator, or in principle a different verifier) requires no changes
here (MASTER PROMPT section 31, "architectural invariant").
"""

from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from mathf.core.interfaces import CandidateGenerator, FormalVerifier
from mathf.core.models import (
    Attempt,
    ExperimentConfig,
    FormalMathProblem,
    Trajectory,
    VerificationResult,
)
from mathf.logging.trajectory import DuplicateTracker, save_trajectory


def build_feedback_context(previous_attempt: Optional[Attempt]) -> Dict[str, Any]:
    """Build the `context` dict passed to `generator.generate()`.

    Generators are never required to use this (MASTER PROMPT section
    13: "Do not require feedback-aware generation in V1") but the
    shape is defined once, here, so future feedback-consuming
    generators have a stable contract to target.
    """
    if previous_attempt is None:
        return {}
    v = previous_attempt.verification
    return {
        "previous_attempt_number": previous_attempt.attempt,
        "previous_proof": previous_attempt.candidate.proof,
        "previous_status": v.status.value if hasattr(v.status, "value") else v.status,
        "previous_verified": v.verified,
        "previous_errors": [e.to_dict() if hasattr(e, "to_dict") else e for e in v.errors],
    }


class ExperimentRunner:
    def __init__(
        self,
        generator: CandidateGenerator,
        verifier: FormalVerifier,
        config: ExperimentConfig,
    ):
        self.generator = generator
        self.verifier = verifier
        self.config = config

    def run_problem(self, problem: FormalMathProblem) -> Trajectory:
        self.generator.reset()
        dup_tracker = DuplicateTracker()

        trajectory = Trajectory(
            problem_id=problem.problem_id,
            generator=self.generator.name,
            verifier=self.verifier.name,
            configuration={
                "max_attempts": self.config.max_attempts,
                "timeout_seconds": self.config.timeout_seconds,
            },
        )

        previous_attempt: Optional[Attempt] = None
        cached_results: Dict[int, VerificationResult] = {}

        for attempt_number in range(1, self.config.max_attempts + 1):
            context = build_feedback_context(previous_attempt)
            candidate = self.generator.generate(problem, attempt_number, context)

            duplicate_of = dup_tracker.check_and_record(attempt_number, candidate.proof)

            if duplicate_of is not None:
                # Exact duplicate of an earlier attempt in THIS trajectory:
                # the verifier is deterministic, so re-running it would
                # burn a Lean invocation for no new information. Reuse the
                # earlier structured result but always record the attempt
                # (MASTER PROMPT section 17: never silently discard).
                result = copy.deepcopy(cached_results[duplicate_of])
            else:
                result = self.verifier.verify(problem, candidate)
                cached_results[attempt_number] = result

            attempt = Attempt(
                attempt=attempt_number,
                candidate=candidate,
                verification=result,
                duplicate=duplicate_of is not None,
                duplicate_of_attempt=duplicate_of,
            )
            trajectory.add_attempt(attempt)
            previous_attempt = attempt

            if result.verified:
                break

            # Optional early-stop hint: a generator may signal it has no
            # more distinct ideas. This never overrides max_attempts as
            # the authoritative ceiling; it only avoids wasted verifier
            # calls once the generator has provably run out of options.
            if candidate.metadata.get("exhausted") and duplicate_of is None:
                # try once more only if the *next* candidate would differ;
                # a generator reporting exhausted with a fresh (non-duplicate)
                # candidate just means "this was my last idea" -- stop here.
                break

        return trajectory

    def run_dataset(
        self, problems: List[FormalMathProblem], save: bool = True
    ) -> List[Trajectory]:
        trajectories = []
        for problem in problems:
            traj = self.run_problem(problem)
            if save:
                save_trajectory(traj, self.config.output_dir)
            trajectories.append(traj)
        return trajectories
