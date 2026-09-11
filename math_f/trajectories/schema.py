"""Trajectory JSON schema (documented here; enforced by construction in
`math_f.repair.loop` and `math_f.trajectories.writer`, not by a separate
validation layer -- kept as plain dicts so every field is easy to inspect
and diff on disk).

One ATTEMPT record per model/verifier round-trip:

{
  "trajectory_id": str,
  "attempt": int,               # 1-indexed
  "parent_attempt": int | null,
  "task": {"task_id": str, "source": str, "split": str},
  "model": {"name": str, "revision": str|null, "temperature": float,
            "max_new_tokens": int},
  "specification": {"theorem_statement": str, "lean_context": str},
  "generation": {"raw_model_output": str, "cleaned_candidate": str|null,
                 "cleaning_status": "CLEANED"|"PASSTHROUGH"|"EMPTY"|"MALFORMED",
                 "cleaning_reason": str|null},
  "verification": {  # shape depends on how far the attempt got:
       # normal Lean-checked candidate:
       "status": "PASS"|"FAIL", "verifier": "lean", "exit_code": int|null,
       "stdout": str, "stderr": str, "diagnostics": [...], "failure_class": str|null,
       "timed_out": bool, "duration_ms": int
       # OR malformed-candidate short-circuit (never reached Lean):
       "status": "ABORTED", "failure_class": "malformed_candidate"
  },
  "repair_feedback": str | null,  # feedback given to the model for the *next* attempt
  "runtime": {"generation_latency_ms": int, "verification_latency_ms": int,
              "total_latency_ms": int, "input_tokens": int|null, "output_tokens": int|null}
}

One FINAL record per task, written once the task's loop ends normally
(VERIFIED or ABSTAIN -- ABORTED tasks do not get a final record; see
`write_abort_marker` in writer.py instead, since the run stops before the
task can be considered "finished" in the ordinary sense):

{
  "trajectory_id": str, "task_id": str,
  "final_status": "VERIFIED"|"ABSTAIN",
  "success": bool, "success_on_attempt": int|null,
  "attempts_used": int, "max_attempts": int, "abort_reason": null
}

One ABORT EVENT record per run-stopping event (malformed output or
infrastructure failure), stored under metadata/aborts/:

{
  "timestamp": str, "kind": "malformed_candidate"|"infrastructure_error",
  "trajectory_id": str|null, "task_id": str|null, "attempt": int|null,
  "reason": str
}
"""
