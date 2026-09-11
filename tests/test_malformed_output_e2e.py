import tempfile
import unittest
from pathlib import Path

from math_f.datasets.minif2f import Task
from math_f.models.mock import ScriptedModel
from math_f.repair.loop import MalformedOutputAbort, RepairLoop
from math_f.trajectories.loader import completed_trajectory_ids, iter_attempt_records
from math_f.trajectories.writer import TrajectoryWriter

TASK = Task(
    task_id="malformed_case",
    source="unit_test",
    split="test",
    theorem_statement="theorem foo : 1 = 1 := by",
    header="",
)
MODEL_META = {"name": "scripted", "revision": None, "temperature": 0.0, "max_new_tokens": 64}


class TestMalformedOutputEndToEnd(unittest.TestCase):
    def test_trajectory_is_persisted_before_the_run_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            writer = TrajectoryWriter(run_dir)
            model = ScriptedModel(["Sorry, I cannot help with this request."])
            loop = RepairLoop(
                model=model, model_meta=MODEL_META, max_attempts=5,
                lean_cmd=["lake", "env", "lean"], lean_project_dir=".", timeout_seconds=30,
            )

            with self.assertRaises(MalformedOutputAbort) as ctx:
                loop.run_task(TASK, "traj_malformed", on_attempt=writer.write_attempt)

            # The attempt that caused the abort must already be on disk.
            self.assertTrue(writer.attempt_exists("traj_malformed", 1))
            saved = list(iter_attempt_records(run_dir, trajectory_id="traj_malformed"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["verification"]["status"], "ABORTED")
            self.assertEqual(saved[0]["verification"]["failure_class"], "malformed_candidate")

            # No final record for this task -- it must be retried on resume,
            # not treated as a completed ABSTAIN.
            self.assertFalse(writer.final_exists("traj_malformed"))
            self.assertNotIn("traj_malformed", completed_trajectory_ids(run_dir))

            # A CLI-level abort marker would be written from `ctx.exception`;
            # simulate that step here to confirm the plumbing is sufficient.
            marker_path = writer.write_abort_marker(
                "malformed_candidate", ctx.exception.reason,
                trajectory_id=ctx.exception.trajectory_id,
                task_id=ctx.exception.task_id, attempt=ctx.exception.attempt,
            )
            self.assertTrue(marker_path.exists())


if __name__ == "__main__":
    unittest.main()
