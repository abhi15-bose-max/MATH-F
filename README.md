# MATH-F: Verifier-Driven Formal Mathematics

MATH-F investigates a simple, general architecture for formal theorem proving:

```
 MATHEMATICAL PROBLEM
         |
 CANDIDATE GENERATOR   (any method: tactic search, ATP, SMT, symbolic,
         |               neural theorem prover, LLM, SLM, hybrid, ...)
         v
   CANDIDATE PROOF
         |
 FORMAL VERIFIER       (Lean 4 + Mathlib -- the sole authority)
         |
         v
    PASS / FAIL
    /         \
 PASS         FAIL
   |            |
 finish     feedback
                |
          next candidate
                |
              retry
```

The fundamental separation is:

**GENERATION ≠ VERIFICATION.**

A candidate generator *proposes* a proof. An independent formal
verifier *determines* whether that proof is valid. The generator is
never trusted to judge its own correctness — Lean is.

## Why separate candidate generation from verification?

Because it lets you swap the generator without ever having to trust
it. Whether the candidate came from a hand-written tactic portfolio,
an SMT solver, a specialized theorem prover, or eventually an LLM, the
question "is this actually a proof?" is answered by the same
independent authority every time. This also makes generators directly
comparable: run different generators against the same dataset, the
same verifier, and the same attempt budget, and their success rates
mean the same thing.

## What is the V1 architecture?

- **Problem**: a `FormalMathProblem` (`src/mathf/core/models.py`) —
  an id, an informal statement, a Lean theorem signature, and metadata.
  Dataset-agnostic; the orchestration layer only ever sees this shape.
- **Generator**: implements `CandidateGenerator.generate(problem,
  attempt_number, context) -> Candidate` (`src/mathf/core/interfaces.py`).
  V1 ships `FixedTacticSearchGenerator`
  (`src/mathf/generators/tactic_search.py`): a **non-AI** generator
  that tries an ordered, fixed portfolio of closing tactics
  (`decide`, `rfl`, `norm_num`, `ring`, `omega`, `simp`, `tauto`,
  `trivial`, `aesop`), optionally reordered per-problem via
  `metadata["tactic_priority"]`.
- **Verifier**: implements `FormalVerifier.verify(problem, candidate)
  -> VerificationResult`. V1 ships `LeanVerifier`
  (`src/mathf/verifiers/lean_verifier.py`), which assembles a real
  `.lean` file and runs `lake env lean` against a Lean 4 + Mathlib
  project (`lean_project/`). A candidate is `VERIFIED` only if Lean
  exits 0 **and** the proof does not rely on `sorry` (Lean happily
  exits 0 on an incomplete `sorry` proof, so this check matters).
- **Runner**: `ExperimentRunner` (`src/mathf/core/runner.py`) drives
  the retry loop up to `max_attempts` per problem, builds an optional
  feedback context from the previous failed attempt, detects exact
  duplicate candidates without re-invoking the verifier, and records
  every attempt.
- **Trajectory**: every candidate and every verification result for a
  problem, saved as JSON (`src/mathf/logging/trajectory.py`) —
  never just the final successful proof.
- **Evaluation**: `src/mathf/evaluation/metrics.py` and
  `failure_analysis.py` turn a set of trajectories into aggregate
  success rates *and* a breakdown of *how* the system failed.

## Why does V1 begin without AI?

Because the interesting engineering risk in this architecture isn't
"can an LLM write Lean" — it's "does generator → verifier → retry →
trajectory → evaluation actually work, end to end, without silently
lying about correctness anywhere in the pipeline." V1 answers that
question with the cheapest generator that can possibly produce real
Lean proofs: a fixed portfolio of tactics, with zero learned
components. Every later generator (a better proof-search algorithm, an
ATP, an SMT-backed method, eventually an LLM/SLM) plugs into the exact
same `CandidateGenerator` interface without changing the runner,
verifier, logging, or evaluation code at all.

## What is Lean's role? What is the generator's role?

