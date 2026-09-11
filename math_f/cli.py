"""Command-line interface.

    python -m math_f evaluate --split test --max-attempts 5 --output runs/experiment_001
    python -m math_f smoke-test
    python -m math_f verify --candidate-file proof.lean --task-id sample_two_plus_two --split sample
    python -m math_f stats --input runs/experiment_001
    python -m math_f resume --input runs/experiment_001
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from math_f.config import ExperimentConfig, apply_env_overrides, apply_overrides
from math_f.datasets.minif2f import load_tasks, load_sample_tasks
from math_f.evaluation.metrics import compute_metrics
from math_f.evaluation.reports import render_markdown_table, write_reports
from math_f.generation.output_cleaner import clean_model_output
from math_f.logging_utils import setup_logging
from math_f.models.build import build_model
from math_f.repair.loop import MalformedOutputAbort, RepairLoop
from math_f.repair.prompts import build_initial_prompt
from math_f.trajectories.loader import completed_trajectory_ids, load_config
from math_f.trajectories.writer import TrajectoryWriter
from math_f.utils.env_check import full_environment_report
from math_f.utils.ids import new_experiment_id, trajectory_id_for_task
from math_f.verification.lean_runner import LeanInfrastructureError, run_lean


# --------------------------------------------------------------------------
# shared config construction
# --------------------------------------------------------------------------
def _build_config(args) -> ExperimentConfig:
    config = ExperimentConfig.load(getattr(args, "config", None))
    config = apply_env_overrides(config)

    overrides = {}
    if getattr(args, "model_name", None):
        overrides["model.name"] = args.model_name
    if getattr(args, "model_backend", None):
        overrides["model.backend"] = args.model_backend
    if getattr(args, "model_revision", None):
        overrides["model.revision"] = args.model_revision
    if getattr(args, "max_attempts", None) is not None:
        overrides["evaluation.max_attempts"] = args.max_attempts
    if getattr(args, "split", None):
        overrides["evaluation.split"] = args.split
    if getattr(args, "dataset_name", None):
        overrides["evaluation.dataset_name"] = args.dataset_name
    if getattr(args, "limit", None) is not None:
        overrides["evaluation.limit"] = args.limit
    if getattr(args, "timeout", None) is not None:
        overrides["verification.timeout_seconds"] = args.timeout
    if getattr(args, "lean_project_dir", None):
        overrides["verification.lean_project_dir"] = args.lean_project_dir
    apply_overrides(config, overrides)
    return config


# --------------------------------------------------------------------------
# evaluate / resume shared core
# --------------------------------------------------------------------------
def _make_on_attempt(writer: TrajectoryWriter, logger):
    def on_attempt(attempt_record: dict) -> None:
        writer.write_attempt(attempt_record)
        verification = attempt_record.get("verification") or {}
        status = verification.get("status")
        failure_class = verification.get("failure_class")
        suffix = f" ({failure_class})" if status != "PASS" and failure_class else ""
        logger.info(f"  Attempt {attempt_record['attempt']} -> {status}{suffix}")

    return on_attempt


def _run_evaluation(config: ExperimentConfig, run_dir: Path, resume: bool) -> int:
    writer = TrajectoryWriter(run_dir)
    logger = setup_logging(writer.logs_dir / "run.log")

    stored_config = load_config(run_dir) if resume else None
    if resume and stored_config is not None:
        logger.info(f"Resuming run at {run_dir} using its stored configuration.")
        config = ExperimentConfig.from_dict(stored_config)
    writer.write_config(config.to_dict(), overwrite=not resume)

    logger.info("Experiment started" if not resume else "Experiment resumed")
    logger.info(
        f"Model: {config.model.name} (backend={config.model.backend}) | "
        f"Dataset: {config.evaluation.dataset_name} split={config.evaluation.split} | "
        f"Max attempts: {config.evaluation.max_attempts}"
    )

    env_report = full_environment_report(config)
    writer.write_environment(env_report)
    if not env_report["lean"].get("available"):
        logger.info(
            "[WARN] Lean was not detected on PATH. Verification will raise an "
            "infrastructure error and abort the run as soon as a task needs it."
        )

    try:
        tasks = load_tasks(
            dataset_name=config.evaluation.dataset_name,
            split=config.evaluation.split,
            limit=config.evaluation.limit,
            shuffle=config.evaluation.shuffle,
            random_seed=config.evaluation.random_seed,
        )
    except Exception as e:
        logger.critical(f"Could not load dataset: {e}")
        writer.write_run_status({"status": "ABORTED", "abort_reason": "dataset_load_error", "detail": str(e)})
        return 1

    logger.info(f"Loaded {len(tasks)} task(s).")

    if resume:
        done = completed_trajectory_ids(run_dir)
        remaining = [t for t in tasks if trajectory_id_for_task(t.split, t.task_id) not in done]
        logger.info(f"Resume: {len(tasks) - len(remaining)} already completed, {len(remaining)} remaining.")
        tasks = remaining

    try:
        model = build_model(config.model)
    except Exception as e:
        logger.critical(f"Could not build model backend '{config.model.backend}': {e}")
        writer.write_run_status({"status": "ABORTED", "abort_reason": "model_load_error", "detail": str(e)})
        return 1

    model_meta = {
        "name": config.model.name if config.model.backend != "mock" else "mock",
        "revision": config.model.revision,
        "temperature": config.model.temperature,
        "max_new_tokens": config.model.max_new_tokens,
    }

    loop = RepairLoop(
        model=model,
        model_meta=model_meta,
        max_attempts=config.evaluation.max_attempts,
        lean_cmd=config.verification.lean_cmd,
        lean_project_dir=config.verification.lean_project_dir,
        timeout_seconds=config.verification.timeout_seconds,
        duplicate_detection=config.evaluation.duplicate_detection,
    )
    on_attempt = _make_on_attempt(writer, logger)

    stop = {"flag": False}

    def _signal_handler(signum, frame):
        logger.info(f"Received signal {signum}; will stop after the current task and flush results.")
        stop["flag"] = True

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except (ValueError, OSError):
        pass  # not in main thread / unsupported platform; best effort only

    run_aborted = False
    abort_reason: Optional[str] = None
    infra_consecutive = 0
    processed = 0
    total = len(tasks)

    for i, task in enumerate(tasks, start=1):
        if stop["flag"]:
            logger.info("Stopping before next task due to interrupt.")
            break

        trajectory_id = trajectory_id_for_task(task.split, task.task_id)
        logger.info(f"Task {i}/{total}: {trajectory_id}")

        try:
            outcome = loop.run_task(task, trajectory_id, on_attempt=on_attempt)
            writer.write_final(outcome.to_dict())
            infra_consecutive = 0
            processed += 1
            if outcome.success:
                logger.info(f"  -> VERIFIED on attempt {outcome.success_on_attempt}")
            else:
                logger.info(f"  -> ABSTAIN after {outcome.attempts_used} attempt(s)")
        except MalformedOutputAbort as e:
            logger.critical("MALFORMED CANDIDATE")
            logger.critical(f"trajectory_id={e.trajectory_id}")
            logger.critical(f"reason={e.reason}")
            logger.critical("Run aborted intentionally.")
            writer.write_abort_marker(
                "malformed_candidate", e.reason, trajectory_id=e.trajectory_id,
                task_id=e.task_id, attempt=e.attempt,
            )
            run_aborted = True
            abort_reason = "malformed_candidate"
            break
        except LeanInfrastructureError as e:
            if not e.retryable:
                logger.critical(f"INFRASTRUCTURE FAILURE: {e}")
                logger.critical("Run aborted intentionally.")
                writer.write_abort_marker(
                    "infrastructure_error", str(e), trajectory_id=trajectory_id, task_id=task.task_id
                )
                run_aborted = True
                abort_reason = "infrastructure_error"
                break
            infra_consecutive += 1
            logger.critical(
                f"INFRASTRUCTURE FAILURE ({infra_consecutive}/"
                f"{config.verification.max_consecutive_infra_failures} consecutive, retryable): {e}"
            )
            if infra_consecutive >= config.verification.max_consecutive_infra_failures:
                logger.critical("Repeated infrastructure failures. Run aborted intentionally.")
                writer.write_abort_marker(
                    "infrastructure_error",
                    f"{infra_consecutive} consecutive retryable failures; last error: {e}",
                    trajectory_id=trajectory_id, task_id=task.task_id,
                )
                run_aborted = True
                abort_reason = "infrastructure_error"
                break
            logger.info("Continuing to next task (this task was left incomplete and will retry on --resume).")
            continue

    if run_aborted:
        status = "ABORTED"
    elif stop["flag"]:
        status = "INTERRUPTED"
    else:
        status = "COMPLETED"

    writer.write_run_status(
        {
            "status": status,
            "abort_reason": abort_reason,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tasks_total_this_invocation": total,
            "tasks_processed_this_invocation": processed,
        }
    )
    logger.info(f"Run status: {status}")

    metrics = compute_metrics(run_dir, max_attempts=config.evaluation.max_attempts)
    paths = write_reports(run_dir, metrics)
    logger.info(f"Reports written to {paths['json'].parent}")
    print()
    print(render_markdown_table(metrics))
    print()
    print(f"Results saved at: {run_dir}")

    return 1 if run_aborted else 0


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------
def cmd_evaluate(args) -> int:
    config = _build_config(args)
    if args.output:
        run_dir = Path(args.output)
    else:
        run_dir = Path(config.output.directory) / new_experiment_id()
    config.experiment_id = run_dir.name
    return _run_evaluation(config, run_dir, resume=args.resume)


def cmd_resume(args) -> int:
    run_dir = Path(args.input)
    stored = load_config(run_dir)
    if stored is None:
        print(f"No metadata/config.json found under {run_dir}; cannot resume.", file=sys.stderr)
        return 1
    config = ExperimentConfig.from_dict(stored)
    if args.max_attempts is not None:
        config.evaluation.max_attempts = args.max_attempts
    return _run_evaluation(config, run_dir, resume=True)


def cmd_stats(args) -> int:
    run_dir = Path(args.input)
    stored = load_config(run_dir)
    max_attempts = stored["evaluation"]["max_attempts"] if stored else None
    metrics = compute_metrics(run_dir, max_attempts=max_attempts)
    print(render_markdown_table(metrics))
    if args.json:
        print()
        print(json.dumps(metrics, indent=2))
    if args.write:
        paths = write_reports(run_dir, metrics)
        print(f"\nReports written to {paths['json'].parent}")
    return 0


def cmd_verify(args) -> int:
    config = _build_config(args)

    if args.candidate_file:
        raw = Path(args.candidate_file).read_text(encoding="utf-8")
    elif args.candidate:
        raw = args.candidate
    else:
        print("Provide --candidate or --candidate-file.", file=sys.stderr)
        return 2

    header = ""
    if args.header_file:
        header = Path(args.header_file).read_text(encoding="utf-8")
    elif args.task_id:
        tasks = load_tasks(
            dataset_name=config.evaluation.dataset_name,
            split=args.split or "sample",
        )
        matches = [t for t in tasks if t.task_id == args.task_id]
        if not matches:
            print(f"Task '{args.task_id}' not found in split '{args.split or 'sample'}'.", file=sys.stderr)
            return 2
        header = matches[0].header

    clean_result = clean_model_output(raw)
    if clean_result.is_malformed:
        print(json.dumps({"status": "MALFORMED", "reason": clean_result.reason}, indent=2))
        return 1

    result = run_lean(
        header=header,
        candidate=clean_result.cleaned_candidate,
        lean_cmd=config.verification.lean_cmd,
        lean_project_dir=config.verification.lean_project_dir,
        timeout_seconds=config.verification.timeout_seconds,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


def _check(ok: Optional[bool], label: str, detail: str = "") -> bool:
    mark = "SKIPPED" if ok is None else ("PASS" if ok else "FAIL")
    symbol = "-" if ok is None else ("\u2713" if ok else "\u2717")
    print(f"[{symbol}] {label}: {mark}" + (f" -- {detail}" if detail else ""))
    return bool(ok)


def cmd_smoke_test(args) -> int:
    from math_f.utils import env_check

    print("MATH-F smoke test")
    print("=" * 60)
    fatal_ok = True

    _check(True, "Python environment", env_check.python_info()["version"])

    torch_info = env_check.torch_info()
    _check(torch_info.get("available", False) or None, "PyTorch", torch_info.get("version", "not installed"))

    if torch_info.get("available"):
        cuda_ok = torch_info.get("cuda_available", False)
        detail = torch_info.get("gpu_name", "no GPU") if cuda_ok else "CUDA not available (CPU only)"
        _check(cuda_ok or None, "CUDA", detail)
        _check(cuda_ok or None, "GPU", torch_info.get("gpu_name", "n/a"))
    else:
        _check(None, "CUDA", "skipped (no torch)")
        _check(None, "GPU", "skipped (no torch)")

    transformers_info = env_check.transformers_info()
    _check(
        transformers_info.get("available", False) or None,
        "Transformers",
        transformers_info.get("version", "not installed"),
    )

    config = _build_config(args)
    backend = args.backend or config.model.backend
    config.model.backend = backend

    model = None
    if backend == "mock":
        from math_f.models.mock import MockModel

        model = MockModel()
        _check(None, "Model loading", "skipped (mock backend)")
        _check(None, "Tokenizer", "skipped (mock backend)")
    else:
        try:
            model = build_model(config.model)
            ok = _check(True, "Model loading", config.model.name)
            _check(True, "Tokenizer", "loaded with model")
            fatal_ok = fatal_ok and ok
        except Exception as e:
            _check(False, "Model loading", str(e))
            _check(False, "Tokenizer", "not reached")
            fatal_ok = False

    lean_info = env_check.lean_version(config.verification.lean_project_dir, config.verification.lean_cmd)
    lean_ok = lean_info.get("available", False)
    _check(lean_ok or None, "Lean executable", lean_info.get("version") or lean_info.get("reason", ""))

    mathlib_info = env_check.mathlib_info(config.verification.lean_project_dir)
    _check(
        mathlib_info.get("available", False) or None,
        "Mathlib",
        mathlib_info.get("rev") or mathlib_info.get("reason", ""),
    )

    sample_tasks = load_sample_tasks()[: max(1, args.tasks)]
    task = sample_tasks[0]

    raw_output = None
    try:
        prompt = build_initial_prompt(task)
        result = model.generate(prompt)
        raw_output = result.raw_text
        _check(True, "One theorem generation", f"{len(raw_output)} chars for task '{task.task_id}'")
    except Exception as e:
        _check(False, "One theorem generation", str(e))
        fatal_ok = False

    clean_result = None
    if raw_output is not None:
        clean_result = clean_model_output(raw_output)
        ok = clean_result.status in ("CLEANED", "PASSTHROUGH")
        _check(ok, "Candidate cleaner", clean_result.status)
        fatal_ok = fatal_ok and ok
    else:
        _check(False, "Candidate cleaner", "not reached")
        fatal_ok = False

    if lean_ok and clean_result is not None and clean_result.cleaned_candidate:
        try:
            verify_result = run_lean(
                header=task.header,
                candidate=clean_result.cleaned_candidate,
                lean_cmd=config.verification.lean_cmd,
                lean_project_dir=config.verification.lean_project_dir,
                timeout_seconds=config.verification.timeout_seconds,
            )
            _check(True, "Lean verification", f"returned status={verify_result['status']}")
        except LeanInfrastructureError as e:
            _check(False, "Lean verification", str(e))
    else:
        _check(None, "Lean verification", "skipped (Lean unavailable or no candidate)")

    try:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            writer = TrajectoryWriter(Path(tmp))
            writer.write_attempt(
                {"trajectory_id": "smoke_test", "attempt": 1, "verification": {"status": "FAIL"}}
            )
            ok = writer.attempt_exists("smoke_test", 1)
            _check(ok, "Trajectory writer", "round-trip write/read OK")
            fatal_ok = fatal_ok and ok
    except Exception as e:
        _check(False, "Trajectory writer", str(e))
        fatal_ok = False

    print("=" * 60)
    print("Overall: " + ("PASS" if fatal_ok else "FAIL"))
    return 0 if fatal_ok else 1


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------
def _add_common_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to a YAML/JSON experiment config file.")
    parser.add_argument("--model-name", help="Override MODEL_NAME.")
    parser.add_argument("--model-backend", choices=["hf", "mock"], help="Override model backend.")
    parser.add_argument("--model-revision", help="Specific model revision/commit.")
    parser.add_argument("--dataset-name", help="HF dataset name for real splits.")
    parser.add_argument("--timeout", type=int, help="Lean verification timeout, seconds.")
    parser.add_argument("--lean-project-dir", help="Directory of the Lean/Lake project with Mathlib.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="math_f")
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("evaluate", help="Run a (possibly overnight) evaluation.")
    _add_common_config_args(p_eval)
    p_eval.add_argument("--split", default=None, help="Dataset split: train/valid/test/sample.")
    p_eval.add_argument("--max-attempts", type=int, default=None)
    p_eval.add_argument("--limit", type=int, default=None, help="Only evaluate the first N tasks.")
    p_eval.add_argument("--output", required=True, help="Run directory, e.g. runs/experiment_001")
    p_eval.add_argument("--resume", action="store_true", help="Skip tasks already completed in --output.")
    p_eval.set_defaults(func=cmd_evaluate)

    p_smoke = sub.add_parser("smoke-test", help="Fast end-to-end infrastructure check.")
    _add_common_config_args(p_smoke)
    p_smoke.add_argument("--backend", choices=["hf", "mock"], default=None)
    p_smoke.add_argument("--tasks", type=int, default=1)
    p_smoke.set_defaults(func=cmd_smoke_test)

    p_verify = sub.add_parser("verify", help="Verify one candidate proof with Lean.")
    _add_common_config_args(p_verify)
    p_verify.add_argument("--candidate", help="Inline candidate text.")
    p_verify.add_argument("--candidate-file", help="Path to a file containing the candidate.")
    p_verify.add_argument("--header-file", help="Path to a file containing Lean imports/options.")
    p_verify.add_argument("--task-id", help="Look up header from a dataset task instead of --header-file.")
    p_verify.add_argument("--split", default=None, help="Split to look up --task-id in (default: sample).")
    p_verify.set_defaults(func=cmd_verify)

    p_stats = sub.add_parser("stats", help="Recompute metrics from a run directory's raw trajectories.")
    p_stats.add_argument("--input", required=True)
    p_stats.add_argument("--write", action="store_true", help="(Re)write summaries/summary.*")
    p_stats.add_argument("--json", action="store_true", help="Also print the full metrics JSON.")
    p_stats.set_defaults(func=cmd_stats)

    p_resume = sub.add_parser("resume", help="Resume an evaluation run using its stored config.")
    p_resume.add_argument("--input", required=True)
    p_resume.add_argument("--max-attempts", type=int, default=None)
    p_resume.set_defaults(func=cmd_resume)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
