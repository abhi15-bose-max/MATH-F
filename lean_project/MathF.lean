-- Root library file for the `MathF` Lake target.
--
-- This project exists only to give `lake env lean <scratch_file>.lean`
-- (invoked by mathf.verifiers.lean_verifier.LeanVerifier) a build
-- environment where `import Mathlib` resolves. It intentionally
-- contains no real theorems of its own: all candidate proofs are
-- checked in scratch files under `Scratch/`, which is where the
-- verifier writes each attempt (see LeanVerifier.build_source).

import Mathlib

/-- Sanity check used by `LeanVerifier.check_environment()` and by
`notebooks/MATH_F_V1_demo.ipynb` to confirm the toolchain + Mathlib are
correctly installed before running the benchmark. -/
theorem mathf_sanity_check : (1 : Nat) + 1 = 2 := by decide
