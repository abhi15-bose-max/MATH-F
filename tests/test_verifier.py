import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mathf.core.models import Candidate, FormalMathProblem, VerificationStatus
from mathf.verifiers.base import classify_lean_output, contains_sorry_warning, extract_errors
from mathf.verifiers.lean_verifier import LeanVerifier
from mathf.verifiers.mock_verifier import MockLeanVerifier


def make_problem(**metadata):
    return FormalMathProblem(
        problem_id="p1",
        informal_statement="test",
        lean_statement="theorem p1 (a b : Nat) : a + b = b + a",
        source="unit_test",
        metadata=metadata,
    )


class TestClassifyLeanOutput(unittest.TestCase):
    def test_unknown_identifier(self):
        out = "p1.lean:3:10: error: unknown identifier 'foo'"
        self.assertEqual(classify_lean_output(out, ""), VerificationStatus.UNKNOWN_IDENTIFIER)

    def test_unexpected_token_is_syntax_error(self):
        out = "p1.lean:1:5: error: unexpected token ':='; expected term"
        self.assertEqual(classify_lean_output(out, ""), VerificationStatus.SYNTAX_ERROR)

    def test_type_mismatch(self):
        out = "p1.lean:2:2: error: type mismatch\n  rfl"
        self.assertEqual(classify_lean_output(out, ""), VerificationStatus.TYPE_ERROR)

    def test_unsolved_goals_is_tactic_failure(self):
        out = "p1.lean:4:0: error: unsolved goals\n⊢ a + b = b + a"
        self.assertEqual(classify_lean_output(out, ""), VerificationStatus.TACTIC_FAILURE)

    def test_generic_error_falls_back_to_proof_error(self):
        out = "p1.lean:1:1: error: something unclassified went wrong"
        self.assertEqual(classify_lean_output(out, ""), VerificationStatus.PROOF_ERROR)

    def test_no_error_text_is_unknown(self):
        self.assertEqual(classify_lean_output("all good", ""), VerificationStatus.UNKNOWN)

    def test_extract_errors_parses_line_and_column(self):
        out = "Scratch/p1_attempt1.lean:12:4: error: unknown identifier 'bar'"
        errors = extract_errors(out, "")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line, 12)
        self.assertEqual(errors[0].column, 4)
        self.assertIn("unknown identifier", errors[0].message)

    def test_sorry_detection(self):
        self.assertTrue(contains_sorry_warning("", "p1.lean:3:0: warning: declaration uses 'sorry'"))
        self.assertFalse(contains_sorry_warning("all good", ""))


class TestMockLeanVerifier(unittest.TestCase):
    def test_accepted_tactic_verifies(self):
        v = MockLeanVerifier()
        problem = make_problem(accepted_tactics=["ring", "omega"])
        candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by ring")
        result = v.verify(problem, candidate)
        self.assertTrue(result.verified)
        self.assertEqual(result.status, VerificationStatus.VERIFIED)

    def test_unaccepted_tactic_fails(self):
        v = MockLeanVerifier()
        problem = make_problem(accepted_tactics=["ring"])
        candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by decide")
        result = v.verify(problem, candidate)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, VerificationStatus.TACTIC_FAILURE)

    def test_sorry_never_verifies(self):
        v = MockLeanVerifier()
        problem = make_problem(accepted_tactics=["sorry"])  # even if "accepted", sorry must never pass
        candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by sorry")
        result = v.verify(problem, candidate)
        self.assertFalse(result.verified)

    def test_malformed_candidate(self):
        v = MockLeanVerifier()
        problem = make_problem()
        candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="   ")
        result = v.verify(problem, candidate)
        self.assertEqual(result.status, VerificationStatus.MALFORMED_CANDIDATE)
        self.assertFalse(result.verified)

    def test_simulated_timeout(self):
        v = MockLeanVerifier()
        problem = make_problem(accepted_tactics=["ring"], simulate_timeout_for_tactics=["omega"])
        candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by omega")
        result = v.verify(problem, candidate)
        self.assertEqual(result.status, VerificationStatus.TIMEOUT)
        self.assertFalse(result.verified)

    def test_metadata_flags_result_as_mock(self):
        v = MockLeanVerifier()
        problem = make_problem(accepted_tactics=["ring"])
        candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by ring")
        result = v.verify(problem, candidate)
        self.assertTrue(result.verifier_metadata.get("mock"))


