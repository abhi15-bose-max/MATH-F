"""Robust Lean 4 execution layer (spec section 8/9).

`run_lean` is the ONLY place in the codebase allowed to decide PASS/FAIL --
this is the "Lean is the authority" boundary (spec section 7). It never
infers correctness from anything other than the Lean toolchain's own exit
code and diagnostics (including catching the `sorry` loophole: a proof that
compiles only because it admits `sorry` is not verified).

Candidate-level failures (Lean rejects the proof, or it times out) are
returned as a normal structured result so the repair loop can continue.
Infrastructure-level failures (Lean/Lake missing, the verifier itself
cannot even run) raise `LeanInfrastructureError`, which callers must treat
as a run-abort condition (spec section 23).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional, TypedDict

from .diagnostics import classify_failure, parse_diagnostics, uses_sorry


class LeanVerifierResult(TypedDict, total=False):
    status: str  # "PASS" | "FAIL"
    verifier: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    diagnostics: List[dict]
    failure_class: Optional[str]
    timed_out: bool
    duration_ms: int


class LeanInfrastructureError(RuntimeError):
    """Raised when the Lean toolchain itself cannot be used to verify a
    candidate at all (as opposed to rejecting the candidate).

    `retryable=False` marks conditions that will not resolve themselves
    (e.g. the executable is simply missing) and should abort the run
    immediately. `retryable=True` marks a single anomalous failure that
    should only abort the run after it repeats
    `verification.max_consecutive_infra_failures` times in a row.
    """

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def _build_source(header: str, candidate: str) -> str:
    header = (header or "").rstrip()
    candidate = (candidate or "").rstrip()
    if header:
        return f"{header}\n\n{candidate}\n"
    return f"{candidate}\n"


def run_lean(
    header: str,
    candidate: str,
    lean_cmd: List[str],
    lean_project_dir: str,
    timeout_seconds: int,
) -> LeanVerifierResult:
    exe = lean_cmd[0] if lean_cmd else "lean"
    if shutil.which(exe) is None:
        raise LeanInfrastructureError(
            f"Lean executable '{exe}' not found on PATH. Install the Lean/Lake "
            "toolchain (see README) or verify LEAN_PROJECT_DIR / verification.lean_cmd.",
            retryable=False,
        )

    try:
        tmp_dir = tempfile.mkdtemp(prefix="math_f_verify_")
    except OSError as e:
        raise LeanInfrastructureError(f"Could not create a temp directory for verification: {e}", retryable=True)

    try:
        source_path = Path(tmp_dir) / "candidate.lean"
        try:
            source_path.write_text(_build_source(header, candidate), encoding="utf-8")
        except OSError as e:
            raise LeanInfrastructureError(f"Could not write candidate Lean file: {e}", retryable=True)

        cmd = list(lean_cmd) + [str(source_path)]
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=lean_project_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as e:
            raise LeanInfrastructureError(
                f"Lean executable could not be invoked ({cmd[0]}): {e}", retryable=False
            )
        except subprocess.TimeoutExpired:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return LeanVerifierResult(
                status="FAIL",
                verifier="lean",
                exit_code=None,
                stdout="",
                stderr=f"Verification exceeded {timeout_seconds}s and was terminated.",
                diagnostics=[],
                failure_class="timeout",
                timed_out=True,
                duration_ms=duration_ms,
            )
        except OSError as e:
            # A single anomalous subprocess-launch failure -- track as a
            # retryable infra issue rather than an immediate hard abort.
            raise LeanInfrastructureError(f"OS error while invoking Lean: {e}", retryable=True)

        duration_ms = int((time.perf_counter() - started) * 1000)
        diagnostics = parse_diagnostics(proc.stdout + "\n" + proc.stderr)
        candidate_uses_sorry = uses_sorry(diagnostics, proc.stdout, proc.stderr)
        status = "PASS" if (proc.returncode == 0 and not candidate_uses_sorry) else "FAIL"

        result: LeanVerifierResult = LeanVerifierResult(
            status=status,
            verifier="lean",
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            diagnostics=diagnostics,
            timed_out=False,
            duration_ms=duration_ms,
        )
        result["failure_class"] = classify_failure(result) if status == "FAIL" else None
        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
