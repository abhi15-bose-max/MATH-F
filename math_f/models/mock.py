"""Deterministic model backends that require no GPU, no network, and no
model download. Used by the test suite, and by `smoke-test`/`--backend
mock` for infrastructure checks that shouldn't depend on a real checkpoint.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Union

from .base import CandidateModel, GenerationResult

# Known-correct tactic bodies for the bundled offline sample fixtures
# (math_f/datasets/data/minif2f_sample.jsonl). MockModel "solves" these on
# the second attempt to exercise the repair loop end-to-end without a real
# checkpoint. It intentionally does NOT know how to solve arbitrary miniF2F
# problems -- that would defeat the point of using the real model/Lean pair.
_KNOWN_SOLUTIONS = {
    "sample_nat_add_comm": "  exact Nat.add_comm a b",
    "sample_two_plus_two": "  decide",
    "sample_list_length": "  decide",
}


def _task_name_from_prompt(prompt: str) -> Optional[str]:
    for name in _KNOWN_SOLUTIONS:
        if name in prompt:
            return name
    return None


class MockModel(CandidateModel):
    """Fails once (emits `sorry`), then emits a plausible repair.

    For unrecognized tasks (i.e. anything outside the bundled sample
    fixtures) it keeps emitting a generic, likely-insufficient tactic so the
    repair loop realistically runs out of attempts and ABSTAINs -- it never
    fabricates a pass.
    """

    model_name = "mock"
    model_revision = None

    def __init__(self) -> None:
        self._calls = 0

    def generate(self, prompt: str) -> GenerationResult:
        self._calls += 1
        is_repair = "REPAIR TASK" in prompt
        task_name = _task_name_from_prompt(prompt)

        if not is_repair:
            raw = "```lean4\n  sorry\n```"
        elif task_name is not None:
            raw = f"```lean4\n{_KNOWN_SOLUTIONS[task_name]}\n```"
        else:
            raw = "```lean4\n  simp\n```"

        return GenerationResult(raw_text=raw, input_tokens=len(prompt.split()), output_tokens=len(raw.split()))


class ScriptedModel(CandidateModel):
    """Returns a pre-scripted sequence of raw outputs, one per call.

    Used by unit tests to force specific attempt sequences (malformed
    output, duplicate candidates, FAIL-then-PASS, all-FAIL, etc.) without
    depending on any real inference.
    """

    model_name = "scripted"
    model_revision = None

    def __init__(self, outputs: Union[List[str], Callable[[int], str]]) -> None:
        self._outputs = outputs
        self._index = 0

    def generate(self, prompt: str) -> GenerationResult:
        if callable(self._outputs):
            raw = self._outputs(self._index + 1)
        else:
            if self._index >= len(self._outputs):
                raise IndexError(
                    f"ScriptedModel exhausted: only {len(self._outputs)} outputs scripted "
                    f"but generate() was called a {self._index + 1}th time."
                )
            raw = self._outputs[self._index]
        self._index += 1
        return GenerationResult(raw_text=raw, input_tokens=len(prompt.split()), output_tokens=len(str(raw).split()))