class TestLeanVerifierSourceAssembly(unittest.TestCase):
    def test_build_source_shape(self):
        with tempfile.TemporaryDirectory() as d:
            v = LeanVerifier(lean_project_dir=d, timeout_seconds=5)
            problem = make_problem()
            candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by ring")
            source = v.build_source(problem, candidate)
            self.assertIn("import Mathlib", source)
            self.assertIn("theorem p1 (a b : Nat) : a + b = b + a := by ring", source)
            self.assertIn("maxHeartbeats", source)


class TestLeanVerifierWithStubbedSubprocess(unittest.TestCase):
    """LeanVerifier's control flow (source assembly, scratch file writing,
    exit-code/sorry-based verdict, error classification, timeout and
    missing-binary handling) is tested here against a *stubbed*
    subprocess.run, because no real Lean toolchain is available in the
    environment that produced this repository (see README.md 'Known
    Limitations'). This validates the logic; it does not validate that
    real Lean actually accepts the assembled proofs. That must be
    confirmed separately (see notebooks/MATH_F_V1_demo.ipynb)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.verifier = LeanVerifier(lean_project_dir=self._tmpdir.name, timeout_seconds=5)
        self.problem = make_problem()
        self.candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by ring")

    @patch("mathf.verifiers.lean_verifier.subprocess.run")
    def test_successful_compile_is_verified(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        result = self.verifier.verify(self.problem, self.candidate)
        self.assertTrue(result.verified)
        self.assertEqual(result.status, VerificationStatus.VERIFIED)
        self.assertEqual(result.exit_code, 0)

    @patch("mathf.verifiers.lean_verifier.subprocess.run")
    def test_sorry_is_not_verified_even_with_exit_zero(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="p1.lean:1:0: warning: declaration uses 'sorry'", stderr=""
        )
        result = self.verifier.verify(self.problem, self.candidate)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, VerificationStatus.TACTIC_FAILURE)

    @patch("mathf.verifiers.lean_verifier.subprocess.run")
    def test_lean_error_is_classified_and_rejected(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Scratch/p1_attempt1.lean:1:60: error: unknown identifier 'bogus_tactic'",
        )
        result = self.verifier.verify(self.problem, self.candidate)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, VerificationStatus.UNKNOWN_IDENTIFIER)
        self.assertEqual(len(result.errors), 1)

    @patch("mathf.verifiers.lean_verifier.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="lake env lean", timeout=5)
        result = self.verifier.verify(self.problem, self.candidate)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, VerificationStatus.TIMEOUT)

    @patch("mathf.verifiers.lean_verifier.subprocess.run")
    def test_missing_lean_binary(self, mock_run):
        mock_run.side_effect = FileNotFoundError("lake: command not found")
        result = self.verifier.verify(self.problem, self.candidate)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, VerificationStatus.VERIFIER_ERROR)

    @patch("mathf.verifiers.lean_verifier.subprocess.run")
    def test_malformed_candidate_never_invokes_subprocess(self, mock_run):
        bad_candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="")
        result = self.verifier.verify(self.problem, bad_candidate)
        self.assertEqual(result.status, VerificationStatus.MALFORMED_CANDIDATE)
        mock_run.assert_not_called()

    @patch("mathf.verifiers.lean_verifier.subprocess.run")
    def test_scratch_file_written_to_disk(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        self.verifier.verify(self.problem, self.candidate)
        scratch_files = list(Path(self._tmpdir.name, "Scratch").glob("*.lean"))
        self.assertEqual(len(scratch_files), 1)
        self.assertIn("theorem p1", scratch_files[0].read_text())


if __name__ == "__main__":
    unittest.main()
