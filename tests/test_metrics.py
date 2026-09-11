import tempfile
import unittest
from pathlib import Path

from math_f.evaluation.metrics import compute_metrics
from math_f.trajectories.writer import TrajectoryWriter


def _final(trajectory_id, success_on_attempt, max_attempts=5):
    if success_on_attempt is None:
        return {
            "trajectory_id": trajectory_id, "task_id": trajectory_id,
            "final_status": "ABSTAIN", "success": False, "success_on_attempt": None,
            "attempts_used": max_attempts, "max_attempts": max_attempts, "abort_reason": None,
        }
    return {
        "trajectory_id": trajectory_id, "task_id": trajectory_id,
        "final_status": "VERIFIED", "success": True, "success_on_attempt": success_on_attempt,
        "attempts_used": success_on_attempt, "max_attempts": max_attempts, "abort_reason": None,
    }


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.writer = TrajectoryWriter(self.run_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_exact_vs_cumulative_matches_spec_example(self):
        # Spec section 17 worked example, scaled to 20 tasks:
        #   success_on_attempt_1 = 40% (8/20)
        #   success_on_attempt_2 = 10% (2/20)
        #   success_on_attempt_3 = 5%  (1/20)
        #   cumulative_1 = 40%, cumulative_2 = 50%, cumulative_3 = 55%
        idx = 0
        for _ in range(8):
            self.writer.write_final(_final(f"t{idx}", 1)); idx += 1
        for _ in range(2):
            self.writer.write_final(_final(f"t{idx}", 2)); idx += 1
        for _ in range(1):
            self.writer.write_final(_final(f"t{idx}", 3)); idx += 1
        for _ in range(9):  # remaining 9 ABSTAIN -> total 20
            self.writer.write_final(_final(f"t{idx}", None)); idx += 1

        metrics = compute_metrics(self.run_dir, max_attempts=5)

        self.assertEqual(metrics["total_tasks"], 20)
        self.assertEqual(metrics["exact_attempt_distribution"]["success_on_attempt_1"], 8)
        self.assertEqual(metrics["exact_attempt_distribution"]["success_on_attempt_2"], 2)
        self.assertEqual(metrics["exact_attempt_distribution"]["success_on_attempt_3"], 1)
        self.assertEqual(metrics["exact_attempt_distribution"]["success_on_attempt_4"], 0)

        cumulative = metrics["cumulative_success_by_attempt"]
        self.assertAlmostEqual(cumulative["cumulative_success_1_shot"], 0.40)
        self.assertAlmostEqual(cumulative["cumulative_success_2_shot"], 0.50)
        self.assertAlmostEqual(cumulative["cumulative_success_3_shot"], 0.55)
        self.assertAlmostEqual(cumulative["cumulative_success_5_shot"], 0.55)  # no more successes after attempt 3

        self.assertEqual(metrics["verified_tasks"], 11)
        self.assertEqual(metrics["abstained_tasks"], 9)

    def test_exact_and_cumulative_are_not_confused(self):
        # A pathological case that would trip up a confused implementation:
        # nobody succeeds on attempt 1, everybody succeeds on attempt 2.
        for i in range(4):
            self.writer.write_final(_final(f"t{i}", 2))

        metrics = compute_metrics(self.run_dir, max_attempts=5)
        self.assertEqual(metrics["exact_attempt_distribution"]["success_on_attempt_1"], 0)
        self.assertEqual(metrics["exact_attempt_distribution"]["success_on_attempt_2"], 4)
        cumulative = metrics["cumulative_success_by_attempt"]
        self.assertAlmostEqual(cumulative["cumulative_success_1_shot"], 0.0)
        self.assertAlmostEqual(cumulative["cumulative_success_2_shot"], 1.0)

    def test_mean_and_median_attempts_to_success(self):
        for i, k in enumerate((1, 1, 3, 5)):
            self.writer.write_final(_final(f"m{i}", k))
        metrics = compute_metrics(self.run_dir, max_attempts=5)
        self.assertAlmostEqual(metrics["mean_attempts_to_success"], (1 + 1 + 3 + 5) / 4)
        self.assertEqual(metrics["median_attempts_to_success"], 2)

    def test_empty_run_has_sane_defaults(self):
        metrics = compute_metrics(self.run_dir, max_attempts=5)
        self.assertEqual(metrics["total_tasks"], 0)
        self.assertIsNone(metrics["mean_attempts_to_success"])
        for k in range(1, 6):
            self.assertEqual(metrics["cumulative_success_by_attempt"][f"cumulative_success_{k}_shot"], 0.0)

    def test_failure_class_counts_aggregate_over_all_attempts(self):
        self.writer.write_attempt(
            {
                "trajectory_id": "t1", "attempt": 1,
                "verification": {"status": "FAIL", "failure_class": "unsolved_goal"},
                "runtime": {"generation_latency_ms": 100, "verification_latency_ms": 50, "output_tokens": 20, "input_tokens": 10},
            }
        )
        self.writer.write_attempt(
            {
                "trajectory_id": "t1", "attempt": 2,
                "verification": {"status": "PASS", "failure_class": None},
                "runtime": {"generation_latency_ms": 100, "verification_latency_ms": 50, "output_tokens": 15, "input_tokens": 12},
            }
        )
        self.writer.write_attempt(
            {
                "trajectory_id": "t2", "attempt": 1,
                "verification": {"status": "FAIL", "failure_class": "unsolved_goal"},
                "runtime": {"generation_latency_ms": 200, "verification_latency_ms": 20, "output_tokens": 30, "input_tokens": 11},
            }
        )
        self.writer.write_final(_final("t1", 2))
        self.writer.write_final(_final("t2", None))

        metrics = compute_metrics(self.run_dir, max_attempts=5)
        self.assertEqual(metrics["failure_class_counts"], {"unsolved_goal": 2})
        self.assertEqual(metrics["total_generation_tokens"], 20 + 15 + 30)
        self.assertEqual(metrics["total_input_tokens"], 10 + 12 + 11)
        self.assertAlmostEqual(metrics["total_generation_time_seconds"], 0.4)
        self.assertAlmostEqual(metrics["total_verification_time_seconds"], 0.12)

    def test_abort_events_counted_separately_from_percentages(self):
        self.writer.write_final(_final("t1", 1))
        self.writer.write_abort_marker("malformed_candidate", "bad output", trajectory_id="t2", task_id="t2", attempt=1)
        self.writer.write_abort_marker("infrastructure_error", "lean missing", trajectory_id="t3", task_id="t3")

        metrics = compute_metrics(self.run_dir, max_attempts=5)
        self.assertEqual(metrics["malformed_output_count"], 1)
        self.assertEqual(metrics["infrastructure_abort_count"], 1)
        self.assertEqual(metrics["aborted_tasks"], 2)
        # Aborted tasks are not folded into the normal success denominator.
        self.assertEqual(metrics["total_tasks"], 1)


if __name__ == "__main__":
    unittest.main()
