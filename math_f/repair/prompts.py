"""Prompt construction for the generate/repair loop.

Hard rule (spec section 11): the model receives the problem, its own
previous candidate, and the Lean verifier's feedback -- and nothing else.
There is no reference/gold proof anywhere in this module or in `Task`
(`math_f.datasets.minif2f.Task` simply has no field for one), so it cannot
be leaked even by a coding mistake here.

No hidden chain-of-thought is requested (spec section 35): the model is
asked for a proof, not an explanation of its reasoning.
"""
from __future__ import annotations

from typing import Optional

SYSTEM_INSTRUCTIONS = """You are a Lean 4 theorem-proving assistant.

You will be given a formal theorem statement. Your job is to produce a
complete Lean 4 proof for it.

Lean is the ONLY authority on correctness. You must never claim that a
proof is verified, correct, or complete -- the external Lean checker
decides that, not you.

OUTPUT CONTRACT
Return the complete, self-contained Lean 4 code for the theorem: repeat
the exact theorem statement you were given and follow it with a full
proof (tactic-mode `by ...` or term-mode `:=`). Put it in a single fenced
code block:

```lean4
<the complete theorem statement followed by its proof>
```

Do not include any text outside the fenced code block. Do not change the
theorem's name, arguments, or conclusion. Do not use `sorry` or `admit`.
Do not explain your reasoning outside the proof itself."""


def _task_block(task) -> str:
    lines = [
        "THEOREM",
        f"Task ID: {task.task_id}",
    ]
    if task.informal_statement:
        lines.append(f"Informal statement: {task.informal_statement}")
    if task.header:
        lines.append("Header (imports/options, already in scope):")
        lines.append(task.header)
    lines.append("Formal statement to prove:")
    lines.append("```lean4")
    lines.append(task.theorem_statement)
    lines.append("```")
    return "\n".join(lines)


def build_initial_prompt(task) -> str:
    return (
        SYSTEM_INSTRUCTIONS
        + "\n\n"
        + _task_block(task)
        + "\n\nTASK\nGenerate a complete Lean 4 proof for the theorem above. "
        "Return ONLY the fenced ```lean4``` code block."
    )


def summarize_verifier_result(verifier_result: dict) -> str:
    """A compact, human/model-readable summary of a Lean verifier result,
    used both to build the next repair prompt and to persist in the
    trajectory as an audit trail of the feedback the model was given.
    """
    lines = [
        f"status: {verifier_result.get('status')}",
        f"failure_class: {verifier_result.get('failure_class')}",
        f"exit_code: {verifier_result.get('exit_code')}",
    ]
    diagnostics = verifier_result.get("diagnostics") or []
    if diagnostics:
        lines.append("diagnostics:")
        for d in diagnostics[:20]:  # cap to keep prompts bounded
            lines.append(
                f"  - {d.get('severity')} at line {d.get('line')}, col {d.get('column')}: "
                f"{d.get('message')}"
            )
    else:
        stderr = (verifier_result.get("stderr") or "").strip()
        if stderr:
            lines.append("stderr:")
            lines.append(stderr[:2000])
    return "\n".join(lines)


def build_repair_prompt(
    task,
    previous_candidate: Optional[str],
    verifier_result: dict,
    attempt: int,
    max_attempts: int,
) -> str:
    feedback = summarize_verifier_result(verifier_result)
    return (
        SYSTEM_INSTRUCTIONS
        + "\n\n"
        + _task_block(task)
        + "\n\nPREVIOUS CANDIDATE (attempt "
        + str(attempt - 1)
        + f" of {max_attempts})\n```lean4\n"
        + (previous_candidate or "")
        + "\n```"
        + "\n\nLEAN VERIFIER RESULT\n"
        + feedback
        + "\n\nREPAIR TASK\n"
        "The previous candidate above was independently checked by Lean and "
        "rejected. Using the verifier feedback, produce a corrected, complete "
        "Lean 4 proof for the SAME theorem statement (do not change the "
        "statement). Do not claim the proof is verified. Do not use `sorry`. "
        f"This is attempt {attempt} of {max_attempts}.\n\n"
        "Return ONLY the fenced ```lean4``` code block."
    )
