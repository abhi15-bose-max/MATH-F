"""
Shared scaffolding for concrete candidate generators.

`CandidateGenerator` (mathf.core.interfaces) is the abstract contract.
`BaseGenerator` here just factors out bookkeeping that most concrete,
non-AI generators want (a settable name, a default no-op reset, and a
small helper for building a Candidate with consistent defaults) so
individual generator files stay focused on their actual proof-search
logic.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from mathf.core.interfaces import CandidateGenerator
from mathf.core.models import Candidate, FormalMathProblem


class BaseGenerator(CandidateGenerator):
    def __init__(self, name: str):
        self.name = name

    def _make_candidate(
        self,
        problem: FormalMathProblem,
        attempt_number: int,
        proof: str,
        method: Optional[str] = None,
        search_time_seconds: Optional[float] = None,
        search_parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Candidate:
        return Candidate(
            problem_id=problem.problem_id,
            generator=self.name,
            attempt=attempt_number,
            proof=proof,
            method=method,
            search_time_seconds=search_time_seconds,
            search_parameters=search_parameters or {},
            metadata=metadata or {},
        )

    def reset(self) -> None:
        return None
