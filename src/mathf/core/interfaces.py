"""
Generic interfaces for MATH-F.

These abstract base classes are the ONLY contract the orchestration
layer (core.runner) depends on. They contain no assumptions about:

  - what kind of algorithm produces a candidate (tactic search, ATP,
    SMT, symbolic method, neural theorem prover, LLM, SLM, hybrid, or
    something invented later), or
  - what formal system checks it (V1 uses Lean 4 + Mathlib; the
    interface itself says nothing about Lean).

Two calling conventions are supported for generators (see
`CandidateGenerator` docstring) because not every generator can
usefully consume feedback -- some just run an internal search process
and hand back successive candidates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from mathf.core.models import Candidate, FormalMathProblem, VerificationResult


class CandidateGenerator(ABC):
    """Produces candidate proofs for a FormalMathProblem.

    Contract:

        generate(problem, attempt_number, context) -> Candidate

    `context` is an optional dict that MAY contain feedback from a
    previous failed attempt on the same problem (see
    `mathf.core.runner.build_feedback_context`). A generator is free to
    ignore `context` entirely -- nothing in the orchestration layer
    requires feedback-aware generation (see MASTER PROMPT sections 12-14).

    A generator may also maintain purely internal state (e.g. an
    internal proof-search frontier) keyed by problem_id, in which case
    `context` is irrelevant and each call simply returns the generator's
    next internal candidate.
    """

    #: short machine-readable name recorded on every candidate/trajectory
    name: str = "unnamed_generator"

    @abstractmethod
    def generate(
        self,
        problem: FormalMathProblem,
        attempt_number: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> Candidate:
        """Return a single Candidate for the given attempt number.

        Implementations MUST NOT raise for "no more ideas" -- instead
        return a Candidate whose `proof` is something the verifier will
        reject (e.g. the previous best-effort candidate again, or a
        `sorry`), or set `metadata["exhausted"] = True`. The runner uses
        `metadata["exhausted"]` as an optional early-stop hint but never
        requires it.
        """
        raise NotImplementedError

    def reset(self) -> None:
        """Clear any internal state. Called between problems if a
        generator instance is reused across a dataset. Default is a
        no-op; stateful generators should override this."""
        return None


class FormalVerifier(ABC):
    """Independently determines whether a Candidate proves a Problem.

    Contract:

        verify(problem, candidate) -> VerificationResult

    The verifier is the single source of truth for correctness. Nothing
    upstream (the generator, the runner, or any heuristic) is permitted
    to override `VerificationResult.verified`.
    """

    #: short machine-readable name recorded on every result/trajectory
    name: str = "unnamed_verifier"

    @abstractmethod
    def verify(self, problem: FormalMathProblem, candidate: Candidate) -> VerificationResult:
        raise NotImplementedError
