import unittest

from mathf.evaluation.metrics import compute_metrics, format_metrics_report

from tests._fixtures import build_synthetic_dataset


class TestComputeMetrics(unittest.TestCase):
    def setUp(self):
        self.trajectories = build_synthetic_dataset()
        self.metrics = compute_metrics(self.trajectories, max_attempts=5)

    def test_total_problems(self):
        self.assertEqual(self.metrics["total_problems"], 5)

    def test_first_attempt_successes(self):
        self.assertEqual(self.metrics["first_attempt_successes"], 1)  # only p1

    def test_final_successes(self):
        self.assertEqual(self.metrics["final_successes"], 2)  # p1 and p2

    def test_success_rates(self):
        self.assertAlmostEqual(self.metrics["first_attempt_success_rate"], 1 / 5)
        self.assertAlmostEqual(self.metrics["final_success_rate"], 2 / 5)

    def test_average_and_median_attempts(self):
        # solved at attempts [1, 3]
        self.assertAlmostEqual(self.metrics["average_attempts"], 2.0)
        self.assertAlmostEqual(self.metrics["median_attempts"], 2.0)

    def test_timeout_count(self):
        self.assertEqual(self.metrics["timeout_count"], 1)

    def test_malformed_candidate_count(self):
        self.assertEqual(self.metrics["malformed_candidate_count"], 1)

    def test_duplicate_count(self):
        self.assertEqual(self.metrics["duplicate_count"], 1)

    def test_total_verifier_runtime(self):
        expected = sum(
            a["verification"]["runtime_seconds"] for t in self.trajectories for a in t["attempts"]
        )
        self.assertAlmostEqual(self.metrics["total_verifier_runtime_seconds"], expected)

    def test_success_after_attempt_cumulative_counts(self):
        self.assertEqual(self.metrics["success_after_attempt_1"], 1)
        self.assertEqual(self.metrics["success_after_attempt_2"], 1)
        self.assertEqual(self.metrics["success_after_attempt_3"], 2)
        self.assertEqual(self.metrics["success_after_attempt_4"], 2)
        self.assertEqual(self.metrics["success_after_attempt_5"], 2)

    def test_empty_trajectory_list(self):
        m = compute_metrics([], max_attempts=5)
        self.assertEqual(m["total_problems"], 0)

    def test_format_metrics_report_does_not_crash(self):
        report = format_metrics_report(self.metrics)
        self.assertIn("Problems: 5", report)
        self.assertIn("Timeouts: 1", report)

    def test_format_metrics_report_handles_empty(self):
        report = format_metrics_report(compute_metrics([], max_attempts=5))
        self.assertIn("No trajectories", report)


if __name__ == "__main__":
    unittest.main()
