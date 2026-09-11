import json
import tempfile
import unittest
from pathlib import Path

from math_f.trajectories.writer import TrajectoryWriter


class TestTrajectoryWriter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.writer = TrajectoryWriter(self.run_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_creates_expected_directory_layout(self):
        for sub in ("raw/trajectories", "summaries", "logs", "metadata", "metadata/aborts"):
            self.assertTrue((self.run_dir / sub).is_dir())

    def test_attempt_round_trip(self):
        record = {"trajectory_id": "t1", "attempt": 1, "verification": {"status": "FAIL"}}
        path = self.writer.write_attempt(record)
        self.assertTrue(path.exists())
        self.assertTrue(self.writer.attempt_exists("t1", 1))
        self.assertFalse(self.writer.attempt_exists("t1", 2))
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded, record)

    def test_final_round_trip(self):
        record = {"trajectory_id": "t1", "final_status": "VERIFIED"}
        path = self.writer.write_final(record)
        self.assertTrue(self.writer.final_exists("t1"))
        self.assertEqual(json.loads(path.read_text()), record)

    def test_config_written_once_unless_overwrite(self):
        self.writer.write_config({"a": 1})
        self.writer.write_config({"a": 2})  # should be a no-op
        data = json.loads((self.writer.metadata_dir / "config.json").read_text())
        self.assertEqual(data, {"a": 1})

        self.writer.write_config({"a": 3}, overwrite=True)
        data = json.loads((self.writer.metadata_dir / "config.json").read_text())
        self.assertEqual(data, {"a": 3})

    def test_abort_marker_written(self):
        path = self.writer.write_abort_marker("malformed_candidate", "no proof found", trajectory_id="t1", task_id="t1", attempt=2)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["kind"], "malformed_candidate")
        self.assertEqual(data["attempt"], 2)

    def test_no_partial_file_left_behind_on_write(self):
        self.writer.write_attempt({"trajectory_id": "t2", "attempt": 1})
        tmp_files = list(self.writer.raw_dir.glob(".tmp_*"))
        self.assertEqual(tmp_files, [])


if __name__ == "__main__":
    unittest.main()