Lean is the **only** thing that decides correctness. It cannot be
argued with, and no heuristic in this codebase is allowed to override
`VerificationResult.verified`. The generator's only job is to propose
candidates; being wrong is expected and is exactly what the retry loop
and trajectory log are for.

## How are trajectories recorded? How are experiments evaluated?

See the "Trajectory" and "Evaluation" bullets above. Concretely, each
run of `experiments/run_v1.py` writes one JSON file per problem under
`trajectories/`, containing every attempt (proof text, full verifier
result, duplicate flags), and one summary JSON under `results/`
containing metrics, failure analysis, and a reproducibility record
(experiment id, timestamp, dataset version, generator, verifier,
configuration, attempt budget, timeout, software versions).

---

## ⚠️ Known Limitations (read this before running)

**The environment that produced this repository had no network
access at all** (`curl`, `apt`, and `pip` to any external host all
failed with `host_not_allowed` / `403`). As a direct consequence:

1. **`LeanVerifier` has never been run against a real Lean +
   Mathlib toolchain.** It was written to the real `lake env lean`
   calling convention and its control flow (source assembly, exit
   code / `sorry` handling, error classification, timeout handling,
   missing-binary handling) is exercised by unit tests
   (`tests/test_verifier.py`) against a **stubbed** `subprocess.run`.
   That validates the *logic*; it does not validate that real Lean
   actually accepts the assembled `.lean` files.
2. **No `lake-manifest.json` is committed** in `lean_project/`,
   because generating one requires `lake update` with network access.
   You must run this yourself the first time (see "Running on Colab"
   or "Running locally" below).
3. **The `pytest` package could not be installed** (no network), so
   the test suite is written against the Python standard library's
   `unittest` instead. `pyproject.toml` / `requirements.txt` still
   list `pytest` as an optional dev dependency for environments that
   do have it.
4. **Every number in this README's "Development benchmark results"
   section comes from `MockLeanVerifier`**, an explicitly-labeled
   offline test double (`src/mathf/verifiers/mock_verifier.py`), NOT
   from real Lean. It exists specifically so the rest of the pipeline
   (retry loop, duplicate detection, trajectory logging, metrics,
   failure analysis) could be exercised for real, in this
   environment, without silently pretending to have done formal
   verification that didn't happen. `experiments/run_v1.py` refuses
   to run with the mock verifier unless you pass `--allow-mock`
   explicitly, and every mock result is tagged
   `"verifier_is_mock": true` in its output JSON, precisely so a mock
   run can never be mistaken for a real one.
5. The `tactic_priority` / `accepted_tactics` orderings in
   `datasets/v1/problems.json` are a good-faith prediction of real
   Lean behavior (e.g. `decide`/`rfl` should get stuck on opaque free
   variables where `ring`/`omega`/`simp` succeed), based on how `Nat`
   and `Int` are defined — **not a confirmed result**.

**Before trusting any correctness claim from this framework, run it
against real Lean** — see the Colab notebook, which installs Lean +
Mathlib (needs network) and re-runs the benchmark for real as its
first and most important job.

**Update, first real Colab run:** the toolchain install and
`LeanVerifier`'s subprocess plumbing worked correctly against a real
Lean install (no `FileNotFoundError`, clean `TimeoutExpired` handling)
— but the original `timeout_seconds=30/60` defaults were too tight and
produced `TIMEOUT` results. Root cause: every verification call spawns
a *fresh* `lean` process, and `import Mathlib` forces that process to
deserialize the entire Mathlib environment from disk before it looks
at the goal — this routinely takes well over a minute on shared/cloud
disks even with `lake exe cache get` already run. Defaults have been
raised to `180s` (`configs/default.yaml`, `ExperimentConfig`,
`LeanVerifier`). If you still see `TIMEOUT`, first confirm `lake exe
cache get` actually downloaded prebuilt files (rather than falling
back to a from-source Mathlib build, which takes hours). The durable
fix — not yet implemented — is to stop paying Mathlib's cold-import
cost on every single candidate by reusing one warm Lean process (e.g.
via `leanprover-community/repl`) instead of shelling out fresh each
time; see "What is planned" below.

