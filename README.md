# MATH-F: Verified Small-Model Lean 4 Theorem Proving Evaluation

MATH-F evaluates a small language model on miniF2F-style Lean 4 theorem
proving. The model proposes a proof; **the real Lean 4 toolchain is the
only authority on whether it's correct**; if Lean rejects it, the model
gets the verifier's feedback and up to 5 total attempts. Every attempt is
persisted as its own JSON file, so every statistic this repo reports is
traceable back to raw evidence on disk.

This is an **evaluation and failure-analysis engine**, not a fine-tuning
pipeline and not a web app. It is designed to run unattended for hours on a
Colab A100, survive being killed and resumed, and produce an auditable
trajectory dataset plus a metrics report.

```
python -m math_f evaluate --split test --max-attempts 5 --output runs/experiment_001
```

---

## Table of contents

1. [Repository layout](#repository-layout)
2. [Setup](#setup)
3. [Colab quick start](#colab-quick-start)
4. [CLI reference](#cli-reference)
5. [The overnight evaluation command](#the-overnight-evaluation-command)
6. [Trajectory format](#trajectory-format)
7. [The malformed-output policy](#the-malformed-output-policy)
8. [1-shot / 2-shot / ... metrics, explained](#1-shot--2-shot---metrics-explained)
9. [Design notes](#design-notes)
10. [Tests](#tests)

---

## Repository layout

```
math-f/
├── configs/
│   └── default.yaml            # all tunables; overridden by env vars, then CLI flags
├── math_f/
│   ├── cli.py                  # evaluate / smoke-test / verify / stats / resume
│   ├── config.py                # ExperimentConfig (dataclasses) + YAML/JSON/env/CLI merge
│   ├── logging_utils.py         # "[INFO] ..." / "[CRITICAL] ..." structured logging
│   ├── models/
│   │   ├── base.py              # CandidateModel interface
│   │   ├── mock.py               # deterministic offline backend (tests, smoke-test)
│   │   ├── hf_model.py           # real Transformers backend (lazy torch/transformers import)
│   │   └── build.py              # backend factory
│   ├── datasets/
│   │   ├── minif2f.py            # loads/normalizes AI-MO/minif2f_test (or any compatible dataset)
│   │   └── data/minif2f_sample.jsonl  # bundled OFFLINE fixtures, NOT miniF2F (see below)
│   ├── generation/
│   │   ├── output_cleaner.py     # deterministic (non-LLM) model-output -> candidate cleaner
│   │   └── generator.py          # prompt -> model -> timing -> cleaning orchestration
│   ├── verification/
│   │   ├── lean_runner.py        # isolated, timed Lean subprocess execution
│   │   └── diagnostics.py        # Lean diagnostic parsing + deterministic failure taxonomy
│   ├── repair/
│   │   ├── prompts.py            # initial + repair prompt construction (no reference proofs)
│   │   └── loop.py               # the bounded generate/verify/repair loop
│   ├── trajectories/
│   │   ├── writer.py             # atomic, one-file-per-attempt persistence
│   │   ├── loader.py             # read-only iteration over raw trajectories
│   │   └── schema.py             # documents the JSON shapes (see below)
│   ├── evaluation/
│   │   ├── metrics.py            # exact vs. cumulative attempt-success, failure counts, etc.
│   │   └── reports.py            # summary.json / summary.csv / summary.md
│   └── utils/                    # ids, git provenance, environment/tool checks
├── notebooks/
│   └── math_f_colab.ipynb        # clone -> install -> Lean/Mathlib setup -> smoke-test -> run
├── tests/                        # pure-Python unit + integration tests (no GPU/Lean required)
├── requirements.txt
├── pyproject.toml
└── configs/default.yaml
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Run the offline test suite (no GPU, no Lean, no network needed):

```bash
pytest
```

You also need a **Lean 4 + Mathlib** toolchain to verify anything for real.
Locally:

```bash
curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh
mkdir lean_project && cd lean_project
lake +leanprover/lean4:stable new mathlib_project math   # or configure an existing Mathlib project
# add a `[[require]] name = "mathlib" git = "https://github.com/leanprover-community/mathlib4"`
# entry to lakefile.toml, then:
lake update && lake exe cache get && lake build
export LEAN_PROJECT_DIR=$(pwd)
```

Without Lean installed, `evaluate`/`verify` will still run correctly: the
first task that needs verification raises an infrastructure error and the
run aborts cleanly with a clear message (see
[Design notes](#design-notes)). `smoke-test` degrades gracefully and marks
the Lean-dependent checks as skipped instead of crashing.

## Colab quick start

Open `notebooks/math_f_colab.ipynb` in Colab. It walks through, in order:

1. clone + `pip install -r requirements.txt`
2. GPU check (`nvidia-smi`, `torch.cuda.is_available()`)
3. install `elan`/`lake`, create a Mathlib-enabled Lake project, and run
   `lake exe cache get` (downloads prebuilt `.olean`s instead of compiling
   Mathlib from source -- this is the one genuinely slow step)
4. set `MODEL_NAME` / `MAX_ATTEMPTS`
5. `python -m math_f smoke-test --backend hf` (fast sanity check)
6. a 5-task trial evaluation
7. a printed pre-flight summary (GPU / model / task count / max attempts)
   before you commit to an overnight run
8. the full overnight `evaluate` command
9. a `resume` cell for after a disconnect
10. `stats` + zip-and-download of `runs/experiment_001`

## CLI reference

```bash
python -m math_f evaluate --split test --max-attempts 5 --output runs/experiment_001
python -m math_f smoke-test
python -m math_f verify --candidate-file proof.lean --task-id sample_two_plus_two --split sample
python -m math_f stats --input runs/experiment_001
python -m math_f resume --input runs/experiment_001
```

| Command | Purpose |
|---|---|
| `evaluate` | Run (or continue, with `--resume`) an evaluation over a dataset split. |
| `smoke-test` | Fast, mostly-non-fatal infrastructure check (see checklist below). |
| `verify` | Check one candidate against Lean directly, outside the repair loop. |
| `stats` | Recompute metrics fresh from a run's raw trajectory files. |
| `resume` | Shorthand for `evaluate --resume`, using the run's stored config. |

Common flags (all commands that touch a model/dataset/Lean): `--config
path.yaml`, `--model-name`, `--model-backend {hf,mock}`, `--model-revision`,
`--dataset-name`, `--timeout` (Lean, seconds), `--lean-project-dir`.
`evaluate` adds `--split`, `--max-attempts`, `--limit`, `--output`
(required), `--resume`.

Every flag can also be set via environment variable (`MODEL_NAME`,
`MODEL_BACKEND`, `MODEL_REVISION`, `MAX_ATTEMPTS`, `LEAN_PROJECT_DIR`,
`VERIFY_TIMEOUT_SECONDS`) or in a YAML/JSON config file passed via
`--config` (see `configs/default.yaml`). Priority: CLI flag > env var >
config file > built-in default.

`smoke-test` checks, each printed as `[✓]`/`[✗]`/`[-]` (pass/fail/skipped):
Python environment, PyTorch, CUDA, GPU, Transformers, model loading,
tokenizer, Lean executable, Mathlib, one theorem generation, the candidate
cleaner, one real Lean verification, and the trajectory writer round-trip.
It uses 1-3 tasks from the bundled offline sample set, not real miniF2F, so
it never needs the network or a downloaded checkpoint unless you pass
`--backend hf`.

## The overnight evaluation command

```bash
python -m math_f evaluate \
  --split test \
  --max-attempts 5 \
  --lean-project-dir "$LEAN_PROJECT_DIR" \
  --output runs/experiment_001
```

This uses the default model (`AI-MO/Kimina-Prover-Preview-Distill-1.5B`,
overridable with `--model-name` / `MODEL_NAME`) against the real
`AI-MO/minif2f_test` `test` split, at up to 5 attempts per problem,
`temperature=0` / greedy decoding for reproducibility.

If the Colab runtime dies partway through:

```bash
python -m math_f resume --input runs/experiment_001
```

reloads the run's own saved config and skips every task that already has a
final (`VERIFIED` or `ABSTAIN`) trajectory record -- see
[trajectory format](#trajectory-format) for exactly what "final" means and
why a task that triggered an abort does *not* count as done.

## Trajectory format

Every attempt gets its own file, written to disk **immediately** (spec:
never hold a night's worth of trajectories only in RAM):

```
runs/experiment_001/
├── raw/trajectories/
│   ├── test__amc12a_2015_p10_attempt_1.json
│   ├── test__amc12a_2015_p10_attempt_2.json
│   └── test__amc12a_2015_p10_final.json
├── summaries/
│   ├── summary.json   summary.csv   summary.md
├── logs/
│   └── run.log
└── metadata/
    ├── config.json               # the config this run actually used
    ├── environment_latest.json   # python/torch/transformers/lean/mathlib/git provenance
    └── aborts/*.json             # one record per run-stopping event, if any
```

`trajectory_id` is deterministic (`"{split}__{task_id}"`), not random, so
`--resume` can detect completed work by re-deriving the ID and checking for
a `_final.json` file -- no separate ID-mapping file needed.

An **attempt** record (see `math_f/trajectories/schema.py` for the full
annotated shape):

```json
{
  "trajectory_id": "test__amc12a_2015_p10",
  "attempt": 2,
  "parent_attempt": 1,
  "task": {"task_id": "amc12a_2015_p10", "source": "AI-MO/minif2f_test", "split": "test"},
  "model": {"name": "AI-MO/Kimina-Prover-Preview-Distill-1.5B", "revision": null,
            "temperature": 0.0, "max_new_tokens": 1024},
  "specification": {"theorem_statement": "theorem amc12a_2015_p10 ... := by", "lean_context": "import Mathlib\n..."},
  "generation": {"raw_model_output": "...unmodified model text...",
                 "cleaned_candidate": "theorem amc12a_2015_p10 ... := by\n  ...",
                 "cleaning_status": "CLEANED", "cleaning_reason": null},
  "verification": {"status": "PASS", "verifier": "lean", "exit_code": 0,
                    "stdout": "", "stderr": "", "diagnostics": [],
                    "failure_class": null, "timed_out": false, "duration_ms": 842},
  "repair_feedback": null,
  "runtime": {"generation_latency_ms": 1310, "verification_latency_ms": 842,
              "total_latency_ms": 2152, "input_tokens": 612, "output_tokens": 96}
}
```

`raw_model_output` is always the untouched model text. `cleaned_candidate`
is a *separate* field produced by the deterministic cleaner, so the two can
always be diffed later. A `_final.json` record is written once per task
that reaches `VERIFIED` or `ABSTAIN`:

```json
{"trajectory_id": "test__amc12a_2015_p10", "task_id": "amc12a_2015_p10",
 "final_status": "VERIFIED", "success": true, "success_on_attempt": 2,
 "attempts_used": 2, "max_attempts": 5, "abort_reason": null}
```

No reference/gold proof is ever loaded into a `Task` object or sent to the
model -- `math_f.datasets.minif2f.Task` simply has no field for one, so it
cannot leak into a prompt even by accident (spec section 11).

## The malformed-output policy

Two failures look similar but are treated completely differently:

* **A valid-but-wrong Lean candidate** (Lean rejects it: unsolved goal,
  type mismatch, wrong tactic, ...) is a **normal experimental result**.
  It's recorded, the verifier's diagnostics are handed back to the model,
  and the loop continues to the next attempt.
* **Protocol-malformed output** -- prose with no extractable proof, an
  unclosed code fence, an empty response -- means the model-output
  contract itself broke. This is **not** mathematical failure data, so it
  is never silently retried or discarded. `math_f/generation/output_cleaner.py`
  is the single deterministic (no LLM) gate that makes this call. On a
  MALFORMED verdict, `math_f/repair/loop.py` writes the offending attempt
  to disk (`verification.status = "ABORTED"`,
  `failure_class = "malformed_candidate"`), then raises
  `MalformedOutputAbort`, which the CLI catches, logs at `[CRITICAL]`,
  records under `metadata/aborts/`, and uses to **stop the entire
  evaluation run** -- not just that task.

The same "stop the whole run, don't paper over it" treatment applies to
**infrastructure failures**: `lean_runner.py` raises
`LeanInfrastructureError` if the Lean/Lake executable can't be found at
all (immediate abort) or, for a transient subprocess-launch failure, after
`verification.max_consecutive_infra_failures` (default 3) happen in a row.
A **duplicate candidate** (the model repeats an already-rejected candidate
verbatim after seeing the feedback) is different again: it's a normal
model failure, so it only ends that one task's loop (recorded as
`failure_class = "duplicate_candidate"`, final status `ABSTAIN`) and
evaluation continues to the next task.

One more correctness subtlety worth calling out: Lean will happily exit 0
on a proof that only compiles because it admits `sorry`. `lean_runner.py`
explicitly checks for the `declaration uses 'sorry'` warning and reports
`status: "FAIL"` / `failure_class: "uses_sorry"` in that case, even though
the exit code is 0 -- "Lean is the authority" has to mean the *whole*
Lean verdict, not just its exit code.

## 1-shot / 2-shot / ... metrics, explained

These are two different quantities and `math_f/evaluation/metrics.py`
keeps them separate on purpose (spec section 17):

* **`exact_attempt_distribution["success_on_attempt_k"]`** -- the number of
  tasks whose *first successful* attempt was *exactly* attempt `k`.
* **`cumulative_success_by_attempt["cumulative_success_k_shot"]`** -- the
  fraction of tasks solved *within* the first `k` attempts, i.e. `<= k`.

Worked example (matches the spec's own numbers, scaled to 20 tasks and
reproduced verbatim in `tests/test_metrics.py`):

| k | success_on_attempt_k | cumulative_k_shot |
|---|---:|---:|
| 1 | 8 (40%) | 40% |
| 2 | 2 (10%) | 50% |
| 3 | 1 (5%)  | 55% |
| 4 | 0       | 55% |
| 5 | 0       | 55% |

with the remaining 9/20 tasks `ABSTAIN`ed after exhausting all 5 attempts.
`mean_attempts_to_success` / `median_attempts_to_success` are computed only
over `VERIFIED` tasks. `failure_class_counts` aggregates over **every**
attempt across every trajectory, not just final outcomes. Aborted tasks
(malformed output or infrastructure failure) are reported as their own
absolute counts (`malformed_output_count`, `infrastructure_abort_count`)
and are **not** folded into the success-rate denominator -- a protocol
break isn't the same statistical event as the model trying and failing 5
times, and mixing them in would misrepresent the model's real capability.

`stats` always recomputes every number directly from the raw
`raw/trajectories/*.json` files on disk; nothing is cached, so results are
traceable back to raw evidence even months later.

## Design notes

* **Candidate contract**: the model is asked to return the *complete*
  self-contained `theorem ... := by ...` block (matching the given
  statement), not just a tactic fragment -- this is the same convention
  used by DeepSeek-Prover/Kimina-Prover and keeps `output_cleaner.py` and
  `lean_runner.py` simple and unambiguous.
* **Cleaner is conservative on purpose**: it strips markdown fences, a
  `text'''...'''`-style wrapper, and outer whitespace -- and nothing else.
  It never regexes the inside of a candidate (see
  `tests/test_output_cleaner.py::test_does_not_mutate_internal_content`).
* **`math_f/datasets/data/minif2f_sample.jsonl`** is a tiny, self-authored,
  Mathlib-free fixture set (3 trivial theorems) used only by `smoke-test`
  and offline tests. It is explicitly tagged `"source": "local_sample"` /
  `split: "sample"` and is never mixed with real `AI-MO/minif2f_test` data,
  so smoke-test output can never be mistaken for a benchmark result.
* **No hidden chain-of-thought** is requested from the model; only the
  proof candidate itself is asked for and stored (spec section 35).
* **Deterministic decoding by default** (`temperature=0`, `do_sample=false`)
  for reproducibility; both are configurable.
* **Provenance**: `metadata/environment_latest.json` records Python,
  PyTorch, Transformers, `datasets`, Lean, and (best-effort) Mathlib
  versions, plus the model name/revision, dataset name/split, and this
  repo's git commit -- so contamination/reproducibility questions have an
  answer on disk, not just a claim in a README (spec sections 21-22).

## Tests

```bash
pytest            # or: python -m unittest discover -s tests
```

57 tests, all running on CPU with no GPU, no network, and no Lean
installation (Lean itself is exercised through a mocked `subprocess.run`,
per spec section 31 -- "don't let tests use the real large model", extended
here to the real Lean toolchain too, for the same reason: CI should not
require a multi-GB Mathlib build to pass).

| File | Covers |
|---|---|
| `test_output_cleaner.py` | plain/fenced/wrapped proofs, whitespace, malformed/empty output, oversized/unclosed-fence guards, non-mutation of candidate content |
| `test_lean_runner.py` | PASS, FAIL-with-diagnostics, syntax-error classification, the `sorry`-despite-exit-0 case, timeout, missing executable, transient OS error, temp-dir cleanup |
| `test_repair_loop.py` | FAIL-then-PASS, full exhaustion -> ABSTAIN, malformed abort (mid-loop too), duplicate-candidate short-circuit (with/without the feature toggled off) |
| `test_malformed_output_e2e.py` | malformed candidate -> attempt persisted to disk -> `MalformedOutputAbort` raised -> no final record -> abort marker written |
| `test_duplicate_candidate_e2e.py` | repeated (non-adjacent) candidate detected and persisted correctly |
| `test_metrics.py` | the exact spec worked example (40/10/5% -> 40/50/55% cumulative), a pathological case that would trip up a confused implementation, mean/median, failure-class aggregation, token/time totals, abort accounting kept separate from the success denominator |
| `test_trajectory_writer.py` | directory layout, atomic round-trips, config write-once-unless-overwrite, no leftover temp files |
| `test_resume.py` | completed-ID detection excludes interrupted/aborted tasks, deterministic trajectory IDs, task-list filtering, unsafe-character sanitization |
| `test_reports.py` | `summary.json`/`.csv`/`.md` all get written |
| `test_config.py` | defaults, YAML loading, env-var overrides, dotted CLI overrides, save/load round-trip |
| `test_smoke_test_cli.py` | `smoke-test --backend mock` runs clean end-to-end with no GPU/Lean present |

Also manually exercised end-to-end against a stub Lean binary during
development (not part of the committed suite, since it depends on an
external fake executable): the full `evaluate` -> `resume` -> `stats` ->
`verify` command chain, plus CLI-level malformed-output and
infrastructure-error aborts, all matched their expected exit codes and
on-disk artifacts.

Real-model and real-Lean/Mathlib integration is intentionally left to the
Colab notebook (`smoke-test --backend hf`, then a `--limit 5` trial run)
rather than the committed CI suite, since it needs a GPU and a multi-GB
Mathlib build.
