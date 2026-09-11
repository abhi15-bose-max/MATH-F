"""ID helpers.

Trajectory IDs are made a *deterministic* function of (split, task_id)
rather than random, so that `--resume` can detect already-completed work
purely by re-deriving the ID and checking whether a final record exists on
disk -- no separate task->trajectory-id mapping file is needed.
"""
from __future__ import annotations

import re
import time
import uuid

_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def trajectory_id_for_task(split: str, task_id: str) -> str:
    safe_split = _SAFE_RE.sub("_", split.strip())
    safe_task = _SAFE_RE.sub("_", task_id.strip())
    return f"{safe_split}__{safe_task}"


def new_experiment_id() -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    return f"{stamp}_{uuid.uuid4().hex[:8]}"
