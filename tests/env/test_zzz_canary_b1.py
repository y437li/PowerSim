# CANARY B1 — rl-architect gate-safety canary (criterion B, ci_lanes §7.2).
# DELIBERATE FAILURE on a throwaway PR to prove the `checks` aggregator BLOCKS
# when backend-tests fails. NEVER merged.
def test_canary_b1_deliberate_backend_failure():
    assert False, "canary B1: intentional backend-tests failure — `checks` must report FAILURE"
