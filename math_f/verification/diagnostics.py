"""Deterministic parsing of Lean 4 compiler output into structured
diagnostics, and a deterministic (non-LLM) failure taxonomy built on top of
them (spec section 18).

The raw Lean stdout/stderr is always preserved unmodified alongside these
derived diagnostics -- classification is a convenience layer, never a
replacement for the raw evidence.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Lean 4 diagnostic lines look like:
#   /tmp/xyz/candidate.lean:12:34: error: unknown identifier 'foo'
#   /tmp/xyz/candidate.lean:5:0: warning: declaration uses 'sorry'
# Messages may continue on following lines (indented context, goal state,
# etc.) until the next diagnostic header or end of stream.
_DIAG_HEADER_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+):\s*(?P<severity>error|warning|info)\s*:\s*(?P<message>.*)$"
)

FAILURE_CLASSES = (
    "malformed_candidate",
    "lean_syntax_error",
    "unknown_identifier",
    "type_mismatch",
    "uses_sorry",
    "unknown_tactic",
    "tactic_failure",
    "unsolved_goal",
    "wrong_theorem_application",
    "missing_import",
    "timeout",
    "environment_error",
    "duplicate_candidate",
    "unknown",
)


def parse_diagnostics(text: str) -> List[dict]:
    """Parse combined stdout+stderr text into a list of
    {severity, file, line, column, message} dicts. Never raises: unparsable
    output simply yields no diagnostics (the raw text is preserved
    separately by the caller regardless).
    """
    if not text:
        return []

    diagnostics: List[dict] = []
    current: Optional[dict] = None

    for line in text.splitlines():
        match = _DIAG_HEADER_RE.match(line)
        if match:
            if current is not None:
                diagnostics.append(current)
            current = {
                "severity": match.group("severity"),
                "file": match.group("file"),
                "line": int(match.group("line")),
                "column": int(match.group("col")),
                "message": match.group("message").rstrip(),
            }
        elif current is not None:
            # Continuation line belonging to the previous diagnostic.
            stripped = line.rstrip()
            if stripped:
                current["message"] = (current["message"] + "\n" + stripped).strip()

    if current is not None:
        diagnostics.append(current)

    return diagnostics


def uses_sorry(diagnostics: List[dict], stdout: str = "", stderr: str = "") -> bool:
    if any("uses 'sorry'" in d.get("message", "") for d in diagnostics):
        return True
    combined = f"{stdout}\n{stderr}"
    return "declaration uses 'sorry'" in combined


_KEYWORD_RULES = (
    ("unknown identifier", "unknown_identifier"),
    ("unknown constant", "unknown_identifier"),
    ("unknown tactic", "unknown_tactic"),
    ("type mismatch", "type_mismatch"),
    ("application type mismatch", "type_mismatch"),
    ("unsolved goals", "unsolved_goal"),
    ("unexpected token", "lean_syntax_error"),
    ("expected term", "lean_syntax_error"),
    ("expected command", "lean_syntax_error"),
    ("unexpected end of input", "lean_syntax_error"),
    ("unknown package", "missing_import"),
    ("unknown module", "missing_import"),
    ("file not found", "missing_import"),
    ("cannot find", "missing_import"),
    ("failed to synthesize", "tactic_failure"),
    ("linarith failed", "tactic_failure"),
    ("nlinarith failed", "tactic_failure"),
    ("ring failed", "tactic_failure"),
    ("simp made no progress", "tactic_failure"),
    ("tactic failed", "tactic_failure"),
    ("tactic '", "tactic_failure"),
    ("motive is not type correct", "wrong_theorem_application"),
    ("argument", "wrong_theorem_application"),
)


def classify_failure(result: dict) -> Optional[str]:
    """Deterministic keyword-based classification. `result` is a
    LeanVerifierResult-shaped dict (see lean_runner.py). Returns None when
    status is PASS (there is nothing to classify).
    """
    if result.get("status") == "PASS":
        return None

    if result.get("failure_class"):
        # Already classified upstream (e.g. malformed_candidate, timeout,
        # duplicate_candidate, environment_error) -- don't override it.
        return result["failure_class"]

    diagnostics = result.get("diagnostics") or []

    if uses_sorry(diagnostics, result.get("stdout", ""), result.get("stderr", "")):
        return "uses_sorry"

    messages = " ".join(d.get("message", "").lower() for d in diagnostics)
    if not messages:
        messages = f"{result.get('stdout', '')} {result.get('stderr', '')}".lower()

    for keyword, failure_class in _KEYWORD_RULES:
        if keyword in messages:
            return failure_class

    if diagnostics:
        return "lean_syntax_error" if any(
            d.get("severity") == "error" for d in diagnostics
        ) else "unknown"

    return "unknown"
