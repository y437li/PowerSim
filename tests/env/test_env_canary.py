# CANARY B1 — gate-safety (criterion B). Deliberate backend-tests failure; throwaway, never merged.
def test_env_canary_deliberate_failure():
    assert False, "canary B1: intentional backend-tests failure — checks must BLOCK"
