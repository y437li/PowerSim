"""Harness-specific pytest configuration.

Autouse fixture: join any surviving run-manager background threads after each
test so the process exits cleanly on CI.  Without this, daemon threads that are
inside a JAX/XLA JIT call when the interpreter tears down cause exit 134
(SIGABRT / core dump), which manifests as a CI failure even when all pytest
assertions pass.

Root cause: start_run() spawns a daemon thread (named "run-<id[:8]>") that
calls jax.jit-compiled functions.  If a test ends without calling stop_run(),
the thread may still be executing native XLA code at process exit; daemon
threads are killed abruptly, crashing the XLA runtime.

Defense-in-depth layers (all three active simultaneously):
  1. stop_run() now joins its thread with a 2-second timeout.
  2. RunManager.__del__ calls close() which stops+joins all active threads.
  3. This fixture joins any threads that survived layers 1 and 2.
"""
import threading
import pytest


@pytest.fixture(autouse=True)
def _join_run_threads_on_teardown():
    """Join all live run-manager threads after each test.

    Threads are named 'run-<run_id[:8]>' by RunManager.start_run().
    A 2-second timeout matches stop_run()'s join timeout — enough for any
    in-flight JAX step (typically microseconds with a warm JIT cache).
    """
    yield
    for t in threading.enumerate():
        if t.name.startswith("run-") and t.is_alive():
            t.join(timeout=2.0)
