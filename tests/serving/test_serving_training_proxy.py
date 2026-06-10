"""Tests for Energy GO Training Control Proxy.

Contract: contracts/serving/training_proxy.md
Module:   energy_go.serving.training_proxy (registered on app)

The tests use a mock harness (HarnessStub) so no live training process is required.
The stub emits pre-canned train_metrics frames; tests verify:
  - REST status/start/stop/pause/resume semantics
  - WS stream lifecycle and status frames
  - train_metrics frames conform to LOCKED telemetry schema (D18)
  - D18 producer obligation: validate(msg)==[] before every send

Units: costs ¥, rewards dimensionless, steps integers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

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
# Harness mock fixture data
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

# Canonical train_metrics frames for the mock harness to emit.
# Field names MUST match the LOCKED telemetry schema v1.0.0 (D18):
#   global_step (not "step"), ent_coef (not "entropy_coef"),
#   reward_scaled_mean (not "mean_reward"), reward_norm_mean (not "eval_reward"),
#   plus wall_seconds, env_steps_per_sec, cost_total_real_mean_yuan,
#   is_eval_checkpoint, checkpoint_id.
MOCK_TRAIN_FRAMES = [
    {
        "schema_version": "1.0.0",
        "kind": "train_metrics",
        "ts_utc": "2026-06-10T08:00:01Z",
        "run_id": "run_001",
        "seq": 0,
        "payload": {
            "global_step": 1000,
            "wall_seconds": 12.5,
            "env_steps_per_sec": 80.0,
            "actor_loss": 0.31,
            "critic_loss": 0.55,
            "ent_coef": 0.12,
            "reward_scaled_mean": -0.52,
            "reward_norm_mean": None,          # null = no eval checkpoint yet
            "cost_total_real_mean_yuan": 42500.0,
            "is_eval_checkpoint": False,
            "checkpoint_id": None,
        },
    },
    {
        "schema_version": "1.0.0",
        "kind": "train_metrics",
        "ts_utc": "2026-06-10T08:00:02Z",
        "run_id": "run_001",
        "seq": 1,
        "payload": {
            "global_step": 2000,
            "wall_seconds": 25.0,
            "env_steps_per_sec": 80.0,
            "actor_loss": 0.28,
            "critic_loss": 0.49,
            "ent_coef": 0.11,
            "reward_scaled_mean": -0.48,
            "reward_norm_mean": -0.49,         # eval result available at step 2000
            "cost_total_real_mean_yuan": 41000.0,
            "is_eval_checkpoint": True,
            "checkpoint_id": "run_001/epoch_20",
        },
    },
]


@pytest.fixture()
def work_dir(tmp_path):
    """Minimal working dir with a site YAML."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site_gansu.yaml").write_text(SITE_GANSU_YAML)
    return tmp_path


@pytest.fixture()
def client(work_dir):
    """TestClient with mock harness injected and CWD set to work_dir."""
    old_cwd = os.getcwd()
    os.chdir(work_dir)
    try:
        from energy_go.serving.app import app  # type: ignore
        from energy_go.serving.training_proxy import set_harness_stub  # type: ignore
        set_harness_stub(MOCK_TRAIN_FRAMES)
        with TestClient(app) as c:
            yield c
    finally:
        os.chdir(old_cwd)


def _recv_until(ws, kind: str, max_frames: int = 30):
    for _ in range(max_frames):
        raw = ws.receive_text()
        msg = json.loads(raw)
        if msg.get("kind") == kind:
            return msg
    raise AssertionError(f"No frame with kind={kind!r} in {max_frames} frames")


# ===========================================================================
# TestTrainingStatusEndpoint
# ===========================================================================

