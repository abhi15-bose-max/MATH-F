"""Deterministic model-output cleaner.

This module is one of the most important parts of the project (spec
section 4). It draws the line between:

  * a VALID candidate that Lean might still reject mathematically
    (a normal experimental failure -- retry), and
  * MALFORMED protocol output that cannot be turned into a candidate at all
    (a run-abort condition -- spec section 5).

Hard rules:
  * No LLM is ever used here. Every decision is a plain string operation.
  * The raw model output is never mutated in place; callers must keep it
    verbatim in the trajectory. This module only ever returns a *new*
    string (or None) derived from it.
  * Only unambiguous transport/wrapper artifacts are removed (markdown code
    fences, a handful of known prose preambles, stray leading/trailing
    whitespace, a `text'''...'''`-style wrapper). Nothing inside the
    extracted candidate body is ever rewritten, reordered, or regexed --
    Lean syntax, identifiers, unicode math symbols, parentheses, and
    indentation are passed through byte-for-byte (spec section 6).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

CleaningStatus = Literal["CLEANED", "PASSTHROUGH", "EMPTY", "MALFORMED"]

# A generous but finite ceiling protecting against runaway/pathological
# generations. This is a safety net, not a content edit.
_MAX_CANDIDATE_CHARS = 20_000

_FENCE_RE = re.compile(
    r"```(?:lean4|lean|Lean4|Lean)?\s*\n(?P<body>.*?)```",
    re.DOTALL,
)
_UNCLOSED_FENCE_RE = re.compile(r"```(?:lean4|lean|Lean4|Lean)?\s*\n")

_TEXT_QUOTE_RE = re.compile(r"^text'''(?P<body>.*)'''\s*$", re.DOTALL)

# Heuristics used only to decide whether bare (unwrapped) text plausibly
# *is* a Lean proof body, never to modify it. Note: "sorry" is deliberately
# excluded -- it is common enough in ordinary English apologies ("sorry,
# I can't help with that") that using it as a Lean signal produces false
# positives on genuinely malformed refusals.
_LEAN_MARKERS = (":=", " by", "\nby", "theorem", "lemma", "example")


@dataclass(frozen=True)
class CleanResult:
    cleaned_candidate: Optional[str]
    status: CleaningStatus
    reason: Optional[str] = None

    @property
    def is_malformed(self) -> bool:
        return self.status in ("MALFORMED", "EMPTY")


def _strip_text_quote_wrapper(text: str) -> str:
    match = _TEXT_QUOTE_RE.match(text.strip())
    if match:
        return match.group("body")
    return text


def _looks_like_lean(text: str) -> bool:
    return any(marker in text for marker in _LEAN_MARKERS)


def clean_model_output(raw_text: str) -> CleanResult:
    """Deterministically turn raw model text into a Lean candidate, or
    classify it as MALFORMED protocol output.
    """
    if raw_text is None:
        return CleanResult(None, "EMPTY", "Model output was None.")

    if not isinstance(raw_text, str):
        return CleanResult(None, "MALFORMED", f"Model output was not text (got {type(raw_text).__name__}).")

    text = raw_text.strip()
    if not text:
        return CleanResult(None, "EMPTY", "Model output was empty after stripping whitespace.")

    # Step 1: strip a `text'''...'''` transport wrapper if the *entire*
    # message is wrapped in one (safe/deterministic per spec section 4).
    unwrapped = _strip_text_quote_wrapper(text)
    was_text_quote_wrapped = unwrapped != text
    text = unwrapped.strip()
    if not text:
        return CleanResult(None, "EMPTY", "Output was empty after removing text''' wrapper.")

    # Step 2: look for a closed markdown fence.
    fence_matches = list(_FENCE_RE.finditer(text))
    if fence_matches:
        body = fence_matches[0].group("body").strip()
        if not body:
            return CleanResult(None, "MALFORMED", "Fenced code block was empty.")
        if len(body) > _MAX_CANDIDATE_CHARS:
            return CleanResult(None, "MALFORMED", f"Candidate exceeds {_MAX_CANDIDATE_CHARS} characters.")
        status: CleaningStatus = "CLEANED"
        return CleanResult(body, status, None)

    # Step 3: an *unclosed* fence is a malformed transport artifact, not a
    # candidate we can safely extract (spec section 5, example B).
    if _UNCLOSED_FENCE_RE.search(text):
        return CleanResult(None, "MALFORMED", "Unclosed markdown code fence; no complete candidate found.")

    # Step 4: no fence at all. If the bare text plausibly *is* Lean, pass it
    # through unchanged (only outer whitespace was stripped above).
    if _looks_like_lean(text):
        if len(text) > _MAX_CANDIDATE_CHARS:
            return CleanResult(None, "MALFORMED", f"Candidate exceeds {_MAX_CANDIDATE_CHARS} characters.")
        status = "PASSTHROUGH" if not was_text_quote_wrapped else "CLEANED"
        return CleanResult(text, status, None)

    # Step 5: nothing extractable -- this is prose/refusal/garbage, not a
    # mathematically-wrong-but-valid candidate. Abort-the-run territory.
    return CleanResult(None, "MALFORMED", "No extractable Lean proof found in model output.")
