import os
import tempfile
import unittest
from pathlib import Path

from math_f.config import ExperimentConfig, apply_env_overrides, apply_overrides


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        config = ExperimentConfig()
        self.assertEqual(config.evaluation.max_attempts, 5)
        self.assertEqual(config.model.backend, "hf")
        self.assertEqual(config.verification.lean_cmd, ["lake", "env", "lean"])

    def test_load_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.yaml"
            path.write_text(
                "model:\n  name: some/model\nevaluation:\n  max_attempts: 3\n", encoding="utf-8"
            )
            config = ExperimentConfig.load(str(path))
            self.assertEqual(config.model.name, "some/model")
            self.assertEqual(config.evaluation.max_attempts, 3)
            # Unset fields keep their dataclass defaults.
            self.assertEqual(config.verification.timeout_seconds, 60)

    def test_env_overrides(self):
        config = ExperimentConfig()
        os.environ["MODEL_NAME"] = "env/model"
        os.environ["MAX_ATTEMPTS"] = "2"
        try:
            config = apply_env_overrides(config)
        finally:
            del os.environ["MODEL_NAME"]
            del os.environ["MAX_ATTEMPTS"]
        self.assertEqual(config.model.name, "env/model")
        self.assertEqual(config.evaluation.max_attempts, 2)

    def test_dotted_overrides(self):
        config = ExperimentConfig()
        apply_overrides(config, {"model.name": "cli/model", "evaluation.split": "valid"})
        self.assertEqual(config.model.name, "cli/model")
        self.assertEqual(config.evaluation.split, "valid")

    def test_round_trip_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ExperimentConfig()
            config.model.name = "roundtrip/model"
            path = Path(tmp) / "config.json"
            config.save(path)
            reloaded = ExperimentConfig.load(str(path))
            self.assertEqual(reloaded.model.name, "roundtrip/model")


if __name__ == "__main__":
    unittest.main()
