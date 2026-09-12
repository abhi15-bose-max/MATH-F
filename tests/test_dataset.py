import json
import tempfile
import unittest
from pathlib import Path

from mathf.core.dataset import load_dataset, validate_dataset
from mathf.core.models import FormalMathProblem

REPO_ROOT = Path(__file__).resolve().parent.parent
DEV_BENCHMARK = REPO_ROOT / "datasets" / "v1" / "problems.json"


class TestDatasetLoading(unittest.TestCase):
    def test_loads_dev_benchmark(self):
        problems = load_dataset(str(DEV_BENCHMARK))
        self.assertGreaterEqual(len(problems), 10)
        self.assertLessEqual(len(problems), 20)
        for p in problems:
            self.assertIsInstance(p, FormalMathProblem)

    def test_dev_benchmark_is_valid(self):
        problems = load_dataset(str(DEV_BENCHMARK))
        valid, issues = validate_dataset(problems)
        self.assertTrue(valid, msg=f"Dataset issues: {issues}")

    def test_loads_bare_list_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bare.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "problem_id": "x1",
                            "informal_statement": "trivial",
                            "lean_statement": "theorem x1 : True",
                            "source": "test",
                        }
                    ]
                )
            )
            problems = load_dataset(str(path))
            self.assertEqual(len(problems), 1)
            self.assertEqual(problems[0].problem_id, "x1")

    def test_unexpected_json_shape_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text(json.dumps({"not_problems": []}))
            with self.assertRaises(ValueError):
                load_dataset(str(path))


class TestProblemValidation(unittest.TestCase):
    def test_valid_problem_has_no_errors(self):
        p = FormalMathProblem(
            problem_id="p1",
            informal_statement="stmt",
            lean_statement="theorem p1 : True",
            source="unit_test",
        )
        self.assertEqual(p.validate(), [])

    def test_missing_fields_detected(self):
        p = FormalMathProblem(problem_id="", informal_statement="", lean_statement="")
        errors = p.validate()
        self.assertGreaterEqual(len(errors), 3)

    def test_duplicate_ids_detected(self):
        problems = [
            FormalMathProblem(problem_id="dup", informal_statement="a", lean_statement="theorem dup : True"),
            FormalMathProblem(problem_id="dup", informal_statement="b", lean_statement="theorem dup2 : True"),
        ]
        valid, issues = validate_dataset(problems)
        self.assertFalse(valid)
        self.assertTrue(any("duplicate problem_id" in i for i in issues))

    def test_from_dict_preserves_unknown_fields_in_metadata(self):
        p = FormalMathProblem.from_dict(
            {
                "problem_id": "p2",
                "informal_statement": "s",
                "lean_statement": "theorem p2 : True",
                "weird_extra_field": 42,
            }
        )
        self.assertEqual(p.metadata.get("weird_extra_field"), 42)


if __name__ == "__main__":
    unittest.main()
