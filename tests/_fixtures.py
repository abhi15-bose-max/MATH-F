"""Shared synthetic trajectory-dict builders used by test_metrics.py and
test_failure_analysis.py, so both exercise the exact same scenario."""


def attempt(n, verified, status, runtime=0.1, duplicate=False, duplicate_of=None):
    return {
        "attempt": n,
        "candidate": {"proof": f"by tactic_{n}"},
        "verification": {"verified": verified, "status": status, "runtime_seconds": runtime},
        "duplicate": duplicate,
        "duplicate_of_attempt": duplicate_of,
    }


def trajectory(problem_id, attempts, solved, generator="fixed_tactic_search"):
    return {
        "problem_id": problem_id,
        "generator": generator,
        "verifier": "mock_lean_v0",
        "attempts": attempts,
        "attempts_used": len(attempts),
        "solved": solved,
        "final_status": "VERIFIED" if solved else attempts[-1]["verification"]["status"],
    }


def build_synthetic_dataset():
    t1 = trajectory("p1", [attempt(1, True, "VERIFIED", runtime=0.10)], solved=True)
    t2 = trajectory(
        "p2",
        [
            attempt(1, False, "TACTIC_FAILURE", runtime=0.20),
            attempt(2, False, "TACTIC_FAILURE", runtime=0.20, duplicate=True, duplicate_of=1),
            attempt(3, True, "VERIFIED", runtime=0.30),
        ],
        solved=True,
    )
    t3 = trajectory(
        "p3",
        [attempt(i, False, "TACTIC_FAILURE", runtime=0.10) for i in range(1, 6)],
        solved=False,
    )
    t4 = trajectory(
        "p4",
        [attempt(1, False, "TACTIC_FAILURE", runtime=0.10), attempt(2, False, "TIMEOUT", runtime=30.0)],
        solved=False,
    )
    t5 = trajectory("p5", [attempt(1, False, "MALFORMED_CANDIDATE", runtime=0.0)], solved=False)
    return [t1, t2, t3, t4, t5]
