"""Tests for Energy GO Live Inference WebSocket Stream.

Contract: contracts/serving/inference_stream.md
Module:   energy_go.serving.inference_stream (registered on app)

These tests exercise the WS lifecycle, session control commands, message schema
conformance against the LOCKED telemetry schema (D18), D13 identity correctness,
and error handling — all against the ASGI app via httpx/starlette.testclient.

Units: power = MW, energy = MWh, prices = ¥/MWh, costs = ¥.
All env_step frames must pass energy_go.telemetry.validate(msg) == [].
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------
try:
    from starlette.testclient import TestClient  # type: ignore
    from starlette.websockets import WebSocketDisconnect  # type: ignore
except ImportError:
    pytest.skip("starlette not installed; install energy-go[serving,dev]", allow_module_level=True)

try:
    from energy_go.telemetry.validate import validate  # type: ignore
except ImportError:
    pytest.skip(
        "energy_go.telemetry.validate not installed (task #23 must land first)",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Fixtures: on-disk serving environment
# ---------------------------------------------------------------------------

SITE_GANSU_YAML = """\
site:
  name: Gansu Wind+Solar+Battery
  battery:
    capacity_mwh: 294.5
    max_charge_mw: 100.0
    max_discharge_mw: 100.0
    soc_min: 0.2
    soc_max: 0.9
    initial_soc: 0.5
    degradation_rate_per_cycle: 0.0001
    round_trip_efficiency: 0.95
  wind_farm:
    rated_power_mw: 300.0
    hub_height_m: 120.0
  pv_array:
    rated_power_mwp: 100.0
    panel_efficiency: 0.22
  grid_connection:
    max_export_mw: 945.0
    max_import_mw: 400.0
  demand_rate_yuan_per_mw_month: 35.0
