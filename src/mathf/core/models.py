"""
Core data models for MATH-F.

These dataclasses define the generic contracts that flow between
the dataset, the candidate generator, and the formal verifier. No
class in this module knows anything about *how* a proof is produced
(tactic search, ATP, LLM, ...) or *how* it is checked (Lean, in the
future possibly other systems) -- they are plain data.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Problem representation
# ---------------------------------------------------------------------------


@dataclass
class FormalMathProblem:
    """A single formal mathematics problem.

    The orchestration system depends on nothing beyond this interface,
    regardless of which dataset the problem originated from (the small
    hand-written V1 development benchmark, miniF2F, or a future custom
    dataset).
    """

    problem_id: str
    informal_statement: str
    lean_statement: str
    source: str = "unknown"
    difficulty: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        """Return a list of validation problems (empty == valid)."""
        errors = []
        if not self.problem_id or not isinstance(self.problem_id, str):
            errors.append("problem_id must be a non-empty string")
        if not self.informal_statement or not isinstance(self.informal_statement, str):
            errors.append("informal_statement must be a non-empty string")
        if not self.lean_statement or not isinstance(self.lean_statement, str):
            errors.append("lean_statement must be a non-empty string")
        if not isinstance(self.source, str):
            errors.append("source must be a string")
        if self.difficulty is not None and not isinstance(self.difficulty, str):
            errors.append("difficulty must be a string or null")
        if not isinstance(self.metadata, dict):
            errors.append("metadata must be an object")
        return errors

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormalMathProblem":
        known = {
            "problem_id",
            "informal_statement",
            "lean_statement",
            "source",
            "difficulty",
            "metadata",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        # anything unexpected is preserved in metadata rather than dropped
        extra = {k: v for k, v in data.items() if k not in known}
        if extra:
            kwargs.setdefault("metadata", {})
            kwargs["metadata"] = {**extra, **kwargs.get("metadata", {})}
        return cls(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Candidate representation
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """A single candidate proof produced by a CandidateGenerator.

    `proof` is whatever text the generator produced: a complete Lean
    proof term, a full `theorem ... := by ...` block, a bare tactic
    block, or another artifact the verifier knows how to turn into a
    checkable Lean file. The orchestration layer never inspects the
    contents of `proof`; only the verifier and generator need to agree
    on its shape.
    """

    problem_id: str
    generator: str
    attempt: int
    proof: str
    method: Optional[str] = None
    search_time_seconds: Optional[float] = None
    search_parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        errors = []
        if not self.problem_id:
            errors.append("problem_id must be non-empty")
        if not self.generator:
            errors.append("generator must be non-empty")
        if not isinstance(self.attempt, int) or self.attempt < 1:
            errors.append("attempt must be a positive integer")
        if self.proof is None or not isinstance(self.proof, str):
            errors.append("proof must be a string")
        elif self.proof.strip() == "":
            errors.append("proof must not be empty/whitespace-only")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Verification result representation
# ---------------------------------------------------------------------------


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PROOF_ERROR = "PROOF_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    UNKNOWN_IDENTIFIER = "UNKNOWN_IDENTIFIER"
    TACTIC_FAILURE = "TACTIC_FAILURE"
    TIMEOUT = "TIMEOUT"
    VERIFIER_ERROR = "VERIFIER_ERROR"
    MALFORMED_CANDIDATE = "MALFORMED_CANDIDATE"
    UNKNOWN = "UNKNOWN"


@dataclass
class VerifierError:
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    raw: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    """The structured outcome of running the formal verifier on a candidate.

    `verified` is the single authoritative boolean. `status` gives a
    best-effort classification of *why* (see VerificationStatus) but the
    classification is never used to override `verified` -- it exists
    purely to support failure analysis and is not treated as ground
    truth about mathematical correctness.
    """

    verified: bool
    status: VerificationStatus
    errors: List[VerifierError] = field(default_factory=list)
    runtime_seconds: float = 0.0
    raw_stdout: str = ""
    raw_stderr: str = ""
    exit_code: Optional[int] = None
    verifier: str = "unknown"
    verifier_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, VerificationStatus) else self.status
        return d


# ---------------------------------------------------------------------------
# Trajectory representation
# ---------------------------------------------------------------------------


@dataclass
class Attempt:
    attempt: int
    candidate: Candidate
    verification: VerificationResult
    duplicate: bool = False
    duplicate_of_attempt: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt": self.attempt,
            "candidate": self.candidate.to_dict(),
            "verification": self.verification.to_dict(),
            "duplicate": self.duplicate,
            "duplicate_of_attempt": self.duplicate_of_attempt,
        }


@dataclass
class Trajectory:
    problem_id: str
    generator: str
    verifier: str
    configuration: Dict[str, Any]
    trajectory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    attempts: List[Attempt] = field(default_factory=list)
    final_status: VerificationStatus = VerificationStatus.UNKNOWN
    attempts_used: int = 0
    solved: bool = False

    def add_attempt(self, attempt: Attempt) -> None:
        self.attempts.append(attempt)
        self.attempts_used = len(self.attempts)
        if attempt.verification.verified:
            self.solved = True
            self.final_status = VerificationStatus.VERIFIED
        elif not self.solved:
            # keep the *last* observed status while unsolved
            self.final_status = attempt.verification.status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "problem_id": self.problem_id,
            "generator": self.generator,
            "verifier": self.verifier,
            "created_at": self.created_at,
            "configuration": self.configuration,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_status": (
                self.final_status.value
                if isinstance(self.final_status, VerificationStatus)
                else self.final_status
            ),
            "attempts_used": self.attempts_used,
            "solved": self.solved,
        }


# ---------------------------------------------------------------------------
# Experiment configuration
# ---------------------------------------------------------------------------


@dataclass
class ExperimentConfig:
    experiment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dataset_path: str = "datasets/v1/problems.json"
    dataset_version: str = "v1"
    generator_name: str = "fixed_tactic_search"
    verifier_name: str = "lean"
    max_attempts: int = 5
    timeout_seconds: int = 180  # see configs/default.yaml: dominated by Mathlib's cold-import cost
    output_dir: str = "trajectories"
    results_dir: str = "results"
    random_seed: Optional[int] = 0
    lean_project_dir: str = "lean_project"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
