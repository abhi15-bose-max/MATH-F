"""The bounded generate -> clean -> verify -> repair loop (spec section 10).

Three distinct outcomes are modeled, and only one of them is a run-wide
abort:

  * VERIFIED   -- Lean accepted a candidate. Normal success.
  * ABSTAIN    -- every attempt was a valid-but-wrong candidate (or a
                  duplicate candidate was detected), attempts were
                  exhausted. Normal experimental failure. Evaluation
                  continues to the next task.
  * ABORTED    -- the model produced protocol-malformed output that could
                  not be deterministically turned into a candidate at all.
                  This is NOT a normal failure (spec section 5): it is
                  raised as `MalformedOutputAbort` and must stop the entire
                  evaluation run, not just this task.

Infrastructure failures (Lean missing, etc.) are not caught here at all --
`LeanInfrastructureError` from the verifier propagates straight through
`run_task` to the caller, which must also treat that as a run-abort
condition (spec section 23).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from math_f.generation.generator import CandidateGenerator
from math_f.verification.lean_runner import LeanVerifierResult, run_lean
from . import prompts


class MalformedOutputAbort(Exception):
    """Raised when the model produces protocol-malformed output.

    Carries everything the caller needs to log a CRITICAL message and stop
    the run without re-deriving state.
    """

    def __init__(self, trajectory_id: str, task_id: str, attempt: int, reason: str, attempt_record: dict):
        super().__init__(
            f"Malformed candidate for trajectory {trajectory_id} (task {task_id}) "
            f"on attempt {attempt}: {reason}"
        )
        self.trajectory_id = trajectory_id
        self.task_id = task_id
        self.attempt = attempt
        self.reason = reason
        self.attempt_record = attempt_record


@dataclass
class TaskOutcome:
    trajectory_id: str
    task_id: str
    final_status: str  # "VERIFIED" | "ABSTAIN"
    success: bool
    success_on_attempt: Optional[int]
    attempts_used: int
    max_attempts: int
    abort_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory_id,
            "task_id": self.task_id,
            "final_status": self.final_status,
            "success": self.success,
            "success_on_attempt": self.success_on_attempt,
            "attempts_used": self.attempts_used,
            "max_attempts": self.max_attempts,
            "abort_reason": self.abort_reason,
        }


_EMPTY_VERIFICATION = {
    "status": "FAIL",
    "verifier": "lean",
    "exit_code": None,
    "stdout": "",
    "stderr": "",
    "diagnostics": [],
}


class RepairLoop:
    def __init__(
        self,
        model,
        model_meta: dict,
        max_attempts: int,
        lean_cmd,
        lean_project_dir: str,
        timeout_seconds: int,
        duplicate_detection: bool = True,
        verify_fn: Optional[Callable[..., LeanVerifierResult]] = None,
    ):
        self.generator = CandidateGenerator(model)
        self.model_meta = model_meta
        self.max_attempts = max_attempts
        self.lean_cmd = lean_cmd
        self.lean_project_dir = lean_project_dir
        self.timeout_seconds = timeout_seconds
        self.duplicate_detection = duplicate_detection
        # Injectable for tests; defaults to the real Lean subprocess runner.
        self._verify_fn = verify_fn or run_lean

    def _base_attempt(self, trajectory_id: str, task, attempt_n: int) -> dict:
        return {
            "trajectory_id": trajectory_id,
            "attempt": attempt_n,
            "parent_attempt": attempt_n - 1 if attempt_n > 1 else None,
            "task": {
                "task_id": task.task_id,
                "source": task.source,
                "split": task.split,
            },
            "model": dict(self.model_meta),
            "specification": {
                "theorem_statement": task.theorem_statement,
                "lean_context": task.header,
            },
        }

    def run_task(self, task, trajectory_id: str, on_attempt: Optional[Callable[[dict], None]] = None) -> TaskOutcome:
        previous_candidate: Optional[str] = None
        verifier_result: Optional[dict] = None
        seen_candidates = set()

        for attempt_n in range(1, self.max_attempts + 1):
            task_started = time.perf_counter()

            if attempt_n == 1:
                prompt = prompts.build_initial_prompt(task)
            else:
                prompt = prompts.build_repair_prompt(
                    task, previous_candidate, verifier_result, attempt_n, self.max_attempts
                )

            gen_record = self.generator.generate(prompt)
            attempt_record = self._base_attempt(trajectory_id, task, attempt_n)
            attempt_record["generation"] = gen_record.to_dict()

            if gen_record.cleaning_status in ("MALFORMED", "EMPTY"):
                attempt_record["verification"] = {
                    "status": "ABORTED",
                    "failure_class": "malformed_candidate",
                }
                attempt_record["repair_feedback"] = None
                attempt_record["runtime"] = {
                    "generation_latency_ms": gen_record.generation_latency_ms,
                    "verification_latency_ms": 0,
                    "total_latency_ms": int((time.perf_counter() - task_started) * 1000),
                    "input_tokens": gen_record.input_tokens,
                    "output_tokens": gen_record.output_tokens,
                }
                if on_attempt:
                    on_attempt(attempt_record)
                raise MalformedOutputAbort(
                    trajectory_id=trajectory_id,
                    task_id=task.task_id,
                    attempt=attempt_n,
                    reason=gen_record.cleaning_reason or "no extractable candidate",
                    attempt_record=attempt_record,
                )

            candidate = gen_record.cleaned_candidate

            if self.duplicate_detection and candidate in seen_candidates:
                verification = dict(_EMPTY_VERIFICATION)
                verification["failure_class"] = "duplicate_candidate"
                attempt_record["verification"] = verification
                attempt_record["repair_feedback"] = (
                    "Candidate is identical to a previously rejected candidate; "
                    "stopping this task to avoid an infinite loop."
                )
                attempt_record["runtime"] = {
                    "generation_latency_ms": gen_record.generation_latency_ms,
                    "verification_latency_ms": 0,
                    "total_latency_ms": int((time.perf_counter() - task_started) * 1000),
                    "input_tokens": gen_record.input_tokens,
                    "output_tokens": gen_record.output_tokens,
                }
                if on_attempt:
                    on_attempt(attempt_record)
                return TaskOutcome(
                    trajectory_id=trajectory_id,
                    task_id=task.task_id,
                    final_status="ABSTAIN",
                    success=False,
                    success_on_attempt=None,
                    attempts_used=attempt_n,
                    max_attempts=self.max_attempts,
                )

            seen_candidates.add(candidate)

            verify_started = time.perf_counter()
            verifier_result = self._verify_fn(
                header=task.header,
                candidate=candidate,
                lean_cmd=self.lean_cmd,
                lean_project_dir=self.lean_project_dir,
                timeout_seconds=self.timeout_seconds,
            )
            verify_latency_ms = int((time.perf_counter() - verify_started) * 1000)

            attempt_record["verification"] = dict(verifier_result)
            attempt_record["runtime"] = {
                "generation_latency_ms": gen_record.generation_latency_ms,
                "verification_latency_ms": verify_latency_ms,
                "total_latency_ms": int((time.perf_counter() - task_started) * 1000),
                "input_tokens": gen_record.input_tokens,
                "output_tokens": gen_record.output_tokens,
            }

            if verifier_result["status"] == "PASS":
                attempt_record["repair_feedback"] = None
                if on_attempt:
                    on_attempt(attempt_record)
                return TaskOutcome(
                    trajectory_id=trajectory_id,
                    task_id=task.task_id,
                    final_status="VERIFIED",
                    success=True,
                    success_on_attempt=attempt_n,
                    attempts_used=attempt_n,
                    max_attempts=self.max_attempts,
                )

            attempt_record["repair_feedback"] = (
                prompts.summarize_verifier_result(verifier_result)
                if attempt_n < self.max_attempts
                else None
            )
            if on_attempt:
                on_attempt(attempt_record)

            previous_candidate = candidate
            # verifier_result already set for next loop iteration's repair prompt.

        return TaskOutcome(
            trajectory_id=trajectory_id,
            task_id=task.task_id,
            final_status="ABSTAIN",
            success=False,
            success_on_attempt=None,
            attempts_used=self.max_attempts,
            max_attempts=self.max_attempts,
        )
