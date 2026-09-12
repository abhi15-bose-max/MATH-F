import unittest

from mathf.core.models import Candidate, FormalMathProblem
from mathf.generators.tactic_search import DEFAULT_TACTIC_PORTFOLIO, FixedTacticSearchGenerator


def make_problem(tactic_priority=None, problem_id="p1"):
    metadata = {"tactic_priority": tactic_priority} if tactic_priority else {}
    return FormalMathProblem(
        problem_id=problem_id,
        informal_statement="test",
        lean_statement=f"theorem {problem_id} : True",
        source="unit_test",
        metadata=metadata,
    )


class TestCandidateValidation(unittest.TestCase):
    def test_valid_candidate(self):
        c = Candidate(problem_id="p1", generator="g", attempt=1, proof="by decide")
        self.assertEqual(c.validate(), [])

    def test_empty_proof_invalid(self):
        c = Candidate(problem_id="p1", generator="g", attempt=1, proof="   ")
        self.assertIn("proof must not be empty/whitespace-only", c.validate())

    def test_nonpositive_attempt_invalid(self):
        c = Candidate(problem_id="p1", generator="g", attempt=0, proof="by decide")
        errors = c.validate()
        self.assertTrue(any("attempt" in e for e in errors))

    def test_missing_problem_id_invalid(self):
        c = Candidate(problem_id="", generator="g", attempt=1, proof="by decide")
        errors = c.validate()
        self.assertTrue(any("problem_id" in e for e in errors))


class TestFixedTacticSearchGenerator(unittest.TestCase):
    def test_uses_default_portfolio_without_hints(self):
        gen = FixedTacticSearchGenerator()
        problem = make_problem()
        for i, expected_tactic in enumerate(DEFAULT_TACTIC_PORTFOLIO[:3], start=1):
            candidate = gen.generate(problem, i)
            self.assertEqual(candidate.proof, f"by {expected_tactic}")
            self.assertEqual(candidate.attempt, i)
            self.assertEqual(candidate.generator, gen.name)

    def test_respects_per_problem_tactic_priority(self):
        gen = FixedTacticSearchGenerator()
        problem = make_problem(tactic_priority=["ring", "omega"])
        self.assertEqual(gen.generate(problem, 1).proof, "by ring")
        self.assertEqual(gen.generate(problem, 2).proof, "by omega")
        # after exhausting the hinted tactics, falls back to the generic
        # portfolio rather than repeating / erroring
        third = gen.generate(problem, 3)
        self.assertTrue(third.proof.startswith("by "))
        self.assertNotIn(third.proof, ("by ring", "by omega"))

    def test_deterministic_given_same_inputs(self):
        gen = FixedTacticSearchGenerator()
        problem = make_problem(tactic_priority=["norm_num"])
        c1 = gen.generate(problem, 2)
        c2 = gen.generate(problem, 2)
        self.assertEqual(c1.proof, c2.proof)

    def test_exhausted_flag_set_past_portfolio_length(self):
        gen = FixedTacticSearchGenerator()
        problem = make_problem(tactic_priority=["ring"])
        portfolio_len = len(gen._portfolio_for(problem))
        last_candidate = gen.generate(problem, portfolio_len)
        past_candidate = gen.generate(problem, portfolio_len + 1)
        self.assertFalse(last_candidate.metadata["exhausted"])
        self.assertTrue(past_candidate.metadata["exhausted"])

    def test_reset_is_a_safe_noop(self):
        gen = FixedTacticSearchGenerator()
        gen.reset()  # should not raise; generator has no internal state


if __name__ == "__main__":
    unittest.main()
