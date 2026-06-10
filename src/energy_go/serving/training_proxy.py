"""energy_go.serving.training_proxy — Training control proxy (REST + WebSocket).

Implementation pending gate approval (PR #29).
Contract: contracts/serving/training_proxy.md
"""
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter()

# ---------------------------------------------------------------------------
# Test harness: set_harness_stub injects a mock harness for isolated tests.
# The real harness (contracts/harness/training_control.md) is injected at
# startup via dependency injection once that contract lands.
# ---------------------------------------------------------------------------

_harness_stub: list[dict] | None = None


def set_harness_stub(frames: list[dict]) -> None:
    """Inject mock train_metrics frames for test isolation (no live harness)."""
    global _harness_stub
    _harness_stub = frames


# TODO: implement after reviewer APPROVE on PR #29
