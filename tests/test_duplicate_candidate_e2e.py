import tempfile
import unittest
from pathlib import Path

from math_f.datasets.minif2f import Task
from math_f.models.mock import ScriptedModel
from math_f.repair.loop import RepairLoop
from math_f.trajectories.loader import iter_attempt_records
from math_f.trajectories.writer import TrajectoryWriter

TASK = Task(
    task_id="duplicate_case",
    source="unit_test",
    split="test",
    theorem_statement="theorem foo (n : Nat) : n = n := by",
    header="",
)
MODEL_META = {"name": "scripted", "revision": None, "temperature": 0.0, "max_new_tokens": 64}


def _always_fail_verifier():
    def verify(header, candidate, lean_cmd, lean_project_dir, timeout_seconds):
        return {
            "status": "FAIL", "verifier": "lean", "exit_code": 1, "stdout": "",
            "stderr": "error: unsolved goals", "diagnostics": [],
            "failure_class": "unsolved_goal", "timed_out": False, "duration_ms": 1,
        }

    return verify


class TestDuplicateCandidateEndToEnd(unittest.TestCase):
    def test_repeated_candidate_ends_task_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            writer = TrajectoryWriter(run_dir)
            # Attempts 1 and 3 are identical after cleaning; attempt 2 differs.
            model = ScriptedModel(
                [
                    "```lean4\nby exact rfl_wrong\n```",
                    "```lean4\nby simp only []\n```",
                    "```lean4\nby exact rfl_wrong\n```",
                ]
            )
            loop = RepairLoop(
                model=model, model_meta=MODEL_META, max_attempts=5,
                lean_cmd=["lake", "env", "lean"], lean_project_dir=".", timeout_seconds=30,
                verify_fn=_always_fail_verifier(),
            )
            outcome = loop.run_task(TASK, "traj_dup", on_attempt=writer.write_attempt)

            self.assertEqual(outcome.final_status, "ABSTAIN")
            self.assertEqual(outcome.attempts_used, 3)

            saved = list(iter_attempt_records(run_dir, trajectory_id="traj_dup"))
            self.assertEqual(len(saved), 3)
            self.assertEqual(saved[0]["verification"]["failure_class"], "unsolved_goal")
            self.assertEqual(saved[1]["verification"]["failure_class"], "unsolved_goal")
            self.assertEqual(saved[2]["verification"]["failure_class"], "duplicate_candidate")


if __name__ == "__main__":
    unittest.main()
