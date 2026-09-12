import json
import tempfile
import unittest
from pathlib import Path

from mathf.core.models import Attempt, Candidate, Trajectory, VerificationResult, VerificationStatus
from mathf.logging.trajectory import DuplicateTracker, load_all_trajectories, load_trajectory, save_trajectory


class TestDuplicateTracker(unittest.TestCase):
    def test_first_occurrence_is_not_a_duplicate(self):
        t = DuplicateTracker()
        self.assertIsNone(t.check_and_record(1, "by ring"))

    def test_exact_repeat_is_flagged_with_earlier_attempt(self):
        t = DuplicateTracker()
        t.check_and_record(1, "by ring")
        self.assertEqual(t.check_and_record(2, "by ring"), 1)

    def test_whitespace_differences_are_still_duplicates(self):
        t = DuplicateTracker()
        t.check_and_record(1, "by   ring")
        self.assertEqual(t.check_and_record(2, "by ring"), 1)

    def test_different_proofs_are_not_duplicates(self):
        t = DuplicateTracker()
        t.check_and_record(1, "by ring")
        self.assertIsNone(t.check_and_record(2, "by omega"))

    def test_earliest_attempt_is_preserved_across_repeats(self):
        t = DuplicateTracker()
        t.check_and_record(1, "by ring")
        t.check_and_record(2, "by ring")
        self.assertEqual(t.check_and_record(3, "by ring"), 1)


def make_trajectory():
    traj = Trajectory(
        problem_id="p1",
        generator="fixed_tactic_search",
        verifier="mock_lean_v0",
        configuration={"max_attempts": 5, "timeout_seconds": 30},
    )
    c1 = Candidate(problem_id="p1", generator="fixed_tactic_search", attempt=1, proof="by decide")
    r1 = VerificationResult(verified=False, status=VerificationStatus.TACTIC_FAILURE, runtime_seconds=0.1)
    traj.add_attempt(Attempt(attempt=1, candidate=c1, verification=r1))

    c2 = Candidate(problem_id="p1", generator="fixed_tactic_search", attempt=2, proof="by ring")
    r2 = VerificationResult(verified=True, status=VerificationStatus.VERIFIED, runtime_seconds=0.2)
    traj.add_attempt(Attempt(attempt=2, candidate=c2, verification=r2))
    return traj


class TestTrajectoryPersistence(unittest.TestCase):
    def test_add_attempt_updates_solved_and_final_status(self):
        traj = make_trajectory()
        self.assertTrue(traj.solved)
        self.assertEqual(traj.final_status, VerificationStatus.VERIFIED)
        self.assertEqual(traj.attempts_used, 2)

    def test_save_and_load_round_trip(self):
        traj = make_trajectory()
        with tempfile.TemporaryDirectory() as d:
            path = save_trajectory(traj, d)
            self.assertTrue(path.exists())
            loaded = load_trajectory(str(path))
            self.assertEqual(loaded["problem_id"], "p1")
            self.assertEqual(loaded["final_status"], "VERIFIED")
            self.assertEqual(len(loaded["attempts"]), 2)
            self.assertEqual(loaded["attempts"][0]["verification"]["status"], "TACTIC_FAILURE")
            self.assertEqual(loaded["attempts"][1]["verification"]["status"], "VERIFIED")

    def test_load_all_trajectories(self):
        with tempfile.TemporaryDirectory() as d:
            save_trajectory(make_trajectory(), d)
            traj2 = make_trajectory()
            traj2.problem_id = "p2"
            save_trajectory(traj2, d)
            all_traj = load_all_trajectories(d)
            self.assertEqual(len(all_traj), 2)
            self.assertEqual({t["problem_id"] for t in all_traj}, {"p1", "p2"})

    def test_saved_json_is_valid_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path1 = save_trajectory(make_trajectory(), d)
            path2 = save_trajectory(make_trajectory(), d)  # different trajectory_id -> different file
            self.assertNotEqual(path1, path2)
            self.assertEqual(len(list(Path(d).glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
