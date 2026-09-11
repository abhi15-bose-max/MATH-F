"""Persists trajectories to disk immediately, one file per attempt (spec
section 13/24). Writes are atomic (write-to-temp then os.replace) so a
crash mid-write can never leave a corrupt/partial JSON file behind --
important for a process that may be killed by Colab at any moment.

Directory layout under a run directory (spec section 34):

    runs/<experiment_id>/
        raw/trajectories/
            <trajectory_id>_attempt_<n>.json
            <trajectory_id>_final.json
        summaries/
            summary.json, summary.csv, summary.md
        logs/
            run.log
        metadata/
            config.json
            environment_latest.json, environment_<timestamp>.json
            run_status.json
            aborts/<timestamp>.json

Raw trajectory files are never modified or deleted by anything in this
repository once written (spec section 34) -- summaries are always derived
fresh from them.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class TrajectoryWriter:
    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.raw_dir = self.run_dir / "raw" / "trajectories"
        self.summaries_dir = self.run_dir / "summaries"
        self.logs_dir = self.run_dir / "logs"
        self.metadata_dir = self.run_dir / "metadata"
        self.aborts_dir = self.metadata_dir / "aborts"
        for d in (self.raw_dir, self.summaries_dir, self.logs_dir, self.metadata_dir, self.aborts_dir):
            d.mkdir(parents=True, exist_ok=True)

    # -- attempts / finals -------------------------------------------------
    def attempt_path(self, trajectory_id: str, attempt: int) -> Path:
        return self.raw_dir / f"{trajectory_id}_attempt_{attempt}.json"

    def final_path(self, trajectory_id: str) -> Path:
        return self.raw_dir / f"{trajectory_id}_final.json"

    def write_attempt(self, attempt_record: dict) -> Path:
        path = self.attempt_path(attempt_record["trajectory_id"], attempt_record["attempt"])
        _atomic_write_json(path, attempt_record)
        return path

    def write_final(self, final_record: dict) -> Path:
        path = self.final_path(final_record["trajectory_id"])
        _atomic_write_json(path, final_record)
        return path

    def attempt_exists(self, trajectory_id: str, attempt: int) -> bool:
        return self.attempt_path(trajectory_id, attempt).exists()

    def final_exists(self, trajectory_id: str) -> bool:
        return self.final_path(trajectory_id).exists()

    # -- run-level metadata --------------------------------------------------
    def write_config(self, config_dict: dict, overwrite: bool = False) -> Path:
        path = self.metadata_dir / "config.json"
        if path.exists() and not overwrite:
            return path
        _atomic_write_json(path, config_dict)
        return path

    def write_environment(self, env_dict: dict) -> None:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        _atomic_write_json(self.metadata_dir / f"environment_{stamp}.json", env_dict)
        _atomic_write_json(self.metadata_dir / "environment_latest.json", env_dict)

    def write_run_status(self, status_dict: dict) -> None:
        _atomic_write_json(self.metadata_dir / "run_status.json", status_dict)

    def write_abort_marker(self, kind: str, reason: str, trajectory_id: Optional[str] = None,
                            task_id: Optional[str] = None, attempt: Optional[int] = None) -> Path:
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": kind,
            "trajectory_id": trajectory_id,
            "task_id": task_id,
            "attempt": attempt,
            "reason": reason,
        }
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        path = self.aborts_dir / f"{stamp}_{kind}.json"
        _atomic_write_json(path, record)
        return path