class TestTrainingStatusEndpoint:
    def test_status_returns_200(self, client):
        r = client.get("/training/status")
        assert r.status_code == 200

    def test_status_initial_state_is_idle(self, client):
        r = client.get("/training/status")
        assert r.json()["state"] == "idle"

    def test_status_has_run_id_null_when_idle(self, client):
        r = client.get("/training/status")
        assert r.json()["run_id"] is None

    def test_status_has_step_zero_when_idle(self, client):
        r = client.get("/training/status")
        assert r.json()["step"] == 0

    def test_status_has_episode_zero_when_idle(self, client):
        r = client.get("/training/status")
        assert r.json()["episode"] == 0

    def test_status_becomes_running_after_start(self, client):
        client.post("/training/start", json={
            "run_id": "run_new", "site_id": "gansu"
        })
        r = client.get("/training/status")
        assert r.json()["state"] == "running"

    def test_status_has_run_id_after_start(self, client):
        client.post("/training/start", json={
            "run_id": "run_new", "site_id": "gansu"
        })
        r = client.get("/training/status")
        assert r.json()["run_id"] == "run_new"


# ===========================================================================
# TestTrainingStartEndpoint
# ===========================================================================

class TestTrainingStartEndpoint:
    def test_start_returns_200(self, client):
        r = client.post("/training/start", json={
            "run_id": "run_new", "site_id": "gansu"
        })
        assert r.status_code == 200

    def test_start_response_has_state_running(self, client):
        r = client.post("/training/start", json={
            "run_id": "run_new", "site_id": "gansu"
        })
        assert r.json()["state"] == "running"

    def test_start_response_has_run_id(self, client):
        r = client.post("/training/start", json={
            "run_id": "run_new", "site_id": "gansu"
        })
        assert r.json()["run_id"] == "run_new"

    def test_start_with_hyperparams(self, client):
        r = client.post("/training/start", json={
            "run_id": "run_hyper", "site_id": "gansu",
            "hyperparams": {"lr": 1e-4, "gamma": 0.999}
        })
        assert r.status_code == 200

    def test_start_409_when_already_running(self, client):
        """Starting a run while one is active → 409."""
        client.post("/training/start", json={"run_id": "run_a", "site_id": "gansu"})
        r = client.post("/training/start", json={"run_id": "run_b", "site_id": "gansu"})
        assert r.status_code == 409

    def test_start_422_for_unknown_site(self, client):
        r = client.post("/training/start", json={
            "run_id": "run_badsite", "site_id": "no_such_site"
        })
        assert r.status_code == 422

    def test_start_422_for_missing_site_id(self, client):
        r = client.post("/training/start", json={"run_id": "run_nosite"})
        assert r.status_code == 422

    def test_start_uses_default_seed_zero(self, client):
        """No seed in body → server uses default 0 (no error)."""
        r = client.post("/training/start", json={
            "run_id": "run_noseed", "site_id": "gansu"
        })
        assert r.status_code == 200


# ===========================================================================
# TestTrainingStopEndpoint
# ===========================================================================

class TestTrainingStopEndpoint:
    def test_stop_returns_200_when_running(self, client):
        client.post("/training/start", json={"run_id": "run_x", "site_id": "gansu"})
        r = client.post("/training/stop")
        assert r.status_code == 200

    def test_stop_response_has_state_stopped(self, client):
        client.post("/training/start", json={"run_id": "run_x", "site_id": "gansu"})
        r = client.post("/training/stop")
        assert r.json()["state"] == "stopped"

    def test_stop_response_has_final_step(self, client):
        """final_step must be an integer."""
        client.post("/training/start", json={"run_id": "run_x", "site_id": "gansu"})
        r = client.post("/training/stop")
        assert isinstance(r.json().get("final_step"), int)

    def test_stop_409_when_not_running(self, client):
        """Stop when idle → 409."""
        r = client.post("/training/stop")
        assert r.status_code == 409

    def test_stop_updates_status_to_stopped(self, client):
        client.post("/training/start", json={"run_id": "run_x", "site_id": "gansu"})
        client.post("/training/stop")
        r = client.get("/training/status")
        assert r.json()["state"] == "stopped"


# ===========================================================================
# TestTrainingPauseResumeEndpoints
# ===========================================================================

