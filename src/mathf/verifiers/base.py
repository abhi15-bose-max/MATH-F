"""
Shared scaffolding for concrete FormalVerifier implementations.

The important piece factored out here is `classify_lean_output`: turning
raw Lean stdout/stderr text into one of the VerificationStatus values.
This classification is best-effort and diagnostic only (MASTER PROMPT
section 11: "Do not overclaim error classification"). It NEVER decides
`verified` -- that is always exit-code-and-`sorry`-based (see
lean_verifier.py). Classification only helps failure_analysis.py group
failures into human-meaningful buckets.

Factoring this out of lean_verifier.py also lets us unit test the
classification logic directly against captured Lean output strings,
without needing a real Lean installation.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from mathf.core.interfaces import FormalVerifier  # noqa: F401  (re-exported)
from mathf.core.models import VerificationStatus, VerifierError

# Regexes are intentionally simple pattern matches over Lean 4's
# human-readable diagnostic messages. Lean does not provide a stable
# machine-readable error-code API as of this writing, so this is
# necessarily heuristic -- hence "best-effort" above.
_PATTERNS: List[Tuple[re.Pattern, VerificationStatus]] = [
    (re.compile(r"unknown identifier", re.IGNORECASE), VerificationStatus.UNKNOWN_IDENTIFIER),
    (re.compile(r"unknown constant", re.IGNORECASE), VerificationStatus.UNKNOWN_IDENTIFIER),
    (re.compile(r"unexpected token", re.IGNORECASE), VerificationStatus.SYNTAX_ERROR),
    (re.compile(r"expected .*(token|command)", re.IGNORECASE), VerificationStatus.SYNTAX_ERROR),
    (re.compile(r"type mismatch", re.IGNORECASE), VerificationStatus.TYPE_ERROR),
    (re.compile(r"application type mismatch", re.IGNORECASE), VerificationStatus.TYPE_ERROR),
    (re.compile(r"failed to synthesize", re.IGNORECASE), VerificationStatus.TYPE_ERROR),
    (re.compile(r"unsolved goals", re.IGNORECASE), VerificationStatus.TACTIC_FAILURE),
    (re.compile(r"tactic .*failed", re.IGNORECASE), VerificationStatus.TACTIC_FAILURE),
    (re.compile(r"simp made no progress", re.IGNORECASE), VerificationStatus.TACTIC_FAILURE),
    (re.compile(r"ring failed", re.IGNORECASE), VerificationStatus.TACTIC_FAILURE),
    (re.compile(r"linarith failed", re.IGNORECASE), VerificationStatus.TACTIC_FAILURE),
]

_ERROR_LINE_RE = re.compile(
    r"^(?P<path>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<sev>error|warning):\s*(?P<msg>.*)$",
    re.MULTILINE,
)


def classify_lean_output(stdout: str, stderr: str) -> VerificationStatus:
    """Best-effort classification of a *failing* Lean run. Only call
    this when `verified` is already known to be False."""
    combined = f"{stdout}\n{stderr}"
    for pattern, status in _PATTERNS:
        if pattern.search(combined):
            return status
    if "error" in combined.lower():
        return VerificationStatus.PROOF_ERROR
    return VerificationStatus.UNKNOWN


def extract_errors(stdout: str, stderr: str) -> List[VerifierError]:
    """Pull out `file:line:col: error: message` style diagnostics that
    Lean 4 prints, preserving raw text for anything that doesn't match
    that shape."""
    combined = f"{stdout}\n{stderr}"
    errors: List[VerifierError] = []
    for m in _ERROR_LINE_RE.finditer(combined):
        if m.group("sev") != "error":
            continue
        errors.append(
            VerifierError(
                message=m.group("msg").strip(),
                line=int(m.group("line")),
                column=int(m.group("col")),
                raw=m.group(0),
            )
        )
    if not errors and "error" in combined.lower():
        # Fallback: preserve *something* rather than an empty list, per
        # MASTER PROMPT section 11 ("always preserve raw verifier output").
        errors.append(VerifierError(message="unstructured verifier error output", raw=combined.strip()[:4000]))
    return errors


def contains_sorry_warning(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}"
    return "declaration uses 'sorry'" in combined or "uses sorry" in combined
