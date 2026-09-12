#!/usr/bin/env python3
"""
Run the MATH-F V1 experiment end-to-end:

    load config -> load dataset -> build generator + verifier
        -> run retry loop per problem -> save trajectories
        -> compute metrics -> compute failure analysis -> print report

Usage
-----
    python experiments/run_v1.py
    python experiments/run_v1.py --config configs/default.yaml --max-attempts 8
    python experiments/run_v1.py --verifier mock --allow-mock   # offline dev/demo, NOT real verification
    python experiments/run_v1.py --check-lean                  # sanity-check the Lean toolchain and exit

By default this uses the real `LeanVerifier`, which requires a working
Lean 4 + Mathlib installation (see lean_project/README.md). Use
`--verifier mock --allow-mock` only for offline development of the
orchestration logic itself -- it does NOT perform real formal
verification (see mathf/verifiers/mock_verifier.py).
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from mathf.core.dataset import load_dataset, validate_dataset  # noqa: E402
from mathf.core.models import ExperimentConfig  # noqa: E402
from mathf.core.runner import ExperimentRunner  # noqa: E402
from mathf.evaluation.failure_analysis import analyze_failures, format_failure_report  # noqa: E402
from mathf.evaluation.metrics import compute_metrics, format_metrics_report  # noqa: E402
from mathf.generators.tactic_search import FixedTacticSearchGenerator  # noqa: E402
from mathf.verifiers.lean_verifier import LeanVerifier  # noqa: E402
from mathf.verifiers.mock_verifier import MockLeanVerifier  # noqa: E402

GENERATOR_REGISTRY = {
    "fixed_tactic_search": lambda: FixedTacticSearchGenerator(),
}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the MATH-F V1 experiment.")
    p.add_argument("--config", default=str(REPO_ROOT / "configs" / "default.yaml"))
    p.add_argument("--dataset", default=None, help="Override dataset_path from config")
    p.add_argument("--generator", default=None, choices=list(GENERATOR_REGISTRY.keys()))
    p.add_argument("--verifier", default=None, choices=["lean", "mock"])
    p.add_argument(
        "--allow-mock",
        action="store_true",
        help="Required alongside --verifier mock. Without it, the mock verifier is refused, "
        "so a mock (non-real) run can never happen silently.",
    )
    p.add_argument("--max-attempts", type=int, default=None)
    p.add_argument("--timeout-seconds", type=int, default=None)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--results-dir", default=None)
    p.add_argument("--lean-project-dir", default=None)
    p.add_argument("--check-lean", action="store_true", help="Run a Lean+Mathlib sanity check and exit")
    return p


def load_config(path: str) -> ExperimentConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    fields = {f for f in ExperimentConfig.__dataclass_fields__}
    kwargs = {k: v for k, v in raw.items() if k in fields}
    return ExperimentConfig(**kwargs)


def apply_overrides(config: ExperimentConfig, args: argparse.Namespace) -> ExperimentConfig:
    if args.dataset:
        config.dataset_path = args.dataset
    if args.verifier:
        config.verifier_name = args.verifier
    if args.generator:
        config.generator_name = args.generator
    if args.max_attempts:
        config.max_attempts = args.max_attempts
    if args.timeout_seconds:
        config.timeout_seconds = args.timeout_seconds
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.results_dir:
        config.results_dir = args.results_dir
    if args.lean_project_dir:
        config.lean_project_dir = args.lean_project_dir
    return config


def get_lean_version(lean_project_dir: str) -> str:
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", "--version"],
            cwd=lean_project_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return (proc.stdout or proc.stderr).strip() or "unknown"
    except Exception as e:  # noqa: BLE001
        return f"unavailable ({e})"


def build_verifier(config: ExperimentConfig, allow_mock: bool):
    if config.verifier_name == "mock":
        if not allow_mock:
            print(
                "ERROR: --verifier mock requires --allow-mock. The mock verifier is NOT a "
                "real formal verifier (see mathf/verifiers/mock_verifier.py) and must never "
                "be used silently.",
                file=sys.stderr,
            )
            sys.exit(2)
        return MockLeanVerifier()
    if config.verifier_name == "lean":
        return LeanVerifier(
            lean_project_dir=str(REPO_ROOT / config.lean_project_dir),
            timeout_seconds=config.timeout_seconds,
        )
    raise ValueError(f"Unknown verifier_name: {config.verifier_name}")


def main() -> int:
    args = build_arg_parser().parse_args()
    config = load_config(args.config)
    config = apply_overrides(config, args)

    if not Path(config.lean_project_dir).is_absolute():
        config.lean_project_dir = str(REPO_ROOT / config.lean_project_dir)
    if not Path(config.dataset_path).is_absolute():
        config.dataset_path = str(REPO_ROOT / config.dataset_path)
    if not Path(config.output_dir).is_absolute():
        config.output_dir = str(REPO_ROOT / config.output_dir)
    if not Path(config.results_dir).is_absolute():
        config.results_dir = str(REPO_ROOT / config.results_dir)

    verifier = build_verifier(config, args.allow_mock)

    if args.check_lean:
        if not isinstance(verifier, LeanVerifier):
            print("--check-lean only applies to the real Lean verifier.", file=sys.stderr)
            return 2
        result = verifier.check_environment()
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0 if result.verified else 1

    problems = load_dataset(config.dataset_path)
    valid, issues = validate_dataset(problems)
    if not valid:
        print("Dataset validation FAILED:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 2

    generator = GENERATOR_REGISTRY[config.generator_name]()

    print(f"Experiment ID:  {config.experiment_id}")
    print(f"Dataset:        {config.dataset_path} ({len(problems)} problems)")
    print(f"Generator:      {generator.name}")
    print(f"Verifier:       {verifier.name}{'  [MOCK - NOT real verification]' if config.verifier_name == 'mock' else ''}")
    print(f"Max attempts:   {config.max_attempts}")
    print(f"Timeout (s):    {config.timeout_seconds}")
    print()

    runner = ExperimentRunner(generator=generator, verifier=verifier, config=config)

    start = time.time()
    trajectories = runner.run_dataset(problems, save=True)
    wall_clock = time.time() - start

    traj_dicts = [t.to_dict() for t in trajectories]
    metrics = compute_metrics(traj_dicts, max_attempts=config.max_attempts)
    failure_report = analyze_failures(traj_dicts)

    reproducibility = {
        "experiment_id": config.experiment_id,
        "timestamp": time.time(),
        "dataset_path": config.dataset_path,
        "dataset_version": config.dataset_version,
        "generator": generator.name,
        "verifier": verifier.name,
        "verifier_is_mock": config.verifier_name == "mock",
        "configuration": config.to_dict(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "lean_version": (
            get_lean_version(config.lean_project_dir) if isinstance(verifier, LeanVerifier) else "n/a (mock verifier)"
        ),
        "wall_clock_seconds": wall_clock,
    }

    results_dir = Path(config.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"experiment_{config.experiment_id}.json"
    out_path.write_text(
        json.dumps(
            {
                "reproducibility": reproducibility,
                "metrics": metrics,
                "failure_analysis": failure_report,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(format_metrics_report(metrics))
    print()
    print(format_failure_report(failure_report))
    print()
    print(f"Full results written to: {out_path}")
    print(f"Trajectories written to: {config.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