---

## Repository structure

```
math-f/
├── README.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── .gitignore
├── configs/
│   └── default.yaml
├── datasets/
│   └── v1/
│       └── problems.json          # 16-problem V1 development benchmark
├── src/mathf/
│   ├── core/
│   │   ├── interfaces.py          # CandidateGenerator, FormalVerifier (ABCs)
│   │   ├── models.py              # Problem/Candidate/VerificationResult/Trajectory
│   │   ├── dataset.py             # dataset loading + validation
│   │   └── runner.py              # ExperimentRunner: the retry/search loop
│   ├── generators/
│   │   ├── base.py
│   │   └── tactic_search.py       # FixedTacticSearchGenerator (non-AI, V1)
│   ├── verifiers/
│   │   ├── base.py                # Lean output classification helpers
│   │   ├── lean_verifier.py       # LeanVerifier (real; untested against real Lean here)
│   │   └── mock_verifier.py       # MockLeanVerifier (offline test double, NOT real)
│   ├── logging/
│   │   └── trajectory.py          # DuplicateTracker, save/load trajectories
│   └── evaluation/
│       ├── metrics.py
│       └── failure_analysis.py
├── lean_project/                  # Lake project so "import Mathlib" resolves
│   ├── lakefile.toml
│   ├── lean-toolchain
│   ├── MathF.lean
│   └── README.md                  # Lean-specific setup instructions
├── experiments/
│   └── run_v1.py                  # CLI: run the full experiment end-to-end
├── trajectories/                  # one JSON per problem per run (gitignored)
├── results/                       # one JSON per experiment run (gitignored)
├── notebooks/
│   └── MATH_F_V1_demo.ipynb       # Colab workflow: install Lean, run for real
└── tests/                         # 78 unittest tests, all passing offline
    ├── test_dataset.py
    ├── test_generators.py
    ├── test_verifier.py
    ├── test_runner.py
    ├── test_trajectory.py
    ├── test_metrics.py
    └── test_failure_analysis.py
```

## Running locally

```bash
git clone <this-repo-url> math-f
cd math-f
pip install -r requirements.txt        # or: pip install -e .

# Run the test suite (no Lean required):
python -m unittest discover -s tests -t . -v

# Set up Lean + Mathlib (requires network; see lean_project/README.md):
cd lean_project && lake update && lake exe cache get && lake build && cd ..

# Sanity-check the Lean toolchain:
python experiments/run_v1.py --check-lean

# Run the real experiment:
python experiments/run_v1.py

# Or, without Lean installed, exercise the pipeline offline (NOT real verification):
python experiments/run_v1.py --verifier mock --allow-mock
```

## Running on Colab

Open `notebooks/MATH_F_V1_demo.ipynb` in Google Colab. It:

1. Clones this repository.
2. Installs `elan` and the pinned Lean toolchain.
3. Runs `lake update`, `lake exe cache get`, `lake build` for
   `lean_project/`.
4. Runs a tiny Lean sanity check (`#eval 1 + 1`).
5. Runs `experiments/run_v1.py` against the **real** `LeanVerifier`.
6. Displays aggregate metrics and at least one complete trajectory.
7. Saves results back into `results/` and `trajectories/`.

MATH-F V1 does not require a GPU.

## Testing

```bash
python -m unittest discover -s tests -t . -v
```

78 tests currently pass, covering: dataset loading and problem
validation, candidate validation, the fixed tactic search generator
(including per-problem overrides, determinism, and the "exhausted"
hint), Lean output classification and error extraction (against
hand-written sample Lean diagnostic strings), `LeanVerifier`'s control
flow against a stubbed subprocess (success, `sorry`, classified
failure, timeout, missing binary, malformed candidate), the mock
verifier, the retry/search runner (first-attempt success, multi-attempt
success, permanent failure, duplicate detection, feedback context
shape), trajectory persistence (save/load round-trip, never
overwriting), metrics computation, and failure analysis — all against
a hand-built synthetic dataset with known expected outputs.

If you have network access, `pip install pytest` and run `pytest
tests/` instead; both work against the same test files.

