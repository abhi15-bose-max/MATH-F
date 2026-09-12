"""
MockLeanVerifier: an offline test double. THIS IS NOT A FORMAL VERIFIER.

Purpose
-------
Building and querying a real Lean 4 + Mathlib toolchain requires network
access (to fetch elan/Lean/Mathlib) and, even then, a non-trivial amount
of time (a full Mathlib build/cache download). Two consequences follow:

  1. Unit tests for the *orchestration* logic (retry loop, duplicate
     detection, trajectory logging, metrics, failure analysis) should
     not require a real Lean install -- that would make `python -m
     unittest` slow and environment-dependent for something that has
     nothing to do with Lean itself.
  2. The environment that produced this repository has NO network
     access at all (see README.md "Known Limitations"), so real Lean
     verification could not be executed or demonstrated here.

`MockLeanVerifier` exists to make both of those honest rather than
silently papering over them. It implements the exact same
`FormalVerifier` interface as `LeanVerifier`, so the rest of the
framework (runner, trajectory logging, metrics, failure analysis)
runs completely unmodified against it -- but it does NOT check
mathematical correctness. It decides "verified" by simple, fully
deterministic pattern matching against `problem.metadata`, not by
calling Lean.

`experiments/run_v1.py` refuses to describe a run using this verifier
as a real verification result: it labels output with
`"verifier_is_mock": true` and the CLI requires an explicit
`--allow-mock` flag, precisely so mock results can never be silently
mistaken for real Lean verification (MASTER PROMPT section 29:
use careful, non-overclaiming language).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from mathf.core.interfaces import FormalVerifier
from mathf.core.models import (
    Candidate,
    FormalMathProblem,
    VerificationResult,
    VerificationStatus,
    VerifierError,
)


class MockLeanVerifier(FormalVerifier):
    name = "mock_lean_v0"

    def __init__(self, simulated_runtime_seconds: float = 0.01):
        self.simulated_runtime_seconds = simulated_runtime_seconds

    def verify(self, problem: FormalMathProblem, candidate: Candidate) -> VerificationResult:
        malformed = candidate.validate()
        if malformed:
            return VerificationResult(
                verified=False,
                status=VerificationStatus.MALFORMED_CANDIDATE,
                errors=[],
                runtime_seconds=0.0,
                verifier=self.name,
                verifier_metadata={"reason": "candidate failed schema validation", "mock": True},
            )

        proof = candidate.proof.strip()
        meta: Dict[str, Any] = problem.metadata or {}

        if meta.get("simulate_timeout_for_tactics") and any(
            t in proof for t in meta["simulate_timeout_for_tactics"]
        ):
            return VerificationResult(
                verified=False,
                status=VerificationStatus.TIMEOUT,
                errors=[],
                runtime_seconds=self.simulated_runtime_seconds,
                verifier=self.name,
                verifier_metadata={"mock": True, "reason": "simulated timeout"},
            )

        accepted = set(meta.get("accepted_tactics", []))
        tactic = proof[3:].strip() if proof.startswith("by ") else proof

        if "sorry" in proof:
            return VerificationResult(
                verified=False,
                status=VerificationStatus.TACTIC_FAILURE,
                errors=[VerifierError(message="proof relies on 'sorry' (mock)")],
                runtime_seconds=self.simulated_runtime_seconds,
                verifier=self.name,
                verifier_metadata={"mock": True},
            )

        if tactic in accepted:
            return VerificationResult(
                verified=True,
                status=VerificationStatus.VERIFIED,
                errors=[],
                runtime_seconds=self.simulated_runtime_seconds,
                verifier=self.name,
                verifier_metadata={"mock": True},
            )

        return VerificationResult(
            verified=False,
            status=VerificationStatus.TACTIC_FAILURE,
            errors=[VerifierError(message=f"(mock) tactic '{tactic}' does not close the goal")],
            runtime_seconds=self.simulated_runtime_seconds,
            verifier=self.name,
            verifier_metadata={"mock": True},
        )
