"""Experiment configuration.

Configuration is loaded from YAML/JSON, then overridden by environment
variables, then overridden by explicit CLI arguments (highest priority).
This keeps constants out of the code (spec section 29) while still letting
the repository be driven entirely from the command line for quick runs.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a base dependency
    yaml = None


DEFAULT_MODEL_NAME = "AI-MO/Kimina-Prover-Preview-Distill-1.5B"
# ^ Default ~1.5B Lean 4 theorem-proving specialist (Project Numina / Kimi
#   distillation of Kimina-Prover-Preview onto Qwen2.5-1.5B). Overridable via
#   MODEL_NAME env var or --model-name.

DEFAULT_DATASET_NAME = "AI-MO/minif2f_test"


@dataclass
class ModelConfig:
    backend: str = "hf"  # "hf" (real Transformers model) or "mock"
    name: str = DEFAULT_MODEL_NAME
    revision: Optional[str] = None
    temperature: float = 0.0
    top_p: float = 0.95
    do_sample: bool = False
    max_new_tokens: int = 1024
    device_map: str = "auto"
    dtype: str = "auto"  # "auto" | "bfloat16" | "float16" | "float32"


@dataclass
class VerificationConfig:
    timeout_seconds: int = 60
    lean_cmd: list = field(default_factory=lambda: ["lake", "env", "lean"])
    lean_project_dir: str = "."
    max_consecutive_infra_failures: int = 3


@dataclass
class EvaluationConfig:
    dataset_name: str = DEFAULT_DATASET_NAME
    split: str = "test"
    limit: Optional[int] = None
    shuffle: bool = False
    random_seed: int = 0
    max_attempts: int = 5
    duplicate_detection: bool = True


@dataclass
class OutputConfig:
    directory: str = "runs/"


@dataclass
class ExperimentConfig:
    experiment_id: Optional[str] = None
    model: ModelConfig = field(default_factory=ModelConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    # Convenience top-level aliases used throughout the spec's examples.
    @property
    def max_attempts(self) -> int:
        return self.evaluation.max_attempts

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentConfig":
        data = dict(data or {})
        model = ModelConfig(**data.get("model", {}))
        verification = VerificationConfig(**data.get("verification", {}))
        evaluation = EvaluationConfig(**data.get("evaluation", {}))
        output = OutputConfig(**data.get("output", {}))
        return cls(
            experiment_id=data.get("experiment_id"),
            model=model,
            verification=verification,
            evaluation=evaluation,
            output=output,
        )

    @classmethod
    def load(cls, path: Optional[str] = None) -> "ExperimentConfig":
        if path is None:
            return cls()
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("PyYAML is required to read YAML config files.")
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text) if text.strip() else {}
        return cls.from_dict(data)


def _coerce(value: str) -> Any:
    """Best-effort coercion of a CLI/env override string into bool/int/float."""
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def apply_env_overrides(config: ExperimentConfig) -> ExperimentConfig:
    """Apply well-known environment variable overrides on top of a config."""
    if os.getenv("MODEL_NAME"):
        config.model.name = os.getenv("MODEL_NAME")
    if os.getenv("MODEL_BACKEND"):
        config.model.backend = os.getenv("MODEL_BACKEND")
    if os.getenv("MODEL_REVISION"):
        config.model.revision = os.getenv("MODEL_REVISION")
    if os.getenv("MAX_ATTEMPTS"):
        config.evaluation.max_attempts = int(os.getenv("MAX_ATTEMPTS"))
    if os.getenv("LEAN_PROJECT_DIR"):
        config.verification.lean_project_dir = os.getenv("LEAN_PROJECT_DIR")
    if os.getenv("VERIFY_TIMEOUT_SECONDS"):
        config.verification.timeout_seconds = int(os.getenv("VERIFY_TIMEOUT_SECONDS"))
    return config


def apply_overrides(config: ExperimentConfig, overrides: dict) -> ExperimentConfig:
    """Apply a flat dict of dotted-path overrides, e.g. {'model.name': 'x'}.

    Used by the CLI to apply explicit flags on top of the loaded config
    without CLI code needing to know about dataclass internals everywhere.
    """
    for dotted_key, value in (overrides or {}).items():
        if value is None:
            continue
        parts = dotted_key.split(".")
        obj = config
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)
    return config
