"""
LeanVerifier: the V1 formal verification backend.

This is the single source of truth for "is this proof correct". It
shells out to a real Lean 4 toolchain (via `lake env lean`) against a
pre-built Lake project that depends on Mathlib (see
`lean_project/README.md`), so the full Mathlib library is in scope for
every candidate.

IMPORTANT / HONESTLY STATED LIMITATION
---------------------------------------
This class has been written to the real `lake env lean` /
`lean --stdin` calling convention and is exercised by unit tests with
a *stubbed* subprocess (see tests/test_verifier.py), but it has NOT
been run against a real Lean+Mathlib installation in the environment
that produced this repository, because that environment has no
network access (no way to fetch elan, the Lean toolchain, or Mathlib).
It MUST be validated the first time you run it in an environment with
network access (e.g. the provided Colab notebook) -- see
notebooks/MATH_F_V1_demo.ipynb, which does exactly that as its first
executable steps. See README.md "Known Limitations" for details.

Verification protocol
----------------------
1. Assemble a complete `.lean` source file:

       <imports>
       set_option maxHeartbeats <n>

       <problem.lean_statement> := <candidate.proof>

   `problem.lean_statement` is expected to be a complete theorem
   header up to (but not including) `:=`, e.g.:

       theorem mathf_001 : (2 : Nat) + 2 = 4

   `candidate.proof` is appended directly after `:=`, e.g. `by decide`
   or a full term-mode proof.

2. Write it to a scratch file inside the Lake project so `import
   Mathlib` resolves against the project's built dependency, and run:

       lake env lean <scratch_file.lean>

   inside `lean_project_dir`, with a wall-clock timeout.

3. exit_code == 0 AND no "declaration uses 'sorry'" diagnostic
   => VERIFIED. Any other outcome is a failure, classified
   best-effort by `verifiers.base.classify_lean_output`.

   Treating a successful-but-`sorry`-containing compile as NOT verified
   is a deliberate, important safeguard: Lean happily accepts `sorry`
   as a placeholder proof with exit code 0, so checking exit code alone
   would silently accept incomplete proofs as "VERIFIED".
"""

from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Optional

from mathf.core.interfaces import FormalVerifier
from mathf.core.models import (
    Candidate,
    FormalMathProblem,
    VerificationResult,
    VerificationStatus,
)
from mathf.verifiers.base import classify_lean_output, contains_sorry_warning, extract_errors

DEFAULT_IMPORTS = "import Mathlib\n"
DEFAULT_MAX_HEARTBEATS = 400000  # generous budget for Mathlib-heavy tactics like `simp`/`aesop`


