import unittest

from math_f.datasets.minif2f import Task
from math_f.models.mock import ScriptedModel
from math_f.repair.loop import MalformedOutputAbort, RepairLoop

TASK = Task(
    task_id="t1",
    source="unit_test",
    split="test",
    theorem_statement="theorem foo (a b : Nat) : a + b = b + a := by",
    header="import Mathlib",
)

MODEL_META = {"name": "scripted", "revision": None, "temperature": 0.0, "max_new_tokens": 128}


def _fenced(body: str) -> str:
    return f"```lean4\n{body}\n```"


class FakeVerifier:
    """Deterministic stand-in for `run_lean`: PASS iff the candidate text
    contains the marker 'GOOD', otherwise FAIL. Records every call so tests
    can assert the duplicate-candidate short-circuit actually short-circuits.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, header, candidate, lean_cmd, lean_project_dir, timeout_seconds):
        self.calls.append(candidate)
        if "GOOD" in candidate:
            return {
                "status": "PASS", "verifier": "lean", "exit_code": 0,
                "stdout": "", "stderr": "", "diagnostics": [], "failure_class": None,
                "timed_out": False, "duration_ms": 1,
            }
        return {
            "status": "FAIL", "verifier": "lean", "exit_code": 1,
            "stdout": "", "stderr": "error: unsolved goals", "diagnostics": [],
            "failure_class": "unsolved_goal", "timed_out": False, "duration_ms": 1,
        }


def make_loop(outputs, max_attempts=5, duplicate_detection=True):
    model = ScriptedModel(outputs)
    verifier = FakeVerifier()
    loop = RepairLoop(
        model=model,
        model_meta=MODEL_META,
        max_attempts=max_attempts,
        lean_cmd=["lake", "env", "lean"],
        lean_project_dir=".",
        timeout_seconds=30,
        duplicate_detection=duplicate_detection,
        verify_fn=verifier,
    )
    return loop, verifier


class TestRepairLoopSuccess(unittest.TestCase):
    def test_fail_then_pass(self):
        outputs = [_fenced("by bad_tactic"), _fenced("by GOOD_tactic")]
        loop, verifier = make_loop(outputs)
        attempts = []
        outcome = loop.run_task(TASK, "traj_1", on_attempt=attempts.append)

        self.assertEqual(outcome.final_status, "VERIFIED")
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.success_on_attempt, 2)
        self.assertEqual(outcome.attempts_used, 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["verification"]["status"], "FAIL")
        self.assertEqual(attempts[1]["verification"]["status"], "PASS")
        self.assertIsNotNone(attempts[0]["repair_feedback"])
        self.assertIsNone(attempts[1]["repair_feedback"])
        self.assertEqual(len(verifier.calls), 2)

    def test_pass_on_first_attempt(self):
        outputs = [_fenced("by GOOD_tactic")]
        loop, verifier = make_loop(outputs)
        outcome = loop.run_task(TASK, "traj_2")
        self.assertEqual(outcome.success_on_attempt, 1)
        self.assertEqual(outcome.attempts_used, 1)


class TestRepairLoopExhaustion(unittest.TestCase):
    def test_all_attempts_fail_then_abstain(self):
        outputs = [_fenced(f"by bad_tactic_{i}") for i in range(5)]
        loop, verifier = make_loop(outputs, max_attempts=5)
        attempts = []
        outcome = loop.run_task(TASK, "traj_3", on_attempt=attempts.append)

        self.assertEqual(outcome.final_status, "ABSTAIN")
        self.assertFalse(outcome.success)
        self.assertIsNone(outcome.success_on_attempt)
        self.assertEqual(outcome.attempts_used, 5)
        self.assertEqual(len(attempts), 5)
        self.assertEqual(len(verifier.calls), 5)


class TestMalformedAbort(unittest.TestCase):
    def test_malformed_output_raises_and_records_attempt(self):
        outputs = ["I don't know how to prove this, sorry about that."]
        loop, verifier = make_loop(outputs)
        attempts = []
        with self.assertRaises(MalformedOutputAbort) as ctx:
            loop.run_task(TASK, "traj_4", on_attempt=attempts.append)

        self.assertEqual(ctx.exception.trajectory_id, "traj_4")
        self.assertEqual(ctx.exception.attempt, 1)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["verification"]["status"], "ABORTED")
        self.assertEqual(attempts[0]["verification"]["failure_class"], "malformed_candidate")
        # Lean must never be invoked on unparseable output.
        self.assertEqual(len(verifier.calls), 0)

    def test_malformed_output_on_a_later_attempt_still_aborts(self):
        outputs = [_fenced("by bad_tactic"), "no usable content here at all"]
        loop, verifier = make_loop(outputs)
        attempts = []
        with self.assertRaises(MalformedOutputAbort) as ctx:
            loop.run_task(TASK, "traj_5", on_attempt=attempts.append)
        self.assertEqual(ctx.exception.attempt, 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(verifier.calls), 1)  # only attempt 1 reached Lean


class TestDuplicateCandidate(unittest.TestCase):
    def test_exact_repeat_candidate_stops_task_without_reverifying(self):
        outputs = [_fenced("by bad_tactic"), _fenced("by bad_tactic")]
        loop, verifier = make_loop(outputs)
        attempts = []
        outcome = loop.run_task(TASK, "traj_6", on_attempt=attempts.append)

        self.assertEqual(outcome.final_status, "ABSTAIN")
        self.assertEqual(outcome.attempts_used, 2)
        self.assertEqual(attempts[1]["verification"]["failure_class"], "duplicate_candidate")
        # The second, identical candidate must not trigger a second Lean call.
        self.assertEqual(len(verifier.calls), 1)

    def test_duplicate_detection_can_be_disabled(self):
        outputs = [_fenced("by bad_tactic"), _fenced("by bad_tactic")]
        loop, verifier = make_loop(outputs, max_attempts=2, duplicate_detection=False)
        outcome = loop.run_task(TASK, "traj_7")
        self.assertEqual(outcome.attempts_used, 2)
        self.assertEqual(len(verifier.calls), 2)


if __name__ == "__main__":
    unittest.main()
