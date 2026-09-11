import tempfile
import unittest
from pathlib import Path

from math_f.trajectories.loader import completed_trajectory_ids
from math_f.trajectories.writer import TrajectoryWriter
from math_f.utils.ids import trajectory_id_for_task


class TestResume(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.writer = TrajectoryWriter(self.run_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_completed_ids_only_include_finalized_tasks(self):
        self.writer.write_final({"trajectory_id": "test__a", "final_status": "VERIFIED"})
        self.writer.write_final({"trajectory_id": "test__b", "final_status": "ABSTAIN"})
        # A task that was interrupted mid-way (e.g. by a malformed abort)
        # has attempt files but no final file.
        self.writer.write_attempt({"trajectory_id": "test__c", "attempt": 1})

        done = completed_trajectory_ids(self.run_dir)
        self.assertEqual(done, {"test__a", "test__b"})

    def test_trajectory_ids_are_deterministic_for_resume_matching(self):
        id1 = trajectory_id_for_task("test", "amc12a_2015_p10")
        id2 = trajectory_id_for_task("test", "amc12a_2015_p10")
        self.assertEqual(id1, id2)

    def test_resume_filters_task_list_correctly(self):
        class FakeTask:
            def __init__(self, task_id):
                self.task_id = task_id
                self.split = "test"

        all_tasks = [FakeTask(f"task_{i}") for i in range(5)]
        for t in all_tasks[:3]:
            self.writer.write_final(
                {"trajectory_id": trajectory_id_for_task(t.split, t.task_id), "final_status": "VERIFIED"}
            )

        done = completed_trajectory_ids(self.run_dir)
        remaining = [t for t in all_tasks if trajectory_id_for_task(t.split, t.task_id) not in done]

        self.assertEqual(len(remaining), 2)
        self.assertEqual([t.task_id for t in remaining], ["task_3", "task_4"])

    def test_unsafe_characters_are_sanitized_in_ids(self):
        tid = trajectory_id_for_task("te/st", "task id with spaces")
        self.assertNotIn("/", tid)
        self.assertNotIn(" ", tid)


if __name__ == "__main__":
    unittest.main()