class LeanVerifier(FormalVerifier):
    name = "lean4_mathlib"

    def __init__(
        self,
        lean_project_dir: str,
        timeout_seconds: int = 180,  # see configs/default.yaml: dominated by Mathlib's cold-import cost
        imports: str = DEFAULT_IMPORTS,
        max_heartbeats: int = DEFAULT_MAX_HEARTBEATS,
        keep_scratch_files: bool = True,
        lean_binary: str = "lean",
        lake_binary: str = "lake",
    ):
        self.lean_project_dir = Path(lean_project_dir)
        self.timeout_seconds = timeout_seconds
        self.imports = imports
        self.max_heartbeats = max_heartbeats
        self.keep_scratch_files = keep_scratch_files
        self.lean_binary = lean_binary
        self.lake_binary = lake_binary
        self.scratch_dir = self.lean_project_dir / "Scratch"

    # -- source assembly -----------------------------------------------

    def build_source(self, problem: FormalMathProblem, candidate: Candidate) -> str:
        statement = problem.lean_statement.rstrip()
        proof = candidate.proof.strip()
        return (
            f"{self.imports}"
            f"set_option maxHeartbeats {self.max_heartbeats}\n\n"
            f"{statement} := {proof}\n"
        )

    def _scratch_path(self, problem: FormalMathProblem, candidate: Candidate) -> Path:
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{problem.problem_id}_attempt{candidate.attempt}_{uuid.uuid4().hex[:8]}.lean"
        return self.scratch_dir / fname

    # -- main entry point -------------------------------------------------

    def verify(self, problem: FormalMathProblem, candidate: Candidate) -> VerificationResult:
        malformed = candidate.validate()
        if malformed:
            return VerificationResult(
                verified=False,
                status=VerificationStatus.MALFORMED_CANDIDATE,
                errors=[],
                runtime_seconds=0.0,
                raw_stdout="",
                raw_stderr="; ".join(malformed),
                exit_code=None,
                verifier=self.name,
                verifier_metadata={"reason": "candidate failed schema validation"},
            )

        source = self.build_source(problem, candidate)
        scratch_path = self._scratch_path(problem, candidate)
        scratch_path.write_text(source, encoding="utf-8")

        cmd = [self.lake_binary, "env", self.lean_binary, str(scratch_path.resolve())]
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.lean_project_dir),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            runtime = time.time() - start
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            runtime = time.time() - start
            return VerificationResult(
                verified=False,
                status=VerificationStatus.TIMEOUT,
                errors=[],
                runtime_seconds=runtime,
                raw_stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
                raw_stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
                exit_code=None,
                verifier=self.name,
                verifier_metadata={
                    "timeout_seconds": self.timeout_seconds,
                    "lean_source_path": str(scratch_path),
                    "note": "verifier execution did not complete within budget; "
                    "this is NOT a claim that the proof is mathematically wrong",
                },
            )
        except FileNotFoundError as e:
            runtime = time.time() - start
            return VerificationResult(
                verified=False,
                status=VerificationStatus.VERIFIER_ERROR,
                errors=[],
                runtime_seconds=runtime,
                raw_stdout="",
                raw_stderr=str(e),
                exit_code=None,
                verifier=self.name,
                verifier_metadata={
                    "reason": "lean/lake binary not found; is the Lean toolchain installed and on PATH?",
                    "lean_source_path": str(scratch_path),
                },
            )
        finally:
            if not self.keep_scratch_files:
                try:
                    scratch_path.unlink(missing_ok=True)
                except Exception:
                    pass

        has_sorry = contains_sorry_warning(stdout, stderr)
        verified = (exit_code == 0) and not has_sorry

        if verified:
            status = VerificationStatus.VERIFIED
            errors: List = []
        elif exit_code == 0 and has_sorry:
            # Lean happily exits 0 on a `sorry`-completed proof; without this
            # branch that would be misreported as VERIFIED.
            status = VerificationStatus.TACTIC_FAILURE
            errors = extract_errors(stdout, stderr)
            if not errors:
                from mathf.core.models import VerifierError

                errors = [VerifierError(message="proof compiled but relies on 'sorry' (incomplete proof)")]
        else:
            status = classify_lean_output(stdout, stderr)
            errors = extract_errors(stdout, stderr)

        return VerificationResult(
            verified=verified,
            status=status,
            errors=errors,
            runtime_seconds=runtime,
            raw_stdout=stdout,
            raw_stderr=stderr,
            exit_code=exit_code,
            verifier=self.name,
            verifier_metadata={
                "lean_source_path": str(scratch_path),
                "lean_source": source,
                "contains_sorry": has_sorry,
                "command": cmd,
            },
        )

    # -- environment sanity check -----------------------------------------

    def check_environment(self) -> VerificationResult:
        """Run a trivial `#eval 1 + 1` sanity check against this Lean
        project, independent of any benchmark problem. Used by the
        notebook and by `experiments/run_v1.py --check-lean` to fail
        fast with a clear message if Lean/Mathlib are not correctly
        installed, rather than surfacing confusing VERIFIER_ERROR
        results across an entire benchmark run."""
        dummy_problem = FormalMathProblem(
            problem_id="__env_check__",
            informal_statement="Environment sanity check.",
            lean_statement="theorem __env_check__ : (1 : Nat) + 1 = 2",
            source="internal",
        )
        dummy_candidate = Candidate(
            problem_id="__env_check__", generator="internal", attempt=1, proof="by decide"
        )
        return self.verify(dummy_problem, dummy_candidate)
