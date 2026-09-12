import unittest

from mathf.evaluation.failure_analysis import analyze_failures, format_failure_report

from tests._fixtures import build_synthetic_dataset


class TestAnalyzeFailures(unittest.TestCase):
    def setUp(self):
        self.report = analyze_failures(build_synthetic_dataset())

    def test_failure_counts_by_status(self):
        counts = self.report["failure_counts_by_status"]
        self.assertEqual(counts["TACTIC_FAILURE"], 8)  # 2 (p2) + 5 (p3) + 1 (p4)
        self.assertEqual(counts["TIMEOUT"], 1)
        self.assertEqual(counts["MALFORMED_CANDIDATE"], 1)

    def test_unsolved_problems(self):
        self.assertEqual(set(self.report["unsolved_problems"]), {"p3", "p4", "p5"})

    def test_problems_needing_retries(self):
        needing_retries = {e["problem_id"]: e["attempts_needed"] for e in self.report["problems_needing_retries"]}
        self.assertEqual(needing_retries, {"p2": 3})  # p1 solved on attempt 1, not a "retry"

    def test_average_attempts_for_solved(self):
        self.assertAlmostEqual(self.report["average_attempts_for_solved"], 2.0)  # (1 + 3) / 2

    def test_repeated_identical_failure_problems(self):
        repeated = self.report["repeated_identical_failure_problems"]
        self.assertEqual(repeated.get("p2"), {"TACTIC_FAILURE": 2})
        self.assertEqual(repeated.get("p3"), {"TACTIC_FAILURE": 5})
        # p4 mixes TACTIC_FAILURE and TIMEOUT -> not a "repeated identical" case
        self.assertNotIn("p4", repeated)
        # p5 only fails once -> not "repeated"
        self.assertNotIn("p5", repeated)

    def test_generator_specific_failure_patterns(self):
        patterns = self.report["generator_specific_failure_patterns"]
        self.assertEqual(
            patterns["fixed_tactic_search"],
            {"TACTIC_FAILURE": 8, "TIMEOUT": 1, "MALFORMED_CANDIDATE": 1},
        )

    def test_format_failure_report_does_not_crash(self):
        text = format_failure_report(self.report)
        self.assertIn("Unsolved problems", text)
        self.assertIn("p3", text)

    def test_empty_input(self):
        report = analyze_failures([])
        self.assertEqual(report["failure_counts_by_status"], {})
        self.assertEqual(report["unsolved_problems"], [])


if __name__ == "__main__":
    unittest.main()