class TestTrainingPauseResumeEndpoints:
    def test_pause_returns_200_when_running(self, client):
        client.post("/training/start", json={"run_id": "run_y", "site_id": "gansu"})
        r = client.post("/training/pause")
        assert r.status_code == 200

    def test_pause_response_has_state_paused(self, client):
        client.post("/training/start", json={"run_id": "run_y", "site_id": "gansu"})
        r = client.post("/training/pause")
        assert r.json()["state"] == "paused"

    def test_pause_409_when_idle(self, client):
        r = client.post("/training/pause")
        assert r.status_code == 409

    def test_pause_409_when_already_paused(self, client):
        client.post("/training/start", json={"run_id": "run_y", "site_id": "gansu"})
        client.post("/training/pause")
        r = client.post("/training/pause")
        assert r.status_code == 409

    def test_resume_returns_200_when_paused(self, client):
        client.post("/training/start", json={"run_id": "run_z", "site_id": "gansu"})
        client.post("/training/pause")
        r = client.post("/training/resume")
        assert r.status_code == 200

    def test_resume_response_has_state_running(self, client):
        client.post("/training/start", json={"run_id": "run_z", "site_id": "gansu"})
        client.post("/training/pause")
        r = client.post("/training/resume")
        assert r.json()["state"] == "running"

    def test_resume_409_when_already_running(self, client):
        client.post("/training/start", json={"run_id": "run_z", "site_id": "gansu"})
        r = client.post("/training/resume")
        assert r.status_code == 409

    def test_resume_409_when_idle(self, client):
        r = client.post("/training/resume")
        assert r.status_code == 409

    def test_state_machine_idle_start_pause_resume_stop(self, client):
        """Full lifecycle: idle → running → paused → running → stopped."""
        assert client.get("/training/status").json()["state"] == "idle"
        client.post("/training/start", json={"run_id": "run_lifecycle", "site_id": "gansu"})
        assert client.get("/training/status").json()["state"] == "running"
        client.post("/training/pause")
        assert client.get("/training/status").json()["state"] == "paused"
        client.post("/training/resume")
        assert client.get("/training/status").json()["state"] == "running"
        client.post("/training/stop")
        assert client.get("/training/status").json()["state"] == "stopped"


# ===========================================================================
# TestTrainingWSStream
# ===========================================================================

