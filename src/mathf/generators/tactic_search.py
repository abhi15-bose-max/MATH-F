"""
FixedTacticSearchGenerator: a genuinely non-AI candidate generator.

This is V1's proof-search mechanism (see MASTER PROMPT section 5). It is
deliberately simple and contains no learned components:

For each attempt, it emits ONE candidate proof consisting of a single
closing tactic (or short fixed tactic script) drawn from a small, fixed
portfolio -- the same idea behind Lean/Mathlib's own `hint` tactic and
the `first | t1 | t2 | ...` combinator, just made explicit so each
tactic becomes its own logged attempt/verification round-trip instead
of being resolved inside a single Lean invocation.

Per-problem ordering can be supplied via
`problem.metadata["tactic_priority"]` (a list of tactic strings to try,
in order, before falling back to the generic default portfolio). This
lets a dataset curator (or a future, smarter non-AI search tool) bias
the search without changing any framework code -- the generator
contract is unaffected.

This generator carries NO neural network, NO LLM/SLM call, and NO
API dependency. It is intentionally the "smallest real thing that
could possibly work" baseline described in the MASTER PROMPT.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from mathf.core.models import Candidate, FormalMathProblem
from mathf.generators.base import BaseGenerator

# Generic, domain-agnostic default portfolio. Order matters: cheap,
# broadly-applicable tactics are tried first.
DEFAULT_TACTIC_PORTFOLIO: List[str] = [
    "decide",
    "rfl",
    "norm_num",
    "ring",
    "omega",
    "simp",
    "tauto",
    "trivial",
    "aesop",
]


class FixedTacticSearchGenerator(BaseGenerator):
    """Tries a fixed, ordered portfolio of closing tactics.

    generate() is a pure function of (problem, attempt_number): given
    the same inputs it always returns the same candidate, so this
    generator has NO internal search state and `reset()` is a no-op.
    This makes it maximally simple to test and reason about, at the
    cost of not adapting to verifier feedback (V1 does not require
    feedback-aware generation -- see MASTER PROMPT section 13).
    """

    def __init__(
        self,
        name: str = "fixed_tactic_search",
        default_portfolio: Optional[List[str]] = None,
    ):
        super().__init__(name=name)
        self.default_portfolio = list(default_portfolio or DEFAULT_TACTIC_PORTFOLIO)

    def _portfolio_for(self, problem: FormalMathProblem) -> List[str]:
        hinted = problem.metadata.get("tactic_priority") if problem.metadata else None
        if hinted:
            # de-duplicate while preserving order, then extend with any
            # generic tactics not already covered so the search never
            # runs out of ideas before max_attempts is reached.
            seen = set()
            ordered: List[str] = []
            for t in list(hinted) + self.default_portfolio:
                if t not in seen:
                    seen.add(t)
                    ordered.append(t)
            return ordered
        return self.default_portfolio

    def generate(
        self,
        problem: FormalMathProblem,
        attempt_number: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> Candidate:
        start = time.time()
        portfolio = self._portfolio_for(problem)
        index = attempt_number - 1
        exhausted = index >= len(portfolio)
        tactic = portfolio[index % len(portfolio)]
        proof = f"by {tactic}"
        elapsed = time.time() - start
        return self._make_candidate(
            problem=problem,
            attempt_number=attempt_number,
            proof=proof,
            method="fixed_tactic_portfolio",
            search_time_seconds=elapsed,
            search_parameters={"tactic": tactic, "portfolio_index": index},
            metadata={"exhausted": exhausted},
        )
