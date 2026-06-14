"""energy_go.serving.main — Application entry point re-export.

Tests import `from energy_go.serving.main import app`.
This module re-exports `app` from `energy_go.serving.app` after ensuring all
routers (including the compare router) are registered.
"""
from energy_go.serving.app import app  # noqa: F401 — re-export for test fixtures

__all__ = ["app"]