class TestTrainingWSStream:
    def test_ws_accepts_connection(self, client):
        with client.websocket_connect("/ws/training/stream") as ws:
            raw = ws.receive_text(timeout=5)
            msg = json.loads(raw)
            assert msg.get("kind") == "status"

    def test_initial_status_frame_has_state(self, client):
        with client.websocket_connect("/ws/training/stream") as ws:
            msg = json.loads(ws.receive_text(timeout=5))
            assert "state" in msg

    def test_initial_status_is_idle_before_start(self, client):
        with client.websocket_connect("/ws/training/stream") as ws:
            msg = json.loads(ws.receive_text(timeout=5))
            assert msg.get("state") == "idle"

    def test_stream_emits_train_metrics_after_start(self, client):
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)  # discard initial status
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            assert frame["kind"] == "train_metrics"

    def test_train_metrics_frame_passes_validate(self, client):
        """train_metrics frames must pass energy_go.telemetry.validate (D18 producer obligation)."""
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            errs = validate(frame)
            assert errs == [], (
                "train_metrics frame fails telemetry validation:\n"
                + "\n".join(f"  - {e}" for e in errs)
            )

    def test_train_metrics_has_global_step(self, client):
        """LOCKED schema field: global_step (not 'step')."""
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            assert "global_step" in frame["payload"], (
                "train_metrics payload must have 'global_step' (LOCKED schema; "
                "the field is NOT named 'step')"
            )

    def test_train_metrics_has_reward_scaled_mean(self, client):
        """LOCKED schema field: reward_scaled_mean (not 'mean_reward')."""
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            assert "reward_scaled_mean" in frame["payload"], (
                "train_metrics payload must have 'reward_scaled_mean' (LOCKED schema; "
                "not 'mean_reward')"
            )

    def test_train_metrics_first_global_step_value(self, client):
        """First train_metrics frame must have global_step=1000 (MOCK_TRAIN_FRAMES[0])."""
        # expected: global_step=1000 (hand-written in MOCK_TRAIN_FRAMES[0])
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            assert frame["payload"]["global_step"] == 1000, (
                f"Expected global_step=1000, got {frame['payload'].get('global_step')}"
            )

    def test_train_metrics_reward_scaled_mean_first_frame(self, client):
        """reward_scaled_mean = -0.52 for global_step=1000 (MOCK_TRAIN_FRAMES[0])."""
        # expected: -0.52 (hand-written in MOCK_TRAIN_FRAMES[0])
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            reward = frame["payload"]["reward_scaled_mean"]
            assert abs(reward - (-0.52)) < 1e-9, f"Expected -0.52, got {reward}"

    def test_train_metrics_reward_norm_mean_null_first_frame(self, client):
        """reward_norm_mean is null for global_step=1000 (no eval checkpoint yet; MOCK[0])."""
        # expected: null (is_eval_checkpoint=False in MOCK_TRAIN_FRAMES[0])
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            assert frame["payload"]["reward_norm_mean"] is None, (
                "reward_norm_mean must be null for global_step=1000 (no eval checkpoint)"
            )

    def test_stop_stream_closes_ws(self, client):
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            ws.send_text(json.dumps({"cmd": "stop_stream"}))
            with pytest.raises((WebSocketDisconnect, Exception)):
                ws.receive_text(timeout=2)

    def test_status_frame_emitted_on_start(self, client):
        """A running status frame must arrive on the WS when a run starts."""
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)  # initial idle status
            client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
            running_status = _recv_until(ws, "status", max_frames=20)
            assert running_status.get("state") == "running"

    def test_status_frame_emitted_on_pause(self, client):
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)  # initial running status
            client.post("/training/pause")
            pause_status = _recv_until(ws, "status", max_frames=30)
            assert pause_status.get("state") == "paused"

    def test_status_frame_emitted_on_stop(self, client):
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            client.post("/training/stop")
            stop_status = _recv_until(ws, "status", max_frames=30)
            assert stop_status.get("state") == "stopped"


# ===========================================================================
# TestTelemetrySchemaConformance (D18 producer obligation)
# ===========================================================================

class TestTelemetrySchemaConformance:
    def test_two_frames_pass_validate(self, client):
        """Both mock train_metrics frames must pass validate(msg)==[]."""
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        frames = []
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            while len(frames) < 2:
                raw = ws.receive_text(timeout=5)
                msg = json.loads(raw)
                if msg.get("kind") == "train_metrics":
                    frames.append(msg)
        for i, frame in enumerate(frames):
            errs = validate(frame)
            assert errs == [], (
                f"Frame {i} fails telemetry validation:\n"
                + "\n".join(f"  - {e}" for e in errs)
            )

    def test_frame_has_all_envelope_fields(self, client):
        """Envelope fields: schema_version, kind, ts_utc, run_id, seq, payload."""
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            frame = _recv_until(ws, "train_metrics", max_frames=30)
            for field in ("schema_version", "kind", "ts_utc", "run_id", "seq", "payload"):
                assert field in frame, f"Missing envelope field {field!r}"

    def test_seq_is_monotonic_across_two_frames(self, client):
        """seq must increment by 1 from frame 0 to frame 1."""
        # expected: seq 0 then 1 (matching MOCK_TRAIN_FRAMES seq fields)
        client.post("/training/start", json={"run_id": "run_001", "site_id": "gansu"})
        seqs = []
        with client.websocket_connect("/ws/training/stream") as ws:
            ws.receive_text(timeout=5)
            while len(seqs) < 2:
                raw = ws.receive_text(timeout=5)
                msg = json.loads(raw)
                if msg.get("kind") == "train_metrics":
                    seqs.append(msg["seq"])
        assert seqs[1] == seqs[0] + 1, (
            f"seq must be strictly monotonic: {seqs}"
        )
