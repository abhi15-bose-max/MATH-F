"""
MATH-F: Verifier-Driven Formal Mathematics
============================================

A research framework for evaluating proof-candidate generators
against an independent formal verifier (Lean 4 + Mathlib).

Core invariant preserved throughout this package:

    CANDIDATE GENERATOR -> CANDIDATE -> VERIFIER -> RESULT -> FEEDBACK

Generation and verification are always separate, independently
replaceable components. See README.md for the full architecture.
"""

__version__ = "0.1.0"
