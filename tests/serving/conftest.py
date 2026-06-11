"""Serving-tests conftest.

Two concerns:
1.  Starlette 1.x WebSocketTestSession.receive_text() has signature (self) -> str —
    no `timeout` parameter.  The approved tests pass `timeout=5` as a safety guard;
    the underlying anyio portal will still block until a message arrives, so ignoring
    the kwarg is correct when the implementation emits messages correctly.

2.  training_proxy._state is a module-level singleton.  Without a reset between
    tests, a test that starts training leaves state="running", causing the next
    test's POST /training/start to return 409.  The autouse fixture below resets
    the singleton before (and after) every test.
"""
from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# 1. Patch WebSocketTestSession.receive_text to accept `timeout=` kwarg
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _patch_ws_receive_text(monkeypatch):
    """Accept (and ignore) the `timeout` kwarg on WebSocketTestSession.receive_text.

    Starlette 1.x removed the timeout from the synchronous WS test interface.
    The approved test cases pass `timeout=5` as a defensive guard.  Since our
    implementation always emits messages promptly the test will not hang; we
    just need the kwarg not to raise TypeError.
    """
    try:
        from starlette.testclient import WebSocketTestSession
    except ImportError:
        return

    original = WebSocketTestSession.receive_text  # type: ignore[attr-defined]

    def _receive_text_compat(self, timeout=None):  # type: ignore[no-untyped-def]
        return original(self)

    monkeypatch.setattr(WebSocketTestSession, "receive_text", _receive_text_compat)


# ---------------------------------------------------------------------------
# 2. Reset training_proxy singleton state before (and after) every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_training_proxy():
    """Reset the training_proxy module-level singleton between tests.

    The _TrainingState singleton persists across tests in the same process.
    Without this reset a test that starts/pauses training leaves a non-idle
    state and the subsequent test's POST /training/start returns 409.
    """
    try:
        from energy_go.serving import training_proxy  # type: ignore
    except ImportError:
        yield
        return

    def _reset():
        # Cancel any lingering background task
        task = training_proxy._train_task
        if task is not None and not task.done():
            task.cancel()
        training_proxy._train_task = None
        # Re-initialise the singleton in-place (clears subscribers + replay buffer)
        training_proxy._state.__init__()
        # Clear policy cache so tests with different policies don't share state
        if hasattr(training_proxy, "_harness_stub"):
            pass  # harness stub is set per-test via set_harness_stub()

    _reset()
    yield
    _reset()