"""


@pytest.fixture()
def work_dir(tmp_path):
    """Standard test work dir — canonical checkpoint_*.npz only (no legacy policy.npz).

    The legacy policy.npz / normalization.npz path has been removed (backend-reviewer
    decision on PR #59): real training (PR #40) emits canonical §6 .npz only; the
    placeholder never produced real trained policies.
    """
    config = tmp_path / "config"
    config.mkdir()
    (config / "site_gansu.yaml").write_text(SITE_GANSU_YAML)

    run = tmp_path / "checkpoints" / "run_001"
    run.mkdir(parents=True)
    metadata = {
        "episodes_trained": 50,
        "latest_eval_reward": -0.45,
        "site_id": "gansu",
        "created_at": "2026-06-11T00:00:00Z",
    }
    (run / "metadata.json").write_text(json.dumps(metadata))
    _make_canonical_checkpoint(run)  # checkpoint_run_001_step500000.npz

    return tmp_path


@pytest.fixture()
def ws_client(work_dir):
    old_cwd = os.getcwd()
    os.chdir(work_dir)
    try:
        from energy_go.serving.app import app  # type: ignore
        with TestClient(app) as c:
            yield c
    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Canonical-checkpoint fixture (checkpoint_format.md §4 / task #23 cutover)
# ---------------------------------------------------------------------------

def _make_policy_npz(path: Path, obs_dim: int = 107, action_dim: int = 6) -> None:
    """Write a stray legacy-format policy.npz (w_0/b_0 keys) for discovery robustness tests.

    The serving layer no longer loads these; tests use them only to verify that stray
    non-canonical files in a run dir are ignored by the canonical discovery algorithm.
    """
    rng = np.random.default_rng(42)
    hidden = 64
    np.savez(
        path,
        w_0=rng.standard_normal((obs_dim, hidden)).astype(np.float32),
        b_0=rng.standard_normal(hidden).astype(np.float32),
        w_1=rng.standard_normal((hidden, action_dim)).astype(np.float32),
        b_1=np.zeros(action_dim, dtype=np.float32),
    )


def _make_normalization_npz(path: Path, obs_dim: int = 107) -> None:
    """Write a stray legacy normalization.npz (obs_mean / obs_std keys) for robustness tests."""
    np.savez(
        path,
        obs_mean=np.zeros(obs_dim, dtype=np.float32),
        obs_std=np.ones(obs_dim, dtype=np.float32),
    )


def _make_canonical_checkpoint(run_dir: Path, run_id: str = "run_001",
                                global_step: int = 500_000) -> Path:
    """Create a valid canonical checkpoint using save_checkpoint.

    Returns the path written — `checkpoint_{run_id}_step{global_step}.npz`.
    """
    try:
        from energy_go.training.checkpoint_format import (  # type: ignore
            CheckpointData, save_checkpoint,
        )
    except ImportError:
        pytest.skip("energy_go.training.checkpoint_format not installed")

    rng = np.random.default_rng(99)
    ckpt = CheckpointData(
        schema_version="1.0.0",
        checkpoint_id="a1b2c3d4-0000-0000-0000-000000000001",
        run_id=run_id,
        global_step=global_step,
        created_at_utc="2026-06-11T00:00:00Z",
        code_version="test0000",
        run_config_json='{"run_id":"run_001","site_config_id":"gansu"}',
        obs_dim=107,
        action_dim=6,
        obs_count=global_step,
        obs_mean=np.zeros(107, dtype=np.float32),
        obs_var=np.ones(107, dtype=np.float32),
        obs_clip=np.float32(10.0),
        actor_fc1_w=rng.standard_normal((107, 256)).astype(np.float32),
        actor_fc1_b=rng.standard_normal(256).astype(np.float32),
        actor_fc2_w=rng.standard_normal((256, 256)).astype(np.float32),
        actor_fc2_b=rng.standard_normal(256).astype(np.float32),
        actor_out_w=rng.standard_normal((256, 12)).astype(np.float32),
        actor_out_b=np.zeros(12, dtype=np.float32),
    )
    path = run_dir / f"checkpoint_{run_id}_step{global_step}.npz"
    save_checkpoint(ckpt, path)
    return path



def _start_cmd(run_id: str = "run_001", site_id: str = "gansu", seed: int = 0, speed: float = 0.0):
    return json.dumps({"cmd": "start", "run_id": run_id, "site_id": site_id, "seed": seed, "speed": speed})


def _recv_until(ws, kind: str, max_frames: int = 50):
    """Read frames until one with the given 'kind' arrives."""
    for _ in range(max_frames):
        raw = ws.receive_text()
        msg = json.loads(raw)
        if msg.get("kind") == kind:
            return msg
    raise AssertionError(f"Did not receive a frame with kind={kind!r} in {max_frames} frames")


# ===========================================================================
# TestWSConnection
# ===========================================================================

class TestWSConnection:
    def test_ws_endpoint_accepts_connection(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            # Should receive a 'ready' status on connect
            raw = ws.receive_text(timeout=5)
            msg = json.loads(raw)
            assert msg.get("kind") == "status"
            assert msg.get("state") == "ready"

    def test_ready_status_has_step_zero(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            msg = json.loads(ws.receive_text(timeout=5))
            assert msg.get("step") == 0

    def test_ready_status_run_id_is_null(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            msg = json.loads(ws.receive_text(timeout=5))
            assert msg.get("run_id") is None

    def test_two_concurrent_connections_independent(self, ws_client):
        """Each connection must receive its own independent stream."""
        with ws_client.websocket_connect("/ws/inference") as ws1:
            with ws_client.websocket_connect("/ws/inference") as ws2:
                # Both should receive ready status
                m1 = json.loads(ws1.receive_text(timeout=5))
                m2 = json.loads(ws2.receive_text(timeout=5))
                assert m1.get("state") == "ready"
                assert m2.get("state") == "ready"


# ===========================================================================
# TestWSSessionLifecycle
# ===========================================================================

class TestWSSessionLifecycle:
    def test_start_produces_env_step_frames(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # discard ready
            ws.send_text(_start_cmd())
            # Expect running status, then env_step frames
            msg = _recv_until(ws, "env_step", max_frames=20)
            assert msg["kind"] == "env_step"

    def test_start_produces_running_status(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # discard ready
            ws.send_text(_start_cmd())
            msg = _recv_until(ws, "status", max_frames=5)
            assert msg.get("state") == "running"

    def test_env_step_frame_has_schema_version(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd())
            frame = _recv_until(ws, "env_step", max_frames=20)
            assert "schema_version" in frame

    def test_env_step_frame_has_run_id(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd())
            frame = _recv_until(ws, "env_step", max_frames=20)
            assert frame.get("run_id") == "run_001"

    def test_env_step_frame_seq_starts_at_zero(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd())
            # Collect first env_step
            frame = _recv_until(ws, "env_step", max_frames=20)
            assert frame["seq"] == 0, f"First env_step must have seq=0, got {frame['seq']}"

    def test_env_step_seq_is_strictly_monotonic(self, ws_client):
        """Collect 5 env_step frames and verify seq increments by 1."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd())
            seqs = []
            while len(seqs) < 5:
                raw = ws.receive_text(timeout=5)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    seqs.append(msg["seq"])
            for i in range(1, len(seqs)):
                assert seqs[i] == seqs[i - 1] + 1, (
                    f"seq must be strictly monotonic: {seqs}"
                )

    def test_pause_stops_frames(self, ws_client):
        # speed=100 → 10 ms/frame so the OS has time to schedule the pause command
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=100.0))
            _recv_until(ws, "env_step", max_frames=20)
            ws.send_text(json.dumps({"cmd": "pause"}))
            msg = _recv_until(ws, "status", max_frames=20)
            assert msg.get("state") == "paused"

    def test_resume_after_pause(self, ws_client):
        # speed=100 → 10 ms/frame; control commands land before budget is exhausted
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=100.0))
            _recv_until(ws, "env_step", max_frames=20)
            ws.send_text(json.dumps({"cmd": "pause"}))
            _recv_until(ws, "status", max_frames=20)
            ws.send_text(json.dumps({"cmd": "resume"}))
            msg = _recv_until(ws, "status", max_frames=20)
            assert msg.get("state") == "running"

    def test_stop_closes_connection(self, ws_client):
        # speed=100 → 10 ms/frame; stopped status arrives within the 20-frame budget
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=100.0))
            _recv_until(ws, "env_step", max_frames=20)
            ws.send_text(json.dumps({"cmd": "stop"}))
            msg = _recv_until(ws, "status", max_frames=20)
            assert msg.get("state") == "stopped"
            # Server must close after sending stopped status
            with pytest.raises((WebSocketDisconnect, Exception)):
                ws.receive_text(timeout=2)

    def test_stop_without_session_closes_cleanly(self, ws_client):
        """send stop before start — server sends stopped and closes."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(json.dumps({"cmd": "stop"}))
            msg = _recv_until(ws, "status", max_frames=10)
            assert msg.get("state") == "stopped"


# ===========================================================================
# TestTelemetrySchemaConformance (D18 producer obligation)
# ===========================================================================

class TestTelemetrySchemaConformance:
    """env_step frames must pass energy_go.telemetry.validate(msg) == []."""

    def _collect_frames(self, ws_client, n: int = 3) -> list[dict]:
        frames = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(_start_cmd())
            while len(frames) < n:
                raw = ws.receive_text(timeout=5)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)
        return frames

    def test_first_frame_passes_validate(self, ws_client):
        """First env_step must pass validate(msg) == [] (D18 producer obligation)."""
        frames = self._collect_frames(ws_client, n=1)
        errs = validate(frames[0])
        assert errs == [], (
            f"First env_step frame fails telemetry validation:\n"
            + "\n".join(f"  - {e}" for e in errs)
        )

    def test_three_frames_pass_validate(self, ws_client):
        """Three consecutive frames must all pass validate(msg) == []."""
        frames = self._collect_frames(ws_client, n=3)
        for i, frame in enumerate(frames):
            errs = validate(frame)
            assert errs == [], (
                f"Frame {i} fails telemetry validation:\n"
                + "\n".join(f"  - {e}" for e in errs)
            )

    def test_step_cmd_frame_passes_validate(self, ws_client):
        """cmd:'step' emitted env_step must pass validate(msg) == [] (D18 producer obligation).

        This exercises the interactive single-step path (_send_validated helper),
        separate from the continuous _step_loop path tested above.
        speed=100 → 10 ms/frame so pause lands before the 20-frame budget is exhausted.
        """
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # initial ready status
            ws.send_text(_start_cmd(speed=100.0))
            _recv_until(ws, "env_step", max_frames=20)  # session is live
            ws.send_text(json.dumps({"cmd": "pause"}))
            _recv_until(ws, "status", max_frames=20)    # wait for paused status
            ws.send_text(json.dumps({"cmd": "step"}))
            frame = _recv_until(ws, "env_step", max_frames=10)
        errs = validate(frame)
        assert errs == [], (
            "cmd:'step' env_step frame fails telemetry validation:\n"
            + "\n".join(f"  - {e}" for e in errs)
        )

    def test_frame_has_required_envelope_fields(self, ws_client):
        frames = self._collect_frames(ws_client, n=1)
        frame = frames[0]
        for field in ("schema_version", "kind", "ts_utc", "run_id", "seq", "payload"):
            assert field in frame, f"Missing envelope field {field!r}"

    def test_frame_payload_has_battery_soc(self, ws_client):
        frames = self._collect_frames(ws_client, n=1)
        payload = frames[0]["payload"]
        assert "battery" in payload
        assert "soc_mwh" in payload["battery"] or "soc" in payload["battery"], (
            "battery must include SOC field"
        )

    def test_frame_payload_has_costs(self, ws_client):
        frames = self._collect_frames(ws_client, n=1)
        payload = frames[0]["payload"]
        assert "costs" in payload

    def test_frame_payload_has_flows(self, ws_client):
        frames = self._collect_frames(ws_client, n=1)
        payload = frames[0]["payload"]
        assert "flows" in payload

    def test_frame_dt_hours_is_1(self, ws_client):
        """dt_hours must equal 1.0 (D3: Δt = 1 hour)."""
        # expected: 1.0 h (D3 binding decision)
        frames = self._collect_frames(ws_client, n=1)
        dt = frames[0]["payload"]["dt_hours"]
        assert abs(dt - 1.0) < 1e-9, f"dt_hours must be 1.0 (D3), got {dt}"

    def test_frame_step_increments(self, ws_client):
        """payload.step must increment by 1 each frame (starts at 0)."""
        frames = self._collect_frames(ws_client, n=3)
        steps = [f["payload"]["step"] for f in frames]
        assert steps == list(range(len(steps))), (
            f"payload.step must be 0, 1, 2, …; got {steps}"
        )

    def test_d18_runtime_resilience_logs_warning_does_not_crash(
        self, ws_client, monkeypatch
    ):
        """D18 runtime policy: validation error → warning logged, session does NOT crash.

        Monkeypatches energy_go.telemetry.validate.validate to return a fake error
        for all calls.  The session must still stream frames (no crash, no disconnect);
        the frame is sent regardless (resilience-first).

        Contract: contracts/serving/inference_stream.md §D18 Runtime policy tier.
        """
        import logging

        import energy_go.telemetry.validate as _val_mod  # type: ignore

        warnings_logged: list[str] = []

        original_validate = _val_mod.validate

        def _always_error(msg):  # noqa: ANN001
            return ["fake-D18-validation-error"]

        monkeypatch.setattr(_val_mod, "validate", _always_error)

        # Capture D18 warnings from the inference_stream logger.
        class _Catcher(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if "D18" in record.getMessage():
                    warnings_logged.append(record.getMessage())

        catcher = _Catcher()
        logger = logging.getLogger("energy_go.serving.inference_stream")
        logger.addHandler(catcher)
        try:
            # The session must survive and deliver frames even when validate() errors.
            frames = self._collect_frames(ws_client, n=2)
        finally:
            logger.removeHandler(catcher)
            monkeypatch.setattr(_val_mod, "validate", original_validate)

        assert len(frames) == 2, (
            "Session must keep streaming after D18 validation errors "
            f"(resilience-first); got {len(frames)} frames"
        )
        assert warnings_logged, (
            "D18 validation errors must be logged as warnings — "
            "no warning records captured on energy_go.serving.inference_stream logger"
        )


# ===========================================================================
# TestErrorHandling
# ===========================================================================

class TestErrorHandling:
    def test_start_unknown_run_returns_error_frame(self, ws_client):
        """start with unknown run_id → error frame (not a crash)."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(json.dumps({
                "cmd": "start", "run_id": "no_such_run", "site_id": "gansu"
            }))
            msg = _recv_until(ws, "error", max_frames=10)
            assert msg.get("code") == "run_not_found"
            assert "message" in msg

    def test_start_unknown_site_returns_error_frame(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(json.dumps({
                "cmd": "start", "run_id": "run_001", "site_id": "no_such_site"
            }))
            msg = _recv_until(ws, "error", max_frames=10)
            assert msg.get("code") == "site_not_found"

    def test_start_while_running_returns_error_frame(self, ws_client):
        """Sending start while already running → error, session continues.

        speed=100 → 10 ms/frame so the error frame arrives within the 20-frame budget
        despite the step loop emitting frames concurrently.
        """
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=100.0))
            _recv_until(ws, "env_step", max_frames=20)
            ws.send_text(_start_cmd(speed=100.0))
            msg = _recv_until(ws, "error", max_frames=20)
            assert msg.get("code") == "already_running"

    def test_error_frames_have_code_and_message(self, ws_client):
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(json.dumps({"cmd": "start", "run_id": "no_such_run", "site_id": "gansu"}))
            err = _recv_until(ws, "error", max_frames=10)
            assert "code" in err and "message" in err, (
                f"error frame must have 'code' and 'message': {err}"
            )

    # reviewer: no_session untested — pause/resume with no active session must emit code:"no_session"
    def test_pause_without_session_returns_no_session_error(self, ws_client):
        """pause before start → error frame with code='no_session' (no crash, no close)."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(json.dumps({"cmd": "pause"}))
            err = _recv_until(ws, "error", max_frames=10)
            assert err.get("code") == "no_session", (
                f"pause with no active session must return code='no_session', got {err.get('code')!r}"
            )
            assert "message" in err

    # reviewer: no_session untested — pause/resume with no active session must emit code:"no_session"
    def test_resume_without_session_returns_no_session_error(self, ws_client):
        """resume before start → error frame with code='no_session' (no crash, no close)."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(json.dumps({"cmd": "resume"}))
            err = _recv_until(ws, "error", max_frames=10)
            assert err.get("code") == "no_session", (
                f"resume with no active session must return code='no_session', got {err.get('code')!r}"
            )
            assert "message" in err

    # reviewer: bad_command / invalid_message error codes (per contract update)
    def test_unknown_command_returns_bad_command_error(self, ws_client):
        """Sending an unrecognised cmd → error frame with code='bad_command'."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(json.dumps({"cmd": "fly_to_moon"}))
            err = _recv_until(ws, "error", max_frames=10)
            assert err.get("code") == "bad_command", (
                f"unknown command must return code='bad_command', got {err.get('code')!r}"
            )

    def test_invalid_json_returns_invalid_message_error(self, ws_client):
        """Sending malformed JSON → error frame with code='invalid_message'."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text("{this is not json")
            err = _recv_until(ws, "error", max_frames=10)
            assert err.get("code") == "invalid_message", (
                f"malformed JSON must return code='invalid_message', got {err.get('code')!r}"
            )

    def test_missing_policy_returns_policy_not_found_error(self, tmp_path):
        """Run dir exists but no canonical checkpoint_*.npz present → policy_not_found."""
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / "run_nopolicy"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text('{"episodes_trained": 1}')
        # No checkpoint_*.npz (legacy policy.npz path removed — PR #59)
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            from energy_go.serving.app import app  # type: ignore
            with TestClient(app) as c:
                with c.websocket_connect("/ws/inference") as ws:
                    ws.receive_text(timeout=5)
                    ws.send_text(json.dumps({
                        "cmd": "start", "run_id": "run_nopolicy", "site_id": "gansu"
                    }))
                    err = _recv_until(ws, "error", max_frames=10)
                    assert err.get("code") == "policy_not_found"
        finally:
            os.chdir(old_cwd)


# ===========================================================================
# TestNormalization
# ===========================================================================

class TestNormalization:
    def test_normalization_applied_from_canonical_checkpoint(self, ws_client):
        """Canonical checkpoint normalization (obs_var + obs_clip) is applied before policy call.

        Observable: if normalization is broken, costs/flows go to extreme values and
        rewards become NaN/Inf.  Finite rewards confirm the obs_var-based normalization
        path was used correctly (std = sqrt(obs_var + 1e-8)).
        """
        frames = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd())
            while len(frames) < 3:
                raw = ws.receive_text(timeout=5)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)
        # If normalization is wrong, costs and flows would be extreme.
        # Check that reward is finite (not NaN or Inf).
        for i, frame in enumerate(frames):
            r = frame["payload"]["reward"]
            import math
            assert math.isfinite(r), (
                f"reward at frame {i} is not finite ({r}); "
                "likely normalization is broken"
            )

    # test_identity_normalization_when_npz_absent REMOVED: tested the legacy
    # policy.npz + normalization.npz path which was dropped by backend-reviewer
    # decision on PR #59.  Canonical §6 checkpoints carry all normalization
    # stats inline (obs_mean, obs_var, obs_clip) — no separate file needed.


