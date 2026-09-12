"""
Trajectory recording and persistence.

A trajectory captures EVERY candidate and EVERY verification result for
one problem's run, never just the final successful proof (MASTER
PROMPT section 15). This module is intentionally the only place that
knows how a Trajectory gets written to / read from disk, so the JSON
shape can evolve in one place.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from mathf.core.models import Attempt, Candidate, Trajectory, VerificationResult


class DuplicateTracker:
    """Detects exact duplicate candidate proofs within a single
    trajectory. Duplicates are recorded, never silently discarded
    (MASTER PROMPT section 17), and never themselves cause an infinite
    loop -- the runner's global max_attempts remains authoritative
    regardless of what this class reports."""

    def __init__(self):
        self._seen: Dict[str, int] = {}  # normalized proof hash -> attempt number

    @staticmethod
    def _normalize(proof: str) -> str:
        return " ".join(proof.strip().split())

    @staticmethod
    def _hash(proof: str) -> str:
        return hashlib.sha256(DuplicateTracker._normalize(proof).encode("utf-8")).hexdigest()

    def check_and_record(self, attempt_number: int, proof: str) -> Optional[int]:
        """Returns the earlier attempt number this proof duplicates, or
        None if this proof text has not been seen before in this
        trajectory. Always records the current attempt afterward."""
        h = self._hash(proof)
        earlier = self._seen.get(h)
        if earlier is None:
            self._seen[h] = attempt_number
        return earlier


def save_trajectory(trajectory: Trajectory, output_dir: str) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{trajectory.problem_id}_{trajectory.trajectory_id}.json"
    path.write_text(json.dumps(trajectory.to_dict(), indent=2, default=str), encoding="utf-8")
    return path


def load_trajectory(path: str) -> dict:
    """Loads a trajectory back as a plain dict (JSON round-trip). We
    intentionally return a dict rather than reconstructing dataclasses
    with enums, since trajectories are read-only experiment artifacts
    consumed by evaluation code that only needs plain data."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_all_trajectories(directory: str) -> List[dict]:
    out = []
    for p in sorted(Path(directory).glob("*.json")):
        out.append(load_trajectory(str(p)))
    return out
