# lean_project/

This is a minimal Lake project whose only purpose is to give the
`LeanVerifier` a build environment with Mathlib in scope. Individual
candidate proofs are written to `Scratch/*.lean` at verification time
and checked with `lake env lean <scratch_file>.lean` run from this
directory.

## First-time setup (requires network access)

This repository was built in a sandboxed environment with **no network
access**, so the steps below have not been executed as part of
producing this repository. Run them yourself (locally, in CI, or in
the provided Colab notebook) before using the real `LeanVerifier`:

```bash
# 1. Install elan (the Lean toolchain manager), if you don't have it:
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
source $HOME/.elan/env

cd lean_project

# 2. Resolve dependency versions (creates/updates lake-manifest.json):
lake update

# 3. Fetch prebuilt Mathlib .olean cache instead of compiling Mathlib
#    from source (much faster -- minutes instead of hours):
lake exe cache get

# 4. Build this (nearly empty) project, which pulls in Mathlib:
lake build

# 5. Sanity check:
lake env lean --stdin <<< "import Mathlib
theorem t : (1 : Nat) + 1 = 2 := by decide
#eval \"lean + mathlib OK\""
```

## Version pinning

- `lean-toolchain` currently pins `leanprover/lean4:v4.14.0` as a
  good-faith default. **Verify this is still a version Mathlib
  supports** at https://github.com/leanprover-community/mathlib4/blob/master/lean-toolchain
  before running `lake update` -- Mathlib requires an exact toolchain
  match and moves forward frequently. Update the file if needed, then
  re-run `lake update`.
- After `lake update` succeeds, **commit the generated
  `lake-manifest.json`** so that the exact Mathlib commit used is
  reproducible for anyone else who clones this repository (MASTER
  PROMPT section 22, reproducibility). It is intentionally not
  included yet in this delivery, for the reason above.

## Scratch files

`Scratch/` is created automatically by `LeanVerifier` the first time
it runs. Each candidate attempt gets its own file
(`<problem_id>_attempt<N>_<hash>.lean`) and, by default
(`keep_scratch_files=True`), files are kept rather than deleted, so a
full experiment run is auditable after the fact (MASTER PROMPT section
16). Add `Scratch/` to your local `.gitignore` if you don't want to
commit them (the top-level `.gitignore` already does this).
