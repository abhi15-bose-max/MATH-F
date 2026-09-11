import tempfile
import unittest
from pathlib import Path

from math_f.evaluation.metrics import compute_metrics
from math_f.evaluation.reports import render_markdown_table, write_reports
from math_f.trajectories.writer import TrajectoryWriter


class TestReports(unittest.TestCase):
    def test_write_reports_creates_all_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            writer = TrajectoryWriter(run_dir)
            writer.write_final(
                {
                    "trajectory_id": "a", "task_id": "a", "final_status": "VERIFIED",
                    "success": True, "success_on_attempt": 1, "attempts_used": 1,
                    "max_attempts": 5, "abort_reason": None,
                }
            )
            metrics = compute_metrics(run_dir, max_attempts=5)
            paths = write_reports(run_dir, metrics)

            for key in ("json", "csv", "md"):
                self.assertTrue(paths[key].exists())

            table = render_markdown_table(metrics)
            self.assertIn("Tasks evaluated", table)
            self.assertIn("1", table)


if __name__ == "__main__":
    unittest.main()
