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


def _make_policy_npz(path: Path, obs_dim: int = 107, action_dim: int = 6):
    """Create a minimal policy.npz with random weights for a 2-hidden-layer MLP."""
    rng = np.random.default_rng(42)
    hidden = 64
    np.savez(
        path,
        w_0=rng.standard_normal((obs_dim, hidden)).astype(np.float32),
        b_0=rng.standard_normal(hidden).astype(np.float32),
        w_1=rng.standard_normal((hidden, hidden)).astype(np.float32),
        b_1=rng.standard_normal(hidden).astype(np.float32),
        w_2=rng.standard_normal((hidden, action_dim)).astype(np.float32),
        b_2=np.zeros(action_dim, dtype=np.float32),
    )


def _make_normalization_npz(path: Path, obs_dim: int = 107):
    """Create normalization.npz with obs_mean=0, obs_std=1 (identity normalization)."""
    np.savez(
        path,
        obs_mean=np.zeros(obs_dim, dtype=np.float32),
        obs_std=np.ones(obs_dim, dtype=np.float32),
    )


@pytest.fixture()
def work_dir(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "site_gansu.yaml").write_text(SITE_GANSU_YAML)

    run = tmp_path / "checkpoints" / "run_001"
    run.mkdir(parents=True)
    metadata = {
        "episodes_trained": 50,
        "latest_eval_reward": -0.45,
        "site_id": "gansu",
        "created_at": "2026-06-10T08:00:00Z",
    }
    (run / "metadata.json").write_text(json.dumps(metadata))
    _make_policy_npz(run / "policy.npz")
    _make_normalization_npz(run / "normalization.npz")

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
        """Run dir exists but policy.npz and policy.onnx absent → policy_not_found."""
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / "run_nopolicy"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text('{"episodes_trained": 1}')
        # No policy.npz / policy.onnx
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
    def test_normalization_loaded_from_npz(self, ws_client):
        """If normalization.npz exists, obs is normalized before policy call.

        Observable: the action the policy emits (via telemetry or status) must
        not blow up to ±infinity when normalization is applied (finite values
        confirm the normalization path was used).
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

    def test_identity_normalization_when_npz_absent(self, tmp_path):
        """normalization.npz absent → identity norm; stream must still work."""
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
        run = tmp_path / "checkpoints" / "run_nonorm"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text('{"episodes_trained": 1, "site_id": "gansu"}')
        _make_policy_npz(run / "policy.npz")
        # No normalization.npz
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            from energy_go.serving.app import app  # type: ignore
            with TestClient(app) as c:
                with c.websocket_connect("/ws/inference") as ws:
                    ws.receive_text(timeout=5)
                    ws.send_text(json.dumps({
                        "cmd": "start", "run_id": "run_nonorm",
                        "site_id": "gansu", "seed": 0, "speed": 0.0
                    }))
                    frame = _recv_until(ws, "env_step", max_frames=20)
                    assert frame["kind"] == "env_step"
        finally:
            os.chdir(old_cwd)


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
# TestPolicyForwardPass
# reviewer: policy forward-pass never verified — add: known policy.npz +
#   known obs → served action == reference forward (tanh hidden, identity
#   output, clip[-1,1]) within 1e-5.
# ===========================================================================

class TestPolicyForwardPass:
    """Verify the serving layer's MLP forward pass matches the reference.

    Reference (tanh hidden layers, identity output layer, clip to [-1, 1]):
        h_0    = tanh(obs  @ w_0 + b_0)
        h_1    = tanh(h_0  @ w_1 + b_1)
        out    = h_1  @ w_2 + b_2          (identity — no tanh on the last layer)
        action = clip(out, -1.0, 1.0)

    The serving module must expose `policy_forward(weights: dict, obs: np.ndarray)` as
    a public utility so tests can verify it independently of the WebSocket session.
    """

    @staticmethod
    def _reference_forward(weights: dict, obs: "np.ndarray") -> "np.ndarray":
        """Pure-NumPy reference: tanh hidden, identity output, clip[-1,1]."""
        n_layers = max(int(k[2:]) for k in weights if k.startswith("w_")) + 1
        h = obs.astype(np.float32)
        for i in range(n_layers):
            h = h @ weights[f"w_{i}"] + weights[f"b_{i}"]
            if i < n_layers - 1:
                h = np.tanh(h)          # tanh for every hidden layer
            # final layer: identity (no activation applied)
        return np.clip(h, -1.0, 1.0)

    def test_known_weights_match_reference_forward(self, tmp_path):
        """
        Known policy.npz + known obs → serving layer action == reference within 1e-5.

        Architecture: obs_dim=3, hidden=4, action_dim=2 (2-hidden-layer MLP)
            Layer 0 (hidden): h0 = tanh(obs @ w_0 + b_0)
            Layer 1 (hidden): h1 = tanh(h0  @ w_1 + b_1)
            Layer 2 (output): out = h1 @ w_2 + b_2  (identity activation)
            action = clip(out, -1.0, 1.0)

        Weights chosen so all intermediate values are well within float32 range
        and the reference result is easy to sanity-check at this small scale.
        """
        from energy_go.serving.inference_stream import policy_forward  # type: ignore

        # Small fixed weights — deterministic and hand-verifiable
        w_0 = np.array(
            [[ 0.5, -0.3,  0.1,  0.2],
             [ 0.4,  0.1, -0.2,  0.3],
             [-0.1,  0.2,  0.3, -0.4]], dtype=np.float32)   # shape (3, 4)
        b_0 = np.array([ 0.1, -0.2,  0.3, -0.1], dtype=np.float32)   # shape (4,)

        w_1 = np.array(
            [[ 0.2, -0.1,  0.3,  0.1],
             [-0.3,  0.2,  0.1, -0.2],
             [ 0.1,  0.4, -0.2,  0.3],
             [ 0.4, -0.3,  0.2,  0.1]], dtype=np.float32)  # shape (4, 4)
        b_1 = np.array([ 0.1, -0.1,  0.2, -0.2], dtype=np.float32)   # shape (4,)

        w_2 = np.array(
            [[ 0.5,  0.3],
             [-0.2,  0.4],
             [ 0.1, -0.3],
             [ 0.4,  0.2]], dtype=np.float32)               # shape (4, 2)
        b_2 = np.zeros(2, dtype=np.float32)                 # shape (2,)

        obs = np.array([0.5, -0.3, 0.8], dtype=np.float32)

        # Reference forward — must match exactly what the serving layer does:
        #   h0   = tanh(obs @ w_0 + b_0)
        #   h1   = tanh(h0  @ w_1 + b_1)
        #   out  =  h1  @ w_2 + b_2     (identity output — no tanh here)
        #   action = clip(out, -1.0, 1.0)
        weights = {"w_0": w_0, "b_0": b_0,
                   "w_1": w_1, "b_1": b_1,
                   "w_2": w_2, "b_2": b_2}
        expected = self._reference_forward(weights, obs)
        served   = policy_forward(weights, obs)

        np.testing.assert_allclose(
            served, expected, atol=1e-5,
            err_msg=(
                f"Serving layer action differs from reference.\n"
                f"Expected: {expected}\n"
                f"Got:      {served}\n"
                "Likely causes: wrong activation (should be tanh hidden, identity output), "
                "missing clip, or wrong layer order."
            ),
        )

    def test_output_is_clipped_to_unit_interval(self, tmp_path):
        """Large weights → pre-clip output >> 1; after clip must be exactly ±1.0.

        1-layer MLP (input→output directly, no hidden):
            out = obs @ w_0 + b_0      (identity activation on single layer)
            action = clip(out, -1.0, 1.0)

        obs=[1.0, 1.0], w_0=[[100, -200],[50, 75]], b_0=[0,0]:
            pre-clip = [1*100 + 1*50, 1*(-200) + 1*75] = [150, -125]
            clipped  = [1.0, -1.0]
        """
        from energy_go.serving.inference_stream import policy_forward  # type: ignore

        # 1-layer MLP: obs_dim=2, action_dim=2 (no hidden layer — w_0 is output layer)
        # pre-clip: obs @ w_0 + b_0 = [1*100+1*50, 1*(-200)+1*75] = [150, -125]
        # clipped:  [1.0, -1.0]
        w_0 = np.array([[100.0, -200.0],
                         [ 50.0,   75.0]], dtype=np.float32)  # shape (2, 2)
        b_0 = np.zeros(2, dtype=np.float32)
        obs = np.array([1.0, 1.0], dtype=np.float32)

        weights = {"w_0": w_0, "b_0": b_0}
        served = policy_forward(weights, obs)

        assert served[0] == pytest.approx(1.0,  abs=1e-6), (
            f"positive saturation must clip to 1.0, got {served[0]}"
        )
        assert served[1] == pytest.approx(-1.0, abs=1e-6), (
            f"negative saturation must clip to -1.0, got {served[1]}"
        )

    def test_single_hidden_layer_uses_tanh_not_relu(self, tmp_path):
        """Verify hidden activation is tanh (not ReLU or identity).

        Construct an obs + weights where tanh(x) ≠ relu(x) for x in the hidden layer.
        With x=-0.5: tanh(-0.5)≈-0.462, relu(-0.5)=0.0.
        If the serving layer uses relu, the output will differ from the tanh reference.
        """
        from energy_go.serving.inference_stream import policy_forward  # type: ignore

        # 2-layer MLP: obs_dim=1, hidden=1, action_dim=1
        # Layer 0 (hidden): h0 = tanh(obs @ w_0 + b_0) = tanh(1.0 * (-0.5) + 0) = tanh(-0.5)
        # Layer 1 (output): out = h0 @ w_1 + b_1 = tanh(-0.5) * 1.0 + 0 (identity output)
        # tanh(-0.5) ≈ -0.46211716  →  clipped to -0.46211716  (within [-1,1])
        w_0 = np.array([[-0.5]], dtype=np.float32)    # (1, 1)
        b_0 = np.array([0.0],  dtype=np.float32)      # (1,)
        w_1 = np.array([[ 1.0]], dtype=np.float32)    # (1, 1)
        b_1 = np.array([0.0],  dtype=np.float32)      # (1,)
        obs = np.array([1.0],  dtype=np.float32)

        # Reference: tanh(-0.5) ≈ -0.46211716
        # If relu were used: relu(-0.5) = 0.0, so output = 0.0 (wrong)
        weights  = {"w_0": w_0, "b_0": b_0, "w_1": w_1, "b_1": b_1}
        expected = self._reference_forward(weights, obs)   # ≈ -0.46211716
        served   = policy_forward(weights, obs)

        np.testing.assert_allclose(served, expected, atol=1e-5,
            err_msg=(
                f"Hidden activation is wrong (expected tanh≈{expected[0]:.6f}, "
                f"got {served[0]:.6f}). "
                "Possible cause: ReLU or identity activation used for hidden layer."
            ))
        # Sanity: result is negative (tanh(-0.5) < 0); relu(-0.5)=0 would fail this
        assert served[0] < 0, (
            f"tanh(-0.5) must be negative (≈-0.462); got {served[0]:.6f} — "
            "likely relu used instead of tanh"
        )
