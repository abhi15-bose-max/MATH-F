import argparse
import unittest

from math_f.cli import cmd_smoke_test


def _args(**overrides):
    defaults = dict(
        config=None, model_name=None, model_backend=None, model_revision=None,
        dataset_name=None, timeout=None, lean_project_dir=None,
        backend="mock", tasks=1,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestSmokeTestCLI(unittest.TestCase):
    def test_smoke_test_runs_with_mock_backend(self):
        # Lean is not installed in this environment, so the Lean/Mathlib
        # checks are expected to SKIP/FAIL gracefully rather than crash the
        # whole command; the mock backend keeps model/tokenizer checks
        # non-fatal so overall exit code should still be 0.
        exit_code = cmd_smoke_test(_args())
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
