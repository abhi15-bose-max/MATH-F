import subprocess
import unittest
from unittest.mock import patch, MagicMock

from math_f.verification.lean_runner import LeanInfrastructureError, run_lean

LEAN_CMD = ["lake", "env", "lean"]


class TestLeanRunner(unittest.TestCase):
    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run")
    def test_valid_candidate_passes(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = run_lean(
            header="import Mathlib",
            candidate="theorem foo : 1 = 1 := by rfl",
            lean_cmd=LEAN_CMD,
            lean_project_dir=".",
            timeout_seconds=30,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["exit_code"], 0)
        self.assertIsNone(result["failure_class"])

    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run")
    def test_invalid_candidate_fails_with_diagnostics(self, mock_run, mock_which):
        stderr = "/tmp/x/candidate.lean:3:2: error: unsolved goals\n\u22a2 1 = 2\n"
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr=stderr)
        result = run_lean(
            header="",
            candidate="theorem foo : 1 = 2 := by rfl",
            lean_cmd=LEAN_CMD,
            lean_project_dir=".",
            timeout_seconds=30,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(len(result["diagnostics"]), 1)
        self.assertEqual(result["diagnostics"][0]["line"], 3)
        self.assertEqual(result["failure_class"], "unsolved_goal")

    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run")
    def test_syntax_error_classified(self, mock_run, mock_which):
        stderr = "/tmp/x/candidate.lean:1:10: error: unexpected token '='; expected term\n"
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr=stderr)
        result = run_lean(
            header="", candidate="theorem foo : = 1", lean_cmd=LEAN_CMD,
            lean_project_dir=".", timeout_seconds=30,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failure_class"], "lean_syntax_error")

    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run")
    def test_sorry_is_treated_as_failure_even_with_exit_zero(self, mock_run, mock_which):
        # Lean happily exits 0 on a `sorry`-admitted proof but warns about it.
        # "Lean is the authority" means we must not call this PASS.
        stdout = "/tmp/x/candidate.lean:1:0: warning: declaration uses 'sorry'\n"
        mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")
        result = run_lean(
            header="", candidate="theorem foo : 1 = 2 := by sorry", lean_cmd=LEAN_CMD,
            lean_project_dir=".", timeout_seconds=30,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failure_class"], "uses_sorry")

    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run")
    def test_timeout(self, mock_run, mock_which):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=LEAN_CMD, timeout=5)
        result = run_lean(
            header="", candidate="theorem foo : 1 = 1 := by rfl", lean_cmd=LEAN_CMD,
            lean_project_dir=".", timeout_seconds=5,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["failure_class"], "timeout")

    @patch("math_f.verification.lean_runner.shutil.which", return_value=None)
    def test_missing_lean_executable_raises_infrastructure_error(self, mock_which):
        with self.assertRaises(LeanInfrastructureError) as ctx:
            run_lean(
                header="", candidate="theorem foo : 1 = 1 := by rfl", lean_cmd=LEAN_CMD,
                lean_project_dir=".", timeout_seconds=30,
            )
        self.assertFalse(ctx.exception.retryable)

    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run", side_effect=FileNotFoundError("no such file"))
    def test_file_not_found_during_invocation_raises_infrastructure_error(self, mock_run, mock_which):
        with self.assertRaises(LeanInfrastructureError) as ctx:
            run_lean(
                header="", candidate="theorem foo : 1 = 1 := by rfl", lean_cmd=LEAN_CMD,
                lean_project_dir=".", timeout_seconds=30,
            )
        self.assertFalse(ctx.exception.retryable)

    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run", side_effect=OSError("transient os error"))
    def test_os_error_is_retryable_infrastructure_error(self, mock_run, mock_which):
        with self.assertRaises(LeanInfrastructureError) as ctx:
            run_lean(
                header="", candidate="theorem foo : 1 = 1 := by rfl", lean_cmd=LEAN_CMD,
                lean_project_dir=".", timeout_seconds=30,
            )
        self.assertTrue(ctx.exception.retryable)

    @patch("math_f.verification.lean_runner.shutil.which", return_value="/usr/bin/lake")
    @patch("math_f.verification.lean_runner.subprocess.run")
    def test_temp_directory_is_cleaned_up(self, mock_run, mock_which):
        captured = {}

        def fake_run(cmd, cwd, capture_output, text, timeout):
            captured["path"] = cmd[-1]
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run
        run_lean(
            header="", candidate="theorem foo : 1 = 1 := by rfl", lean_cmd=LEAN_CMD,
            lean_project_dir=".", timeout_seconds=30,
        )
        import os

        self.assertFalse(os.path.exists(captured["path"]))


if __name__ == "__main__":
    unittest.main()
