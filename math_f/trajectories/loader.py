"""Read-only helpers for consuming trajectories already on disk. Never
writes anything -- `raw/` is the evidence of record (spec section 34).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator, List, Optional, Set

_ATTEMPT_RE = re.compile(r"^(?P<trajectory_id>.+)_attempt_(?P<attempt>\d+)\.json$")
_FINAL_SUFFIX = "_final.json"


def _raw_dir(run_dir) -> Path:
    return Path(run_dir) / "raw" / "trajectories"


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def iter_final_records(run_dir) -> Iterator[dict]:
    for path in sorted(_raw_dir(run_dir).glob(f"*{_FINAL_SUFFIX}")):
        record = _load_json(path)
        if record is not None:
            yield record


def iter_attempt_records(run_dir, trajectory_id: Optional[str] = None) -> Iterator[dict]:
    records: List[dict] = []
    for path in _raw_dir(run_dir).glob("*_attempt_*.json"):
        match = _ATTEMPT_RE.match(path.name)
        if not match:
            continue
        if trajectory_id is not None and match.group("trajectory_id") != trajectory_id:
            continue
        record = _load_json(path)
        if record is not None:
            records.append(record)
    records.sort(key=lambda r: (r.get("trajectory_id", ""), r.get("attempt", 0)))
    yield from records


def completed_trajectory_ids(run_dir) -> Set[str]:
    """Trajectory IDs that reached a *final* (VERIFIED or ABSTAIN) outcome.

    Used by `--resume` to skip already-completed tasks. A trajectory that
    only has attempt files but no final file (e.g. the run was interrupted
    mid-task, or it was the task that triggered a malformed/infrastructure
    abort) is deliberately NOT considered complete and will be retried.
    """
    ids = set()
    for path in _raw_dir(run_dir).glob(f"*{_FINAL_SUFFIX}"):
        ids.add(path.name[: -len(_FINAL_SUFFIX)])
    return ids


def load_config(run_dir) -> Optional[dict]:
    return _load_json(Path(run_dir) / "metadata" / "config.json")


def load_run_status(run_dir) -> Optional[dict]:
    return _load_json(Path(run_dir) / "metadata" / "run_status.json")


def list_abort_events(run_dir) -> List[dict]:
    aborts_dir = Path(run_dir) / "metadata" / "aborts"
    if not aborts_dir.exists():
        return []
    events = []
    for path in sorted(aborts_dir.glob("*.json")):
        record = _load_json(path)
        if record is not None:
            events.append(record)
    return events
