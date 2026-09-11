"""miniF2F-style Lean 4 dataset loading.

Real evaluation splits ("train" / "valid" / "test") are loaded from the
Hugging Face dataset named by `evaluation.dataset_name` (default
`AI-MO/minif2f_test`, which follows the widely-used
name/split/informal_prefix/formal_statement/goal/header schema popularized
by DeepSeek-Prover / Kimina-Prover).

The special split "sample" always loads a tiny, bundled, locally-authored
fixture set (math_f/datasets/data/minif2f_sample.jsonl) that does not
depend on the network or on Mathlib being installed. It exists purely for
`smoke-test` and offline development -- it is explicitly NOT miniF2F data,
and its `source` field is always "local_sample" so it can never be confused
with real benchmark results (spec section 21: provenance must stay honest).
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_SAMPLE_PATH = Path(__file__).parent / "data" / "minif2f_sample.jsonl"


@dataclass(frozen=True)
class Task:
    task_id: str
    source: str
    split: str
    theorem_statement: str  # Lean 4 `theorem ... := by` (or `:=`) signature
    header: str  # imports / options that must precede the theorem
    informal_statement: str = ""
    goal: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "split": self.split,
            "theorem_statement": self.theorem_statement,
            "header": self.header,
            "informal_statement": self.informal_statement,
            "goal": self.goal,
        }


def _normalize_record(record: dict, source: str, split: str) -> Task:
    name = record.get("name") or record.get("task_id") or record.get("id")
    if not name:
        raise ValueError(f"Dataset record missing a name/task_id field: {record!r}")
    statement = record.get("formal_statement") or record.get("theorem_statement")
    if not statement:
        raise ValueError(f"Dataset record {name!r} missing formal_statement")
    return Task(
        task_id=str(name),
        source=record.get("source", source),
        split=record.get("split", split),
        theorem_statement=statement,
        header=record.get("header", "") or "",
        informal_statement=record.get("informal_prefix", "") or "",
        goal=record.get("goal", "") or "",
    )


def load_sample_tasks() -> List[Task]:
    tasks = []
    with _SAMPLE_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            tasks.append(_normalize_record(record, source="local_sample", split="sample"))
    return sorted(tasks, key=lambda t: t.task_id)


def load_tasks(
    dataset_name: str,
    split: str,
    limit: Optional[int] = None,
    shuffle: bool = False,
    random_seed: int = 0,
) -> List[Task]:
    """Load and normalize a dataset split into a deterministically ordered
    list of Task objects.

    `split == "sample"` bypasses the network entirely and loads the bundled
    fixture set (see module docstring). Any other split is loaded via the
    `datasets` library from `dataset_name`.
    """
    if split == "sample":
        tasks = load_sample_tasks()
    else:
        try:
            import datasets as hf_datasets
        except ImportError as e:
            raise RuntimeError(
                "The 'datasets' package is required to load real evaluation "
                "splits. Install it (see requirements.txt), or pass "
                "--split sample for an offline smoke test."
            ) from e

        try:
            ds = hf_datasets.load_dataset(dataset_name, split=split)
        except (ValueError, KeyError):
            # Some hosted copies expose a single split (often "test") and
            # store the actual train/valid/test split as a column instead of
            # a HF split. Fall back to that and filter client-side.
            full = hf_datasets.load_dataset(dataset_name)
            key = next(iter(full.keys()))
            ds = full[key].filter(lambda r: r.get("split") == split)

        tasks = [
            _normalize_record(dict(row), source=dataset_name, split=split) for row in ds
        ]
        tasks.sort(key=lambda t: t.task_id)  # deterministic ordering (spec section 22)

    if shuffle:
        rng = random.Random(random_seed)
        tasks = list(tasks)
        rng.shuffle(tasks)

    if limit is not None:
        tasks = tasks[:limit]

    return tasks