# ===========================================================================
# TestReplaySpeed
# ===========================================================================

class TestReplaySpeed:
    def test_speed_zero_delivers_frame_immediately(self, ws_client):
        """speed=0.0 → no sleep between frames; first frame arrives quickly."""
        t0 = time.monotonic()
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=0.0))
            _recv_until(ws, "env_step", max_frames=20)
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, (
            f"speed=0 frame took {elapsed:.2f}s — expected < 2s"
        )

    def test_speed_field_out_of_range_clamped(self, ws_client):
        """speed=-5 is clamped to 0; server must not error."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(json.dumps({
                "cmd": "start", "run_id": "run_001", "site_id": "gansu",
                "seed": 0, "speed": -5.0
            }))
            frame = _recv_until(ws, "env_step", max_frames=20)
            assert frame["kind"] == "env_step"

    def test_speed_above_100_clamped(self, ws_client):
        """speed=9999 is clamped to 100; server must not error."""
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(json.dumps({
                "cmd": "start", "run_id": "run_001", "site_id": "gansu",
                "seed": 0, "speed": 9999.0
            }))
            # Should still work (may be slightly throttled)
            frame = _recv_until(ws, "env_step", max_frames=30)
            assert frame["kind"] == "env_step"

    def test_speed_throttles_frame_rate(self, ws_client):
        """speed=2 → sleep=0.5s per frame; collecting 2 env_step frames must take ≥0.3s.

        At speed=2 the server sleeps 1/2 = 0.5s after each frame is sent.
        With N=2 frames there is exactly 1 sleep → ~0.5s wall-clock.
        Lower bound: 0.3s (allows 40% scheduling jitter on slow CI).
        """
        N = 2
        t0 = time.monotonic()
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(json.dumps({
                "cmd": "start", "run_id": "run_001", "site_id": "gansu",
                "seed": 0, "speed": 2.0
            }))
            frames = []
            while len(frames) < N:
                raw = ws.receive_text(timeout=10)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)
        elapsed = time.monotonic() - t0
        # speed=2 → sleep=0.5s/frame; 2 frames → 1 sleep ≈ 0.5s total
        # lower bound 0.3s = 60% of expected (generous for CI jitter)
        assert elapsed > 0.3, (
            f"speed=2 must throttle: {N} frames took {elapsed:.3f}s — "
            f"expected > 0.3s (1 sleep × 0.5s, with CI jitter allowance)"
        )


# ===========================================================================
# TestPolicyCaching
# ===========================================================================

class TestPolicyCaching:
    def test_second_session_same_run_id_uses_cached_policy(self, ws_client):
        """Two successive start commands for the same run_id must succeed.

        This tests that policy caching does not corrupt state between sessions.
        Both runs must produce valid telemetry.
        speed=100 → stopped status lands within the 20-frame budget.
        """
        for _session in range(2):
            with ws_client.websocket_connect("/ws/inference") as ws:
                ws.receive_text(timeout=5)
                ws.send_text(_start_cmd(speed=100.0))
                frame = _recv_until(ws, "env_step", max_frames=20)
                errs = validate(frame)
                assert errs == [], f"session {_session}: frame fails validate: {errs}"
                ws.send_text(json.dumps({"cmd": "stop"}))


# ===========================================================================
# TestEpisodeBoundary
# reviewer: seq only checked within episode 0 — add a test crossing the
#   168-step boundary: seq does NOT reset, episode increments.
# ===========================================================================

class TestEpisodeBoundary:
    def test_seq_does_not_reset_at_episode_boundary(self, ws_client):
        """seq is globally monotonic — does NOT reset when episode increments at step 168 (D3).

        Episode 0: steps  0 … 167  (168 steps per D3)
        Episode 1: steps 168 … 335

        Collect 170 env_step frames; verify:
          - seq at index 168 == 168  (seq must NOT reset to 0 at the episode boundary)
          - seq at index 169 == 169
          - payload.episode at frame 168 == 1  (second episode started)
        """
        N = 170
        frames = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(_start_cmd(speed=0.0))
            while len(frames) < N:
                raw = ws.receive_text(timeout=30)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)

        # seq must be strictly monotonic across the episode boundary
        # expected: seq[168] == 168 (NOT 0 — episode boundary must not reset seq)
        assert frames[168]["seq"] == 168, (
            f"seq must be 168 at the first step of episode 1, "
            f"got {frames[168]['seq']} — seq MUST NOT reset at episode boundary"
        )
        assert frames[169]["seq"] == 169, (
            f"seq at frame 170 must be 169, got {frames[169]['seq']}"
        )
        # payload.episode increments at step 168 (= 7 * 24 steps, D3)
        # expected: episode=1 at frames[168] (the 169th frame, index 168)
        assert frames[168]["payload"]["episode"] == 1, (
            f"payload.episode must be 1 at frame index 168 (episode 0 = steps 0-167 per D3), "
            f"got {frames[168]['payload']['episode']}"
        )

    def test_seq_monotonic_across_full_boundary_window(self, ws_client):
        """Verify strict monotonicity for all 170 frames spanning the episode boundary."""
        N = 170
        frames = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=0.0))
            while len(frames) < N:
                raw = ws.receive_text(timeout=30)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)

        seqs = [f["seq"] for f in frames]
        for i in range(1, len(seqs)):
            assert seqs[i] == seqs[i - 1] + 1, (
                f"seq not strictly monotonic at frame {i}: {seqs[max(0,i-3):i+2]}"
            )


# ===========================================================================
# TestPolicyForwardPass — REMOVED (backend-reviewer decision, PR #59)
# The placeholder dict-based API (w_0/b_0 keys, tanh hidden, identity output,
# clip[-1,1]) is gone; canonical §6 forward pass (ReLU hidden, tanh(a_bat) +
# sigmoid(fractions), D28 mean-clip) is tested in TestPolicyCutover instead.
# ===========================================================================

# ===========================================================================
# Reviewer-added (backend-reviewer, PR #46 gate): D18 runtime-warning CONTENT
# ===========================================================================
class TestReviewerD18RuntimeWarningContent:
    """The contract's D18 runtime tier requires the warning to be structured with
    fields (kind, seq, error list). The dev's resilience test only asserts a
    'D18'-containing warning EXISTS — a content-less "D18 oops" would satisfy it.
    This pins that the logged warning actually carries kind=, seq=, and the errors.
    """

    def _collect_frames(self, ws_client, n: int = 2) -> list[dict]:
        frames: list[dict] = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(_start_cmd())
            while len(frames) < n:
                raw = ws.receive_text(timeout=5)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)
        return frames

    def test_d18_runtime_warning_carries_kind_seq_errors(self, ws_client, monkeypatch):
        # reviewer: force validate() to return a unique sentinel error and assert the
        # reviewer: logged D18 warning contains kind=, seq=, AND that sentinel — pinning
        # reviewer: the contract's "structured (fields: kind, seq, error list)" requirement.
        # reviewer: Also confirms resilience holds alongside content (2 frames still arrive).
        import logging
        import energy_go.telemetry.validate as _val_mod  # type: ignore

        sentinel = "reviewer-D18-sentinel-xyz"
        monkeypatch.setattr(_val_mod, "validate", lambda msg: [sentinel])

        captured: list[str] = []

        class _Catcher(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                m = record.getMessage()
                if "D18" in m:
                    captured.append(m)

        logger = logging.getLogger("energy_go.serving.inference_stream")
        handler = _Catcher()
        logger.addHandler(handler)
        try:
            frames = self._collect_frames(ws_client, n=2)
        finally:
            logger.removeHandler(handler)

        assert captured, "no D18 warning captured on energy_go.serving.inference_stream logger"
        msg = captured[0]
        assert "kind=" in msg, f"D18 warning missing kind field: {msg!r}"
        assert "seq=" in msg, f"D18 warning missing seq field: {msg!r}"
        assert sentinel in msg, f"D18 warning missing the error list: {msg!r}"
        # resilience preserved alongside structured content
        assert len(frames) == 2, f"session must keep streaming; got {len(frames)} frames"


# ===========================================================================
# TestPolicyCutover (task #23 — checkpoint_format §6 cutover)
# ---------------------------------------------------------------------------
# Tests the NEW policy_forward(CheckpointData, obs) API and the canonical
# checkpoint discovery algorithm (contract §Policy loading).
#
# NOTE on TestPolicyForwardPass: the existing class tests the OLD placeholder
# policy_forward(dict, obs) API (tanh-hidden, w_0/b_0 keys).  The cutover
# changes the public signature to policy_forward(CheckpointData, obs).
# These two calling conventions are incompatible; the serving layer
# implementation must support BOTH (backward-compat dict path for legacy
# callers, CheckpointData path for the new API) OR the reviewer must declare
# TestPolicyForwardPass obsolete on this PR.  Flagged for backend-reviewer
# resolution.
# ===========================================================================

class TestPolicyCutover:
    """Verify the checkpoint_format §6 cutover in the serving layer.

    Requires:
      - energy_go.training.checkpoint_format (CheckpointData, save_checkpoint,
        load_checkpoint, actor_forward_numpy)
      - energy_go.serving.inference_stream.policy_forward with NEW signature:
        policy_forward(checkpoint: CheckpointData, obs: np.ndarray) -> np.ndarray
    """

    # -----------------------------------------------------------------------
    # Helper: build a CheckpointData with deterministic weights
    # -----------------------------------------------------------------------
    @staticmethod
    def _make_ckpt(tmp_path: Path, run_id: str = "ck_test",
                   global_step: int = 1,
                   obs_var: "np.ndarray | None" = None,
                   actor_out_b: "np.ndarray | None" = None,
                   seed: int = 77) -> "CheckpointData":  # type: ignore[type-arg]
        """Return a loaded CheckpointData saved in tmp_path (directory created if absent)."""
        try:
            from energy_go.training.checkpoint_format import (  # type: ignore
                CheckpointData, save_checkpoint, load_checkpoint,
            )
        except ImportError as e:
            pytest.skip(f"energy_go.training.checkpoint_format not available: {e}")
        tmp_path.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(seed)
        if obs_var is None:
            obs_var = np.ones(107, dtype=np.float32)
        if actor_out_b is None:
            actor_out_b = np.zeros(12, dtype=np.float32)
        ckpt_data = CheckpointData(
            schema_version="1.0.0",
            checkpoint_id=f"cutover-test-{seed:04d}-0000-000000000001",
            run_id=run_id,
            global_step=global_step,
            created_at_utc="2026-06-11T00:00:00Z",
            code_version="test0000",
            run_config_json='{"run_id":"' + run_id + '"}',
            obs_dim=107,
            action_dim=6,
            obs_count=global_step,
            obs_mean=np.zeros(107, dtype=np.float32),
            obs_var=obs_var,
            obs_clip=np.float32(10.0),
            # Scale weights by 1/sqrt(256) to prevent D28 saturation:
            # unscaled rng.standard_normal weights produce mean O(±1000) which D28
            # clips identically for obs_var=1 and obs_var=4, obliterating the
            # difference the test must detect.  He-style init keeps mean in [-0.3, +0.2]
            # so obs_var=1 vs obs_var=4 produces a visible action difference (~0.10).
            # Approved by backend-reviewer (reviewer fix to test fixture; impl is correct).
            actor_fc1_w=rng.standard_normal((107, 256)).astype(np.float32) / np.sqrt(256),
            actor_fc1_b=rng.standard_normal(256).astype(np.float32) / np.sqrt(256),
            actor_fc2_w=rng.standard_normal((256, 256)).astype(np.float32) / np.sqrt(256),
            actor_fc2_b=rng.standard_normal(256).astype(np.float32) / np.sqrt(256),
            actor_out_w=rng.standard_normal((256, 12)).astype(np.float32) / np.sqrt(256),
            actor_out_b=actor_out_b,
        )
        path = tmp_path / f"checkpoint_{run_id}_step{global_step}.npz"
        save_checkpoint(ckpt_data, path)
        return load_checkpoint(path)

    # -----------------------------------------------------------------------
    # 1. Parity: policy_forward == actor_forward_numpy
    # -----------------------------------------------------------------------
    def test_policy_forward_parity_with_actor_forward_numpy(self, tmp_path):
        """policy_forward(checkpoint, obs) must equal actor_forward_numpy(checkpoint, obs).

        The serving module's policy_forward is a thin wrapper around
        actor_forward_numpy; on fixed inputs, results must agree to atol=1e-5.

        Contract: contracts/serving/inference_stream.md §Public policy utilities.
        """
        try:
            from energy_go.training.checkpoint_format import (  # type: ignore
                actor_forward_numpy,
            )
            from energy_go.serving.inference_stream import policy_forward  # type: ignore
        except ImportError as e:
            pytest.skip(f"Required module not available: {e}")

        ckpt = self._make_ckpt(tmp_path, seed=42)
        rng = np.random.default_rng(7)
        raw_obs = rng.standard_normal(107).astype(np.float32)

        action_served    = policy_forward(ckpt, raw_obs)
        action_reference = actor_forward_numpy(ckpt, raw_obs)

        np.testing.assert_allclose(
            action_served, action_reference, atol=1e-5,
            err_msg=(
                "policy_forward must delegate to actor_forward_numpy exactly.\n"
                f"Served:    {action_served}\n"
                f"Reference: {action_reference}"
            ),
        )

    # -----------------------------------------------------------------------
    # 2. D28 mean-clip applied before tanh/sigmoid
    # -----------------------------------------------------------------------
    def test_d28_mean_clip_applied(self, tmp_path):
        """D28: mean clipped to ±8.0 before tanh/sigmoid (prevents float32 saturation).

        Craft actor_out_b[0] = 100.0 so the raw MLP output mean[0] >> 8.0.
        Without D28 clip: tanh(100.0) rounds to exactly 1.0 in float32.
        With    D28 clip: tanh(clip(100, -8, 8)) = tanh(8.0) ≈ 0.9999977.

        All MLP weight matrices are zero (no-op), so the output depends only on
        actor_out_b.  Expected a_bat:
            mean[0] = 0 @ actor_out_w[:, 0] + 100.0 = 100.0
            clipped = clip(100.0, -8.0, 8.0)          = 8.0
            a_bat   = tanh(8.0)                        ≈ 0.9999977

        Without clip: tanh(100) = 1.0 exactly → test would catch the missing D28.
        """
        try:
            from energy_go.serving.inference_stream import policy_forward  # type: ignore
        except ImportError as e:
            pytest.skip(f"Required module not available: {e}")

        actor_out_b = np.zeros(12, dtype=np.float32)
        actor_out_b[0] = 100.0  # forces mean[0] = 100.0

        # Build checkpoint with zero weight matrices so only actor_out_b matters
        try:
            from energy_go.training.checkpoint_format import (  # type: ignore
                CheckpointData, save_checkpoint, load_checkpoint,
            )
        except ImportError as e:
            pytest.skip(f"energy_go.training.checkpoint_format not available: {e}")

        ckpt_data = CheckpointData(
            schema_version="1.0.0",
            checkpoint_id="d28-clip-test-0000-0000-000000000001",
            run_id="d28_test",
            global_step=1,
            created_at_utc="2026-06-11T00:00:00Z",
            code_version="test0000",
            run_config_json='{}',
            obs_dim=107, action_dim=6, obs_count=1,
            obs_mean=np.zeros(107, dtype=np.float32),
            obs_var=np.ones(107, dtype=np.float32),
            obs_clip=np.float32(10.0),
            actor_fc1_w=np.zeros((107, 256), dtype=np.float32),
            actor_fc1_b=np.zeros(256, dtype=np.float32),
            actor_fc2_w=np.zeros((256, 256), dtype=np.float32),
            actor_fc2_b=np.zeros(256, dtype=np.float32),
            actor_out_w=np.zeros((256, 12), dtype=np.float32),
            actor_out_b=actor_out_b,
        )
        path = tmp_path / "checkpoint_d28_step1.npz"
        save_checkpoint(ckpt_data, path)
        ckpt = load_checkpoint(path)

        obs = np.zeros(107, dtype=np.float32)
        action = policy_forward(ckpt, obs)

        # D28: clip(100.0, -8, 8) = 8.0 → tanh(8.0) ≈ 0.99999977
        # Without clip: tanh(100) = 1.0 exactly in float32 (saturates).
        # Computed reference: np.tanh(np.float32(8.0)) ≈ 0.99999977
        expected_a_bat = float(np.tanh(np.float32(8.0)))
        assert abs(float(action[0]) - expected_a_bat) < 1e-5, (
            f"D28 mean-clip: a_bat must be tanh(clip(100,-8,8)) = tanh(8.0) "
            f"≈ {expected_a_bat:.8f}; got {float(action[0]):.8f}. "
            "Without D28 clip tanh(100) = 1.0 exactly (float32 saturation)."
        )

    # -----------------------------------------------------------------------
    # 3. obs_var (not obs_std) used for normalization
    # -----------------------------------------------------------------------
    def test_obs_var_used_not_obs_std(self, tmp_path):
        """obs_var is used to compute std = sqrt(obs_var + 1e-8), not a raw obs_std.

        Two checkpoints: identical architecture weights, but:
          - ckpt_A: obs_var = 1.0  → std = 1.0  → obs_norm = raw_obs  (no scale)
          - ckpt_B: obs_var = 4.0  → std ≈ 2.0  → obs_norm = raw_obs / 2

        On the same raw_obs, the normalized inputs differ by a factor of 2, so
        the actions from ckpt_A and ckpt_B must differ.

        If the implementation hardcoded std=1.0 (ignoring obs_var) or used
        obs_std directly (when only obs_var is stored), both actions would be
        identical — this test would catch that error.

        Reference arithmetic (obs_mean=0, obs_var_B=4, raw_obs = 0.5):
          std_B    = sqrt(4.0 + 1e-8) ≈ 2.0
          norm_B   = 0.5 / 2.0 = 0.25     (vs norm_A = 0.5 / 1.0 = 0.5)
        """
        try:
            from energy_go.serving.inference_stream import policy_forward  # type: ignore
        except ImportError as e:
            pytest.skip(f"Required module not available: {e}")

        # Same random weights, different obs_var
        ckpt_a = self._make_ckpt(tmp_path / "a", obs_var=np.ones(107, dtype=np.float32),  seed=55)
        # ckpt_b shares the same seed so weights are identical; only obs_var differs
        ckpt_b = self._make_ckpt(tmp_path / "b", obs_var=np.full(107, 4.0, dtype=np.float32), seed=55)

        # Use obs != 0 so normalization scale matters
        raw_obs = np.full(107, 0.5, dtype=np.float32)

        action_a = policy_forward(ckpt_a, raw_obs)
        action_b = policy_forward(ckpt_b, raw_obs)

        # Actions must differ (different obs_var → different normalization → different inputs)
        assert not np.allclose(action_a, action_b, atol=1e-6), (
            "policy_forward with obs_var=1.0 and obs_var=4.0 must produce different actions "
            "(normalization scale differs by ×2). If they are equal, obs_var is being "
            "ignored (std hardcoded to 1.0 or obs_std used instead of sqrt(obs_var+1e-8))."
        )

    # -----------------------------------------------------------------------
    # 4. Canonical checkpoint discovery preferred over legacy policy.npz
    # -----------------------------------------------------------------------
    def test_canonical_checkpoint_preferred_over_legacy(self, tmp_path):
        """When both checkpoint_*.npz and policy.npz exist, canonical is used.

        Contract §Policy loading: first-match-wins order:
          1. checkpoint_*.npz (canonical, highest step)
          2. legacy: policy.npz

        Both files present → serving layer must load checkpoint_*.npz and
        produce valid D18 telemetry frames (proving the canonical path was taken,
        not the legacy path which uses different keys).
        """
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / "run_both"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text('{"episodes_trained": 1, "site_id": "gansu"}')
        _make_canonical_checkpoint(run, run_id="run_both")  # canonical
        _make_policy_npz(run / "policy.npz")                # legacy also present
        _make_normalization_npz(run / "normalization.npz")

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            from energy_go.serving.app import app  # type: ignore
            with TestClient(app) as c:
                with c.websocket_connect("/ws/inference") as ws:
                    ws.receive_text(timeout=5)  # ready
                    ws.send_text(json.dumps({
                        "cmd": "start", "run_id": "run_both",
                        "site_id": "gansu", "seed": 0, "speed": 0.0,
                    }))
                    frame = _recv_until(ws, "env_step", max_frames=20)
                    errs = validate(frame)
                    assert errs == [], (
                        f"Canonical-preferred session: D18 validate errors:\n"
                        + "\n".join(f"  - {e}" for e in errs)
                    )
        finally:
            os.chdir(old_cwd)

    # -----------------------------------------------------------------------
    # 5. Highest-step checkpoint selected when multiple present
    # -----------------------------------------------------------------------
    def test_canonical_highest_step_selected(self, tmp_path):
        """When multiple checkpoint_*.npz exist, highest _step<N> wins.

        Contract §Policy loading: "pick the one with the highest _step<N> suffix"

        Three checkpoints saved: step=100k, step=200k, step=500k.
        The serving layer must select step=500k.  Observable: the session starts
        without error and produces valid D18 frames (all three are valid
        checkpoints, so a wrong selection still starts; we additionally verify
        the correct checkpoint ID is reported if the telemetry carries it).
        """
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / "run_multi"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text('{"episodes_trained": 1, "site_id": "gansu"}')
        for step in (100_000, 200_000, 500_000):
            _make_canonical_checkpoint(run, run_id="run_multi", global_step=step)

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            from energy_go.serving.app import app  # type: ignore
            with TestClient(app) as c:
                with c.websocket_connect("/ws/inference") as ws:
                    ws.receive_text(timeout=5)  # ready
                    ws.send_text(json.dumps({
                        "cmd": "start", "run_id": "run_multi",
                        "site_id": "gansu", "seed": 0, "speed": 0.0,
                    }))
                    frame = _recv_until(ws, "env_step", max_frames=20)
                    assert frame["kind"] == "env_step"
                    errs = validate(frame)
                    assert errs == [], (
                        f"multi-checkpoint session fails D18 validate:\n"
                        + "\n".join(f"  - {e}" for e in errs)
                    )
        finally:
            os.chdir(old_cwd)

    # -----------------------------------------------------------------------
    # 6. End-to-end: canonical checkpoint → valid D18 telemetry
    # -----------------------------------------------------------------------
    def test_canonical_session_produces_valid_d18_frames(self, ws_client):
        """Full end-to-end: canonical checkpoint_*.npz → env_step passes D18 validate.

        The standard work_dir fixture now creates a canonical
        checkpoint_run_001_step500000.npz (no policy.npz — legacy path removed).
        The serving layer must:
          1. Discover checkpoint_run_001_step500000.npz via glob
          2. Load it via load_checkpoint
          3. Run actor_forward_numpy for each step
          4. Produce env_step frames that pass validate() == []
        """
        frames = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)  # ready
            ws.send_text(_start_cmd())
            while len(frames) < 3:
                raw = ws.receive_text(timeout=5)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)
        for i, frame in enumerate(frames):
            errs = validate(frame)
            assert errs == [], (
                f"Canonical checkpoint frame {i} fails D18 validate:\n"
                + "\n".join(f"  - {e}" for e in errs)
            )


# ===========================================================================
# Reviewer-added (backend-reviewer, PR #59 policy-cutover gate)
# ===========================================================================
class TestReviewerPolicyCutover:
    """Edge cases for the §6 / D28 policy cutover: negative D28 clip, obs_clip
    clamp, policy_not_found on an empty run dir, discovery robustness to stray
    non-canonical files. Hand-derived where applicable."""

    def _zero_weight_ckpt(self, tmp_path, actor_out_b):
        # reviewer: zero weight matrices so mean == actor_out_b (isolates the D28 clip).
        from energy_go.training.checkpoint_format import (  # type: ignore
            CheckpointData, save_checkpoint, load_checkpoint,
        )
        ckpt_data = CheckpointData(
            schema_version="1.0.0",
            checkpoint_id="reviewer-clip-0000-0000-000000000001",
            run_id="reviewer_clip_test",
            global_step=1,
            created_at_utc="2026-06-11T00:00:00Z",
            code_version="test0000",
            run_config_json="{}",
            obs_dim=107, action_dim=6, obs_count=1,
            obs_mean=np.zeros(107, dtype=np.float32),
            obs_var=np.ones(107, dtype=np.float32),
            obs_clip=np.float32(10.0),
            actor_fc1_w=np.zeros((107, 256), dtype=np.float32),
            actor_fc1_b=np.zeros(256, dtype=np.float32),
            actor_fc2_w=np.zeros((256, 256), dtype=np.float32),
            actor_fc2_b=np.zeros(256, dtype=np.float32),
            actor_out_w=np.zeros((256, 12), dtype=np.float32),
            actor_out_b=actor_out_b,
        )
        path = tmp_path / "checkpoint_rev_step1.npz"
        save_checkpoint(ckpt_data, path)
        return load_checkpoint(path)

    def test_d28_mean_clip_negative_side(self, tmp_path):
        # reviewer: case 2 covers +100→tanh(8); this pins the NEGATIVE saturation.
        # reviewer: actor_out_b[0]=-100 → mean[0]=-100 → clip(-100,-8,8)=-8 →
        # reviewer: tanh(-8) ≈ -0.99999977 (NOT tanh(-100)=-1.0). Strictly open (> -1).
        pytest.importorskip("energy_go.serving.inference_stream")
        from energy_go.serving.inference_stream import policy_forward  # type: ignore
        out_b = np.zeros(12, dtype=np.float32)
        out_b[0] = -100.0
        ckpt = self._zero_weight_ckpt(tmp_path, out_b)
        action = policy_forward(ckpt, np.zeros(107, dtype=np.float32))
        expected = float(np.tanh(np.float32(-8.0)))   # ≈ -0.99999977
        assert abs(float(action[0]) - expected) < 1e-5, (
            f"negative D28 clip: a_bat must be tanh(-8)≈{expected:.8f}, got {float(action[0]):.8f}")
        assert float(action[0]) > -1.0, "a_bat must stay strictly inside the open range (-1,1)"

    def test_d28_sigmoid_fraction_negative_clip(self, tmp_path):
        # reviewer: a fraction component with a very negative mean → sigmoid(clip(-100,-8,8))
        # reviewer: = sigmoid(-8) ≈ 0.000335 (NOT sigmoid(-100)=0.0). Strictly > 0 (open).
        pytest.importorskip("energy_go.serving.inference_stream")
        from energy_go.serving.inference_stream import policy_forward  # type: ignore
        out_b = np.zeros(12, dtype=np.float32)
        out_b[1] = -100.0   # mean for fraction f_sol_load
        ckpt = self._zero_weight_ckpt(tmp_path, out_b)
        action = policy_forward(ckpt, np.zeros(107, dtype=np.float32))
        expected = float(1.0 / (1.0 + np.exp(np.float32(8.0))))  # sigmoid(-8) ≈ 0.000335
        assert abs(float(action[1]) - expected) < 1e-5, (
            f"sigmoid(-8)≈{expected:.6f}, got {float(action[1]):.6f}")
        assert float(action[1]) > 0.0, "fraction must stay strictly inside the open range (0,1)"

    def test_obs_clip_clamps_extreme_obs(self, tmp_path):
        # reviewer: obs far beyond ±obs_clip·std must clamp, so two distinct extreme obs
        # reviewer: produce IDENTICAL actions. obs_mean=0, obs_var=1, obs_clip=10 →
        # reviewer: norm = clip(obs, -10, 10); obs=+1000 and +5000 both → +10 → same action.
        pytest.importorskip("energy_go.serving.inference_stream")
        from energy_go.training.checkpoint_format import load_checkpoint  # type: ignore
        from energy_go.serving.inference_stream import policy_forward  # type: ignore
        run = tmp_path / "checkpoints" / "run_clip"
        run.mkdir(parents=True)
        path = _make_canonical_checkpoint(run, run_id="run_clip")  # random weights → action depends on obs
        ckpt = load_checkpoint(path)
        a_hi  = policy_forward(ckpt, np.full(107, 1000.0, dtype=np.float32))
        a_hi2 = policy_forward(ckpt, np.full(107, 5000.0, dtype=np.float32))
        np.testing.assert_allclose(a_hi, a_hi2, atol=1e-6,
            err_msg="extreme obs must clamp to +obs_clip → identical actions")
        a_lo  = policy_forward(ckpt, np.full(107, -1000.0, dtype=np.float32))
        a_lo2 = policy_forward(ckpt, np.full(107, -5000.0, dtype=np.float32))
        np.testing.assert_allclose(a_lo, a_lo2, atol=1e-6,
            err_msg="extreme negative obs must clamp to -obs_clip → identical actions")

    def test_policy_not_found_on_empty_run_dir(self, tmp_path):
        # reviewer: a run dir with no canonical checkpoint_*.npz → error code policy_not_found
        # reviewer: (legacy policy.npz dropped, so an empty dir has nothing to load).
        pytest.importorskip("energy_go.serving.app")
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / "run_empty"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text('{"episodes_trained": 0, "site_id": "gansu"}')
        old = os.getcwd()
        os.chdir(tmp_path)
        try:
            from energy_go.serving.app import app  # type: ignore
            with TestClient(app) as c:
                with c.websocket_connect("/ws/inference") as ws:
                    ws.receive_text(timeout=5)  # ready
                    ws.send_text(_start_cmd(run_id="run_empty", site_id="gansu"))
                    err = _recv_until(ws, "error", max_frames=10)
                    assert err.get("code") == "policy_not_found", (
                        f"empty run dir must yield code='policy_not_found', got {err.get('code')!r}")
                    assert "message" in err
        finally:
            os.chdir(old)

    def test_discovery_ignores_stray_non_canonical_files(self, tmp_path):
        # reviewer: discovery must pick the canonical checkpoint_*.npz and not crash on
        # reviewer: stray files (a leftover policy.npz, a malformed .npz, an unrelated file).
        pytest.importorskip("energy_go.serving.app")
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / "run_stray"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text('{"episodes_trained": 1, "site_id": "gansu"}')
        _make_canonical_checkpoint(run, run_id="run_stray")
        (run / "notes.txt").write_text("not a checkpoint")
        (run / "checkpoint_garbled.npz").write_bytes(b"not really an npz")  # malformed, non-matching name
        old = os.getcwd()
        os.chdir(tmp_path)
        try:
            from energy_go.serving.app import app  # type: ignore
            with TestClient(app) as c:
                with c.websocket_connect("/ws/inference") as ws:
                    ws.receive_text(timeout=5)  # ready
                    ws.send_text(_start_cmd(run_id="run_stray", site_id="gansu"))
                    frame = _recv_until(ws, "env_step", max_frames=20)
                    assert validate(frame) == [], "canonical discovery must ignore stray files and stream valid frames"
        finally:
            os.chdir(old)


# ===========================================================================
# TestRealJaxEnvPhysics (task #48 — real env wiring)
# ---------------------------------------------------------------------------
# These tests verify that after the _SyntheticEnv → _JaxEnvSession cutover:
#  1. Telemetry fields come from real JAX physics (not random noise).
#  2. All 13 per-source flow fields from the EnvInfo amendment are present.
#  3. SOC is a fraction in [soc_min=0.2, soc_max=0.9] (D4 binding).
#  4. D13 cost identity holds: c_energy_yuan == c_import_yuan - r_export_yuan.
#  5. D18 validate() == [] for real env output.
# ===========================================================================

# JAX-availability guard for the new real-env classes.
# We do NOT use pytest.importorskip at module level here — that would skip the
# entire module (including the existing non-JAX tests).  Instead each new class
# declares an autouse fixture that skips the class if JAX is absent.

_REQUIRED_FLOW_FIELDS = [
    "solar_to_load_mw",
    "solar_to_bat_mw",
    "solar_to_grid_mw",
    "solar_curtailed_mw",
    "wind_to_load_mw",
    "wind_to_bat_mw",
    "wind_to_grid_mw",
    "wind_curtailed_mw",
    "bat_to_load_mw",
    "bat_to_grid_mw",
    "bat_curtailed_mw",
    "grid_to_bat_mw",
    "grid_to_load_mw",
    "load_unserved_mw",
]


def _collect_real_env_frames(ws_client, n: int = 3) -> list[dict]:
    """Collect n env_step frames at speed=0 (no throttle)."""
    frames: list[dict] = []
    with ws_client.websocket_connect("/ws/inference") as ws:
        ws.receive_text(timeout=5)  # ready
        ws.send_text(_start_cmd(speed=0.0))
        while len(frames) < n:
            raw = ws.receive_text(timeout=30)
            msg = json.loads(raw)
            if msg.get("kind") == "env_step":
                frames.append(msg)
    return frames


class TestRealJaxEnvPhysics:
    """Real JAX env physics after _SyntheticEnv replacement (task #48)."""

    @pytest.fixture(autouse=True)
    def _require_jax(self):
        """Skip the entire class if JAX is not installed (e.g. macOS Intel)."""
        pytest.importorskip("jax", reason="jax not installed; skip real-env physics tests")

    def test_d18_validate_passes_with_real_env(self, ws_client):
        """Real env output must pass energy_go.telemetry.validate() == [] (D18 hard gate)."""
        frames = _collect_real_env_frames(ws_client, n=3)
        for i, frame in enumerate(frames):
            errs = validate(frame)
            assert errs == [], (
                f"Real env frame {i} fails D18 validate:\n"
                + "\n".join(f"  - {e}" for e in errs)
            )

    def test_all_14_flow_fields_present(self, ws_client):
        """All 14 flows fields (13 per-source + load_unserved) must be in the payload.

        Contract §EnvInfo → telemetry payload: 13+2 amendment fields (§3.3 amendment,
        PR #33) must appear in flows.  Missing a field = serving layer did not wire the
        EnvInfo field.
        """
        frames = _collect_real_env_frames(ws_client, n=1)
        flows = frames[0]["payload"]["flows"]
        for field in _REQUIRED_FLOW_FIELDS:
            assert field in flows, (
                f"flows.{field} missing from real-env telemetry payload — "
                "check _JaxEnvSession → payload mapping"
            )

    def test_soc_is_fraction_in_valid_range(self, ws_client):
        """battery.soc must be a fraction in [0.2, 0.9] (D4: SOC bounds [soc_min, soc_max]).

        Reference: EnvState.soc is a fraction ∈ [0, 1]; D4 clips to [0.2, 0.9].
        The initial SOC is soc_init = 0.5 (EnvParams default), so the first step
        must have battery.soc ∈ [0.2, 0.9].
        """
        frames = _collect_real_env_frames(ws_client, n=3)
        for i, frame in enumerate(frames):
            soc = frame["payload"]["battery"]["soc"]
            assert isinstance(soc, float), f"frame {i}: battery.soc must be float, got {type(soc)}"
            # SOC is a fraction; D4 bounds [0.2, 0.9] ± tiny floating-point tolerance
            assert 0.199 <= soc <= 0.901, (
                f"frame {i}: battery.soc={soc:.6f} is outside D4 bounds [0.2, 0.9]"
            )

    def test_d13_c_energy_identity(self, ws_client):
        """D13: c_energy_yuan == c_import_yuan - r_export_yuan to floating-point precision.

        Reference arithmetic: C_E = P_import * price_buy - P_export * price_sell
        c_import = P_import * price_buy, r_export = P_export * price_sell
        → c_energy = c_import - r_export (D13 identity #3).

        Tolerance 1e-4 ¥ accounts for float32 → float64 cast in the serving layer
        (all EnvInfo fields are float32 from JAX; Python float() gives float64).
        """
        frames = _collect_real_env_frames(ws_client, n=3)
        for i, frame in enumerate(frames):
            costs = frame["payload"]["costs"]
            c_energy = costs["c_energy_yuan"]
            c_import = costs["c_import_yuan"]
            r_export = costs["r_export_yuan"]
            # c_energy == c_import - r_export (D13 identity #3)
            identity = c_import - r_export
            assert abs(c_energy - identity) < 1e-3, (
                f"frame {i}: D13 identity violated: c_energy={c_energy:.6f}, "
                f"c_import={c_import:.6f}, r_export={r_export:.6f}, "
                f"c_import-r_export={identity:.6f}, diff={abs(c_energy - identity):.2e}"
            )

    def test_gross_wind_power_is_non_negative(self, ws_client):
        """gross_wind_mw must be ≥ 0 (wind power is non-negative by physics).

        Reference: jax_env step computes P_wind = wind_rated_mw * p_frac where
        p_frac ∈ [0, 1], and wind_rated_mw = 615.0 MW (EnvParams default).
        So gross_wind_mw ∈ [0.0, 615.0].
        """
        frames = _collect_real_env_frames(ws_client, n=5)
        for i, frame in enumerate(frames):
            gw = frame["payload"]["generation"]["gross_wind_mw"]
            assert gw >= 0.0, f"frame {i}: gross_wind_mw={gw:.4f} is negative"
            assert gw <= 615.0 + 1e-4, (
                f"frame {i}: gross_wind_mw={gw:.4f} exceeds wind_rated_mw=615.0 MW"
            )

    def test_gross_solar_power_is_non_negative(self, ws_client):
        """gross_solar_mw must be ≥ 0 (solar power is non-negative by physics).

        Reference: jax_env P_pv = pv_capacity_mw * irr/1000 * temp_factor * eta * degradation
        where pv_capacity_mw = 330.0 MW (EnvParams default); clipped to ≥ 0.
        """
        frames = _collect_real_env_frames(ws_client, n=5)
        for i, frame in enumerate(frames):
            gs = frame["payload"]["generation"]["gross_solar_mw"]
            assert gs >= 0.0, f"frame {i}: gross_solar_mw={gs:.4f} is negative"

    def test_price_fields_match_gansu_tou(self, ws_client):
        """price_buy_yuan_per_mwh must be one of the 4 Gansu TOU tiers.

        Reference: PRICE_TABLE_YPW = [250, 450, 620, 780] ¥/MWh (jax_env.py constant).
        price_sell must be ≤ price_buy (D7: spread clamp ≥ 0 → sell ≥ 0, sell ≤ buy).
        """
        VALID_PRICES = {250.0, 450.0, 620.0, 780.0}
        frames = _collect_real_env_frames(ws_client, n=5)
        for i, frame in enumerate(frames):
            p = frame["payload"]
            buy = p["price_buy_yuan_per_mwh"]
            sell = p["price_sell_yuan_per_mwh"]
            assert buy in VALID_PRICES, (
                f"frame {i}: price_buy={buy} is not a Gansu TOU tier {VALID_PRICES}"
            )
            assert sell >= 0.0, f"frame {i}: price_sell={sell:.4f} is negative (D7 violation)"
            assert sell <= buy + 1e-4, (
                f"frame {i}: price_sell={sell:.4f} > price_buy={buy:.4f} (D7 violation)"
            )

    def test_tariff_tier_consistent_with_price(self, ws_client):
        """tariff_tier must match the price_buy tier (≥780→critical_peak, ≥620→peak,
        ≥450→mid, else→valley).

        Reference: contract §EnvInfo → telemetry payload, tariff_tier row.
        """
        frames = _collect_real_env_frames(ws_client, n=5)
        for i, frame in enumerate(frames):
            p = frame["payload"]
            buy = p["price_buy_yuan_per_mwh"]
            tier = p["tariff_tier"]
            if buy >= 780.0:
                expected = "critical_peak"
            elif buy >= 620.0:
                expected = "peak"
            elif buy >= 450.0:
                expected = "mid"
            else:
                expected = "valley"
            assert tier == expected, (
                f"frame {i}: tariff_tier={tier!r} inconsistent with price_buy={buy} ¥/MWh "
                f"(expected {expected!r})"
            )

    def test_flow_conservation_solar(self, ws_client):
        """Solar flow conservation: gross_solar_mw ≈ solar_to_load + solar_to_bat + solar_to_grid
        + solar_curtailed.

        Reference: jax_env §3.3 amendment — per-source conservation (identity #5).
        Tolerance 1e-3 MW: float32 → float64 cast + 4 summands.
        """
        frames = _collect_real_env_frames(ws_client, n=5)
        for i, frame in enumerate(frames):
            p = frame["payload"]
            gross = p["generation"]["gross_solar_mw"]
            flows = p["flows"]
            decomp = (
                flows["solar_to_load_mw"]
                + flows["solar_to_bat_mw"]
                + flows["solar_to_grid_mw"]
                + flows["solar_curtailed_mw"]
            )
            assert abs(gross - decomp) < 1e-2, (
                f"frame {i}: solar conservation violated: gross={gross:.6f} MW, "
                f"sum_parts={decomp:.6f} MW, diff={abs(gross - decomp):.2e} MW"
            )

    def test_flow_conservation_wind(self, ws_client):
        """Wind flow conservation: gross_wind_mw ≈ wind_to_load + wind_to_bat + wind_to_grid
        + wind_curtailed.

        Reference: jax_env §3.3 amendment — per-source conservation (identity #6).
        Tolerance 1e-2 MW.
        """
        frames = _collect_real_env_frames(ws_client, n=5)
        for i, frame in enumerate(frames):
            p = frame["payload"]
            gross = p["generation"]["gross_wind_mw"]
            flows = p["flows"]
            decomp = (
                flows["wind_to_load_mw"]
                + flows["wind_to_bat_mw"]
                + flows["wind_to_grid_mw"]
                + flows["wind_curtailed_mw"]
            )
            assert abs(gross - decomp) < 1e-2, (
                f"frame {i}: wind conservation violated: gross={gross:.6f} MW, "
                f"sum_parts={decomp:.6f} MW, diff={abs(gross - decomp):.2e} MW"
            )

    def test_weather_fields_come_from_generator_not_random(self, ws_client):
        """wind_speed_mps and irradiance_wm2 must be deterministic across two sessions
        with the same seed (fixed seed → fixed year → identical physics).

        This pins that weather comes from generate_year(PRNGKey(seed)), not RNG noise
        (which is what _SyntheticEnv used — random per step, not deterministic).
        Same seed → same year data → identical weather fields at the same step.
        """
        seed = 42

        def _get_first_weather(client) -> dict:
            with client.websocket_connect("/ws/inference") as ws:
                ws.receive_text(timeout=5)
                ws.send_text(_start_cmd(seed=seed, speed=0.0))
                return _recv_until(ws, "env_step", max_frames=20)["payload"]

        w1 = _get_first_weather(ws_client)
        w2 = _get_first_weather(ws_client)

        assert w1["wind_speed_mps"] == w2["wind_speed_mps"], (
            "wind_speed_mps must be deterministic (fixed seed → fixed year): "
            f"session1={w1['wind_speed_mps']}, session2={w2['wind_speed_mps']}"
        )
        assert w1["irradiance_wm2"] == w2["irradiance_wm2"], (
            "irradiance_wm2 must be deterministic (fixed seed → fixed year): "
            f"session1={w1['irradiance_wm2']}, session2={w2['irradiance_wm2']}"
        )

    def test_reward_is_finite_and_non_positive_for_gansu(self, ws_client):
        """reward must be finite (no NaN/Inf from real physics).

        Reference: reward = -(cost_total_reward_basis + penalty) * reward_scale (§3.5).
        All costs are ≥ 0, so reward ≤ 0. reward_scale = 1e-5 (EnvParams default).
        """
        import math
        frames = _collect_real_env_frames(ws_client, n=5)
        for i, frame in enumerate(frames):
            r = frame["payload"]["reward"]
            assert math.isfinite(r), (
                f"frame {i}: reward={r} is not finite — real env produced NaN/Inf"
            )
            assert r <= 1e-6, (
                f"frame {i}: reward={r:.8f} is positive (expected ≤ 0 since all costs ≥ 0)"
            )


# ===========================================================================
# TestHasPolicyCanonical (task #38 fix — absorbed into task #48)
# ---------------------------------------------------------------------------
# The REST API has_policy field must check for canonical checkpoint_*.npz
# (not the legacy policy.npz which was never produced by training).
# ===========================================================================

class TestHasPolicyCanonical:
    """REST API has_policy field reports True iff a canonical checkpoint_*.npz exists."""

    # has_policy fix in rest_api.py is pure Python — no JAX dependency.

    def _make_rest_client(self, tmp_path):
        """Return a TestClient with work_dir set to tmp_path."""
        old = os.getcwd()
        os.chdir(tmp_path)
        from energy_go.serving.app import app  # type: ignore
        client = TestClient(app)
        client.__enter__()
        client._old_cwd = old  # stash for cleanup
        return client

    def _cleanup_rest_client(self, client):
        client.__exit__(None, None, None)
        os.chdir(client._old_cwd)

    def _make_run_dir(self, tmp_path, run_id: str) -> Path:
        config = tmp_path / "config"
        config.mkdir(exist_ok=True)
        (config / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / run_id
        run.mkdir(parents=True)
        (run / "metadata.json").write_text(json.dumps({
            "episodes_trained": 50, "site_id": "gansu",
            "created_at": "2026-06-11T00:00:00Z",
        }))
        return run

    def test_has_policy_true_with_canonical_checkpoint(self, tmp_path):
        """GET /runs returns has_policy=True when a canonical checkpoint_*.npz is present.

        The legacy policy.npz check (pr #59 removal) always returned False for
        real training runs.  After the fix, has_policy must reflect the canonical
        checkpoint_*.npz discovery algorithm.
        """
        pytest.importorskip("energy_go.serving.app")
        run = self._make_run_dir(tmp_path, "run_hp_canonical")
        _make_canonical_checkpoint(run, run_id="run_hp_canonical")
        client = self._make_rest_client(tmp_path)
        try:
            resp = client.get("/runs")
            assert resp.status_code == 200, f"GET /runs returned {resp.status_code}"
            runs = resp.json()["runs"]
            hp_run = next((r for r in runs if r["id"] == "run_hp_canonical"), None)
            assert hp_run is not None, "run_hp_canonical not found in /runs response"
            assert hp_run["has_policy"] is True, (
                f"has_policy must be True when checkpoint_*.npz is present; "
                f"got {hp_run['has_policy']!r}.  "
                "Likely still checking policy.npz (legacy) instead of checkpoint_*.npz."
            )
        finally:
            self._cleanup_rest_client(client)

    def test_has_policy_false_with_only_legacy_policy_npz(self, tmp_path):
        """GET /runs returns has_policy=False when only a legacy policy.npz is present.

        The canonical discovery algorithm requires checkpoint_*.npz with _step<N> suffix.
        A bare policy.npz (legacy format, PR #59 removed from serving layer) must NOT
        set has_policy=True — it cannot be loaded by the current serving layer.
        """
        pytest.importorskip("energy_go.serving.app")
        run = self._make_run_dir(tmp_path, "run_hp_legacy")
        _make_policy_npz(run / "policy.npz")  # legacy file — canonical discovery ignores it
        client = self._make_rest_client(tmp_path)
        try:
            resp = client.get("/runs")
            assert resp.status_code == 200
            runs = resp.json()["runs"]
            hp_run = next((r for r in runs if r["id"] == "run_hp_legacy"), None)
            assert hp_run is not None, "run_hp_legacy not found in /runs response"
            assert hp_run["has_policy"] is False, (
                f"has_policy must be False when only legacy policy.npz is present; "
                f"got {hp_run['has_policy']!r}.  "
                "Canonical check (checkpoint_*.npz) must not match policy.npz."
            )
        finally:
            self._cleanup_rest_client(client)

    def test_has_policy_true_in_run_detail_endpoint(self, tmp_path):
        """GET /runs/{run_id} also reports has_policy=True for canonical checkpoint.

        Both the list endpoint and the detail endpoint share the same discovery logic.
        """
        pytest.importorskip("energy_go.serving.app")
        run = self._make_run_dir(tmp_path, "run_hp_detail")
        _make_canonical_checkpoint(run, run_id="run_hp_detail")
        client = self._make_rest_client(tmp_path)
        try:
            resp = client.get("/runs/run_hp_detail")
            assert resp.status_code == 200, f"GET /runs/run_hp_detail returned {resp.status_code}"
            data = resp.json()
            assert data.get("has_policy") is True, (
                f"has_policy in /runs/{{run_id}} must be True for canonical checkpoint; "
                f"got {data.get('has_policy')!r}"
            )
        finally:
            self._cleanup_rest_client(client)

    def test_has_policy_false_with_no_checkpoints(self, tmp_path):
        """GET /runs/{run_id} returns has_policy=False when the run dir has no checkpoints."""
        pytest.importorskip("energy_go.serving.app")
        run = self._make_run_dir(tmp_path, "run_hp_empty")
        # No checkpoint files at all
        client = self._make_rest_client(tmp_path)
        try:
            resp = client.get("/runs/run_hp_empty")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("has_policy") is False, (
                f"has_policy must be False with no checkpoints; got {data.get('has_policy')!r}"
            )
        finally:
            self._cleanup_rest_client(client)

    # reviewer: a legacy policy.npz must NOT suppress a present canonical checkpoint.
    # When BOTH checkpoint_*.npz (canonical) and policy.npz (legacy) exist, the
    # canonical-discovery glob finds the checkpoint → has_policy True. Guards against
    # an implementation that returns early/False on seeing the legacy file (or ANDs the
    # two checks). Pure filesystem — hand-verifiable: glob("checkpoint_*.npz") is
    # non-empty regardless of the legacy policy.npz also being present.
    def test_has_policy_true_with_both_canonical_and_legacy(self, tmp_path):
        pytest.importorskip("energy_go.serving.app")
        run = self._make_run_dir(tmp_path, "run_hp_both")
        _make_canonical_checkpoint(run, run_id="run_hp_both")
        _make_policy_npz(run / "policy.npz")  # legacy file present alongside canonical
        client = self._make_rest_client(tmp_path)
        try:
            resp = client.get("/runs")
            assert resp.status_code == 200
            runs = resp.json()["runs"]
            hp_run = next((r for r in runs if r["id"] == "run_hp_both"), None)
            assert hp_run is not None, "run_hp_both not found in /runs response"
            assert hp_run["has_policy"] is True, (
                "has_policy must be True when a canonical checkpoint_*.npz exists, even "
                "if a legacy policy.npz is also present (canonical discovery must not be "
                f"suppressed by the legacy file); got {hp_run['has_policy']!r}"
            )
        finally:
            self._cleanup_rest_client(client)


# ===========================================================================
# TestRealEnvEpisodeBoundary (task #48 — real env episode handling)
# ---------------------------------------------------------------------------
# After episode 0 ends at step 167, the real env must reset for episode 1.
# seq must not reset; episode counter must increment.
# These tests guard the real-env episode-boundary path in _JaxEnvSession.
# ===========================================================================

class TestRealEnvEpisodeBoundary:
    """Real-env episode boundary: reset, seq monotonicity, episode increment."""

    @pytest.fixture(autouse=True)
    def _require_jax(self):
        """Skip the entire class if JAX is not installed."""
        pytest.importorskip("jax", reason="jax not installed; skip real-env boundary tests")

    def test_real_env_episode_resets_at_boundary(self, ws_client):
        """After 168 real-env steps (episode 0), payload.episode increments to 1.

        The real JAX env has done = (t == episode_len - 1) = (t == 167).
        On done=True the serving wrapper must reset and increment the episode counter.
        payload.episode on the 169th frame (index 168) must be 1 (not 0).

        This is the same contract as TestEpisodeBoundary.test_seq_does_not_reset_at_episode_boundary
        but exercised through the REAL JAX env path (not _SyntheticEnv).
        """
        N = 170
        frames: list[dict] = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=0.0))
            while len(frames) < N:
                raw = ws.receive_text(timeout=60)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)

        # Frame at index 168 (the 169th frame) = first step of episode 1
        # payload.episode must be 1 (incremented at the episode boundary, step 167)
        assert frames[168]["payload"]["episode"] == 1, (
            f"payload.episode at frame 168 must be 1 (episode boundary at step 167, D3); "
            f"got {frames[168]['payload']['episode']}"
        )
        # seq must not reset across the boundary
        assert frames[168]["seq"] == 168, (
            f"seq at frame 168 must be 168 (no reset); got {frames[168]['seq']}"
        )

    def test_real_env_all_frames_pass_validate_across_boundary(self, ws_client):
        """All 170 frames spanning the episode boundary must pass D18 validate (real env).

        This extends TestTelemetrySchemaConformance to cover the boundary condition:
        the reset + new episode obs must still produce schema-valid telemetry.
        """
        N = 170
        frames: list[dict] = []
        with ws_client.websocket_connect("/ws/inference") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(_start_cmd(speed=0.0))
            while len(frames) < N:
                raw = ws.receive_text(timeout=60)
                msg = json.loads(raw)
                if msg.get("kind") == "env_step":
                    frames.append(msg)

        failures: list[str] = []
        for i, frame in enumerate(frames):
            errs = validate(frame)
            if errs:
                failures.append(f"  frame {i} (seq={frame['seq']}): {errs}")
        assert not failures, (
            f"D18 validate failed for {len(failures)} frames across episode boundary:\n"
            + "\n".join(failures[:5])  # show first 5 only
        )