## Development benchmark results (⚠️ MockLeanVerifier — NOT real Lean)

Running `python experiments/run_v1.py --verifier mock --allow-mock`
against the 16-problem V1 development benchmark:

```
Problems: 16

First-attempt success: 5/16  (31.2%)
Final success:         15/16  (93.8%)
Average attempts (solved only): 2.13
Median attempts (solved only):  2
Timeouts: 0
Malformed candidates: 0
Duplicate candidates: 0

Cumulative success by attempt:
  after attempt 1: 5
  after attempt 2: 8
  after attempt 3: 15
  after attempt 4: 15
  after attempt 5: 15

Failures by status:
  TACTIC_FAILURE: 22

Unsolved problems (1): mathf_016
```

`mathf_016` (`∀ n : Nat, n < 2 ^ n`) is *deliberately* included as a
problem the fixed-tactic-portfolio generator cannot solve — it needs
induction, which none of `decide`/`rfl`/`norm_num`/`ring`/`omega`/
`simp`/`tauto`/`trivial`/`aesop` perform unassisted on an unbounded
universally-quantified goal. It exists to demonstrate the genuine
failure/retry/REJECTED path, not to pad the benchmark.

This is a 16-problem development benchmark used to validate the
pipeline, not evidence of broad mathematical capability, and (per the
Known Limitations above) these specific pass/fail outcomes are from an
offline mock, not from Lean. **Re-run
`python experiments/run_v1.py` with real Lean (e.g. via the Colab
notebook) before treating these numbers as meaningful.**

## What is currently implemented

- Generic `FormalMathProblem` / `Candidate` / `VerificationResult` /
  `Trajectory` data model with validation.
- Generic `CandidateGenerator` / `FormalVerifier` interfaces with no
  AI-specific or Lean-specific assumptions baked in.
- A real, non-AI candidate generator (`FixedTacticSearchGenerator`).
- A real Lean 4 + Mathlib verifier (`LeanVerifier`) — logic-tested,
  not yet run against a real toolchain in this environment.
- An offline mock verifier for pipeline development/demo
  (`MockLeanVerifier`), clearly labeled and gated behind `--allow-mock`.
- A generic retry/search controller with feedback-context building
  and duplicate detection.
- Full trajectory logging (every attempt, never just the final proof).
- Metrics and failure analysis over trajectories.
- A 16-problem development benchmark.
- A CLI experiment runner (`experiments/run_v1.py`).
- A Colab notebook that installs Lean + Mathlib and runs the real
  thing.
- 78 passing unit tests.

## What is planned (not implemented — see MASTER PROMPT roadmap)

- **V2**: additional non-AI proof-search / ATP methods (e.g. a
  Z3-backed candidate generator, translating an SMT-derived
  certificate into something Lean can check).
- **V3**: an AI theorem-proving candidate generator (LLM/SLM), plugged
  into the same `CandidateGenerator` interface with no framework
  changes.
- **V4**: hybrid proof search + AI.
- Feedback-aware generation (a generator that actually consumes
  `context["previous_errors"]` to adapt its next candidate — the
  framework supports this today; V1's generator simply doesn't use it).
- Larger/standard datasets (miniF2F, etc.) via additional importers in
  `src/mathf/core/`.
- Committing `lean_project/lake-manifest.json` once `lake update` has
  been run with network access, for full reproducibility.
- **Reusing a warm Lean process across candidates** (e.g. via
  `leanprover-community/repl`) instead of spawning `lean` fresh per
  candidate. This is the real fix for the slow-cold-Mathlib-import
  issue noted above, and matters increasingly as the benchmark or
  attempt budget grows — right now every single attempt re-pays the
  full Mathlib import cost.

## Scientific positioning

MATH-F does not claim to "eliminate hallucinations." It provides a
way to evaluate generated proof candidates using an independent formal
verifier, and to measure candidate-generation performance under that
verifier, on a small development benchmark. Broader claims require a
larger, independently-vetted benchmark and should not be inferred from
this repository's V1 results.
