import unittest
from typing import Any, Dict, Optional

from mathf.core.interfaces import CandidateGenerator
from mathf.core.models import Attempt, Candidate, ExperimentConfig, FormalMathProblem, VerificationResult, VerificationStatus
from mathf.core.runner import ExperimentRunner, build_feedback_context
from mathf.generators.tactic_search import FixedTacticSearchGenerator
from mathf.verifiers.mock_verifier import MockLeanVerifier


def make_problem(problem_id="p1", accepted_tactics=None, tactic_priority=None):
    metadata: Dict[str, Any] = {}
    if accepted_tactics is not None:
        metadata["accepted_tactics"] = accepted_tactics
    if tactic_priority is not None:
        metadata["tactic_priority"] = tactic_priority
    return FormalMathProblem(
        problem_id=problem_id,
        informal_statement="test",
        lean_statement=f"theorem {problem_id} : True",
        source="unit_test",
        metadata=metadata,
    )


class ConstantGenerator(CandidateGenerator):
    """Test-only generator that always returns the exact same proof text,
    used to exercise duplicate detection deterministically."""

    name = "constant_generator"

    def __init__(self, proof: str = "by decide"):
        self.proof = proof

    def generate(self, problem, attempt_number, context=None):
        return Candidate(problem_id=problem.problem_id, generator=self.name, attempt=attempt_number, proof=self.proof)


class TestBuildFeedbackContext(unittest.TestCase):
    def test_none_previous_attempt_gives_empty_context(self):
        self.assertEqual(build_feedback_context(None), {})

    def test_context_shape(self):
        result = VerificationResult(verified=False, status=VerificationStatus.TACTIC_FAILURE, runtime_seconds=1.0)
        candidate = Candidate(problem_id="p1", generator="g", attempt=1, proof="by ring")
        attempt = Attempt(attempt=1, candidate=candidate, verification=result)
        ctx = build_feedback_context(attempt)
        self.assertEqual(ctx["previous_attempt_number"], 1)
        self.assertEqual(ctx["previous_proof"], "by ring")
        self.assertEqual(ctx["previous_status"], "TACTIC_FAILURE")
        self.assertFalse(ctx["previous_verified"])


class TestExperimentRunner(unittest.TestCase):
    def _config(self, max_attempts=5, timeout_seconds=30):
        return ExperimentConfig(max_attempts=max_attempts, timeout_seconds=timeout_seconds, output_dir="/tmp/unused")

    def test_first_attempt_success(self):
        problem = make_problem(accepted_tactics=["decide"])  # first in default portfolio
        runner = ExperimentRunner(FixedTacticSearchGenerator(), MockLeanVerifier(), self._config())
        traj = runner.run_problem(problem)
        self.assertTrue(traj.solved)
        self.assertEqual(traj.attempts_used, 1)
        self.assertEqual(traj.final_status, VerificationStatus.VERIFIED)

    def test_success_after_retries(self):
        # "ring" is the 4th entry in the default portfolio
        from mathf.generators.tactic_search import DEFAULT_TACTIC_PORTFOLIO

        ring_index = DEFAULT_TACTIC_PORTFOLIO.index("ring") + 1
        problem = make_problem(accepted_tactics=["ring"])
        runner = ExperimentRunner(FixedTacticSearchGenerator(), MockLeanVerifier(), self._config())
        traj = runner.run_problem(problem)
        self.assertTrue(traj.solved)
        self.assertEqual(traj.attempts_used, ring_index)
        # every attempt before the solving one must be recorded as a failure
        for a in traj.attempts[:-1]:
            self.assertFalse(a.verification.verified)
        self.assertTrue(traj.attempts[-1].verification.verified)

    def test_unsolvable_problem_stops_at_max_attempts(self):
        problem = make_problem(accepted_tactics=[])  # nothing in the portfolio will pass
        runner = ExperimentRunner(FixedTacticSearchGenerator(), MockLeanVerifier(), self._config(max_attempts=5))
        traj = runner.run_problem(problem)
        self.assertFalse(traj.solved)
        self.assertEqual(traj.attempts_used, 5)
        self.assertNotEqual(traj.final_status, VerificationStatus.VERIFIED)

    def test_duplicate_candidates_are_recorded_not_reverified(self):
        problem = make_problem(accepted_tactics=[])  # ConstantGenerator's proof will never match anyway
        runner = ExperimentRunner(ConstantGenerator("by decide"), MockLeanVerifier(), self._config(max_attempts=3))
        traj = runner.run_problem(problem)
        self.assertEqual(traj.attempts_used, 3)
        self.assertFalse(traj.attempts[0].duplicate)
        self.assertTrue(traj.attempts[1].duplicate)
        self.assertTrue(traj.attempts[2].duplicate)
        self.assertEqual(traj.attempts[1].duplicate_of_attempt, 1)
        self.assertEqual(traj.attempts[2].duplicate_of_attempt, 1)

    def test_duplicate_does_not_prevent_eventual_success(self):
        # A generator whose only idea happens to be correct should still
        # be marked solved even though later identical attempts are
        # flagged as duplicates of the (already successful) first one.
        problem = make_problem(accepted_tactics=["decide"])
        runner = ExperimentRunner(ConstantGenerator("by decide"), MockLeanVerifier(), self._config(max_attempts=3))
        traj = runner.run_problem(problem)
        self.assertTrue(traj.solved)
        self.assertEqual(traj.attempts_used, 1)  # loop breaks immediately on success

    def test_run_dataset_produces_one_trajectory_per_problem(self):
        problems = [make_problem(problem_id="a", accepted_tactics=["decide"]), make_problem(problem_id="b", accepted_tactics=["decide"])]
        runner = ExperimentRunner(FixedTacticSearchGenerator(), MockLeanVerifier(), self._config())
        trajectories = runner.run_dataset(problems, save=False)
        self.assertEqual(len(trajectories), 2)
        self.assertEqual({t.problem_id for t in trajectories}, {"a", "b"})

    def test_max_attempts_is_configurable_and_enforced(self):
        problem = make_problem(accepted_tactics=[])
        runner = ExperimentRunner(FixedTacticSearchGenerator(), MockLeanVerifier(), self._config(max_attempts=2))
        traj = runner.run_problem(problem)
        self.assertEqual(traj.attempts_used, 2)


if __name__ == "__main__":
    unittest.main()
