"""
Dataset loading for FormalMathProblem collections.

Kept deliberately tiny: the orchestration layer only ever needs a
`List[FormalMathProblem]`, regardless of whether it came from the small
V1 development benchmark, a future miniF2F import, or a custom dataset
(MASTER PROMPT section 8). Format-specific importers (e.g. a future
`from_minif2f.py`) should live alongside this file and all funnel into
`FormalMathProblem`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

from mathf.core.models import FormalMathProblem


def load_dataset(path: str) -> List[FormalMathProblem]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "problems" in raw:
        raw = raw["problems"]
    if not isinstance(raw, list):
        raise ValueError(f"Dataset at {path} must be a JSON list of problems (or {{'problems': [...]}})")
    return [FormalMathProblem.from_dict(item) for item in raw]


def validate_dataset(problems: List[FormalMathProblem]) -> Tuple[bool, List[str]]:
    """Returns (all_valid, list_of_human_readable_problems)."""
    issues: List[str] = []
    seen_ids = set()
    for p in problems:
        for err in p.validate():
            issues.append(f"{p.problem_id or '<missing id>'}: {err}")
        if p.problem_id in seen_ids:
            issues.append(f"{p.problem_id}: duplicate problem_id in dataset")
        seen_ids.add(p.problem_id)
    return (len(issues) == 0, issues)
