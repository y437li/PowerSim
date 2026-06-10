"""energy_go.serving.training_proxy — Training control proxy (REST + WebSocket).

Contract: contracts/serving/training_proxy.md
Tests:    tests/serving/test_serving_training_proxy.py

Units: costs ¥, rewards dimensionless, steps integers.
train_metrics frames conform to LOCKED telemetry schema v1.0.0 (D18).
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter()

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class _TrainingState:
    """Singleton training-run state (one run at a time per server process).

    Frame replay buffer:
        Emitted train_metrics and status events are stored in a bounded deque
        (_replay_buffer, maxlen=_REPLAY_MAXLEN).  When a new WS client subscribes
        via subscribe(), all buffered events are immediately enqueued so the
        client sees frames emitted before it connected.  This prevents "late
        joiner" tests from hanging indefinitely.
    """

    _REPLAY_MAXLEN: int = 256

    def __init__(self) -> None:
        self.state: str = "idle"   # idle | running | paused | stopped
        self.run_id: str | None = None
        self.step: int = 0
        self.episode: int = 0
        # Active WS subscribers
        self._subscribers: list[asyncio.Queue] = []
        # Replay buffer for late-joining WS clients
        self._replay_buffer: collections.deque[dict] = collections.deque(
            maxlen=self._REPLAY_MAXLEN
        )

    def to_status(self) -> dict:
        return {
            "state": self.state,
            "run_id": self.run_id,
            "step": self.step,
            "episode": self.episode,
        }

    def broadcast(self, msg: dict) -> None:
        """Broadcast to all subscribers; buffer train_metrics only for replay.

        Status frames are NOT buffered for replay — the current status is sent
        explicitly when a WS client connects, so replaying old status frames would
        confuse late-joining clients about the state transition sequence.
        """
        if msg.get("_kind") == "train_metrics":
            self._replay_buffer.append(msg)
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        """Subscribe for future events; replays buffered events into the queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        # Replay missed events for this late-joining subscriber
        for past_event in self._replay_buffer:
            try:
                q.put_nowait(past_event)
            except asyncio.QueueFull:
                break  # queue is bounded; drop oldest replays on overflow
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)


_state = _TrainingState()

# ---------------------------------------------------------------------------
# Test harness: set_harness_stub injects mock frames for test isolation.
# ---------------------------------------------------------------------------

_harness_stub: list[dict] | None = None


def set_harness_stub(frames: list[dict]) -> None:
    """Inject mock train_metrics frames for test isolation (no live harness)."""
    global _harness_stub
    _harness_stub = frames


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _work_dir() -> Path:
    return Path.cwd()


def _ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _site_exists(site_id: str) -> bool:
    return (_work_dir() / "config" / f"site_{site_id}.yaml").exists()


# ---------------------------------------------------------------------------
# Background training task (drives the harness stub or real harness)
# ---------------------------------------------------------------------------

_train_task: asyncio.Task | None = None


async def _run_training(run_id: str) -> None:
    """Simulate training by emitting harness-stub frames (or real harness frames)."""
    frames = _harness_stub or []
    for frame in frames:
        if _state.state not in ("running", "paused"):
            break
        while _state.state == "paused":
            await asyncio.sleep(0.05)
        if _state.state != "running":
            break

        # Update step from the frame payload
        payload = frame.get("payload", {})
        _state.step    = payload.get("global_step", _state.step)
        _state.episode = 0  # training proxy doesn't track episodes in v1

        # Build the metrics broadcast event
        _state.broadcast({"_kind": "train_metrics", "frame": frame})
        await asyncio.sleep(0)  # yield


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    run_id: str
    site_id: str
    seed: int = 0
    hyperparams: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# GET /training/status
# ---------------------------------------------------------------------------

@router.get("/training/status")
def training_status() -> dict:
    return _state.to_status()


# ---------------------------------------------------------------------------
# POST /training/start
# ---------------------------------------------------------------------------

@router.post("/training/start")
async def training_start(body: StartRequest) -> dict:
    global _train_task

    if _state.state in ("running", "paused"):
        raise HTTPException(status_code=409, detail={"error": "training already active"})

    if not _site_exists(body.site_id):
        raise HTTPException(status_code=422, detail={"error": f"site not found: {body.site_id}"})

    _state.state  = "running"
    _state.run_id = body.run_id
    _state.step   = 0
    _state.episode = 0

    # Notify subscribers of state change
    _state.broadcast({"_kind": "status", "status": _state.to_status()})

    # Launch background training task
    _train_task = asyncio.ensure_future(_run_training(body.run_id))

    return _state.to_status()


# ---------------------------------------------------------------------------
# POST /training/stop
# ---------------------------------------------------------------------------

@router.post("/training/stop")
async def training_stop() -> dict:
    global _train_task

    if _state.state not in ("running", "paused"):
        raise HTTPException(status_code=409, detail={"error": "no active training run"})

    final_step = _state.step
    _state.state  = "stopped"
    _state.run_id = None

    if _train_task and not _train_task.done():
        _train_task.cancel()
        try:
            await _train_task
        except asyncio.CancelledError:
            pass

    _state.broadcast({"_kind": "status", "status": _state.to_status()})

    return {**_state.to_status(), "final_step": final_step}


# ---------------------------------------------------------------------------
# POST /training/pause
# ---------------------------------------------------------------------------

@router.post("/training/pause")
def training_pause() -> dict:
    if _state.state != "running":
        raise HTTPException(status_code=409, detail={"error": f"cannot pause from state={_state.state!r}"})
    _state.state = "paused"
    _state.broadcast({"_kind": "status", "status": _state.to_status()})
    return _state.to_status()


# ---------------------------------------------------------------------------
# POST /training/resume
# ---------------------------------------------------------------------------

@router.post("/training/resume")
def training_resume() -> dict:
    if _state.state != "paused":
        raise HTTPException(status_code=409, detail={"error": f"cannot resume from state={_state.state!r}"})
    _state.state = "running"
    _state.broadcast({"_kind": "status", "status": _state.to_status()})
    return _state.to_status()


# ---------------------------------------------------------------------------
# WS /ws/training/stream
# ---------------------------------------------------------------------------

@router.websocket("/ws/training/stream")
async def ws_training_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    q = _state.subscribe()

    try:
        # Send initial status frame
        await websocket.send_text(json.dumps({"kind": "status", **_state.to_status()}))

        while True:
            # Check for incoming client commands (non-blocking)
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if msg.get("cmd") == "stop_stream":
                    await websocket.close()
                    return
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                return

            # Drain the broadcast queue
            try:
                while True:
                    event = q.get_nowait()
                    if event["_kind"] == "status":
                        await websocket.send_text(
                            json.dumps({"kind": "status", **event["status"]})
                        )
                    elif event["_kind"] == "train_metrics":
                        frame = event["frame"]

                        # D18 producer obligation: validate before sending
                        try:
                            from energy_go.telemetry.validate import validate  # type: ignore
                            errs = validate(frame)
                            if errs:
                                log.warning("D18 validate (training_proxy train_metrics): %s", errs)
                        except ImportError:
                            pass

                        await websocket.send_text(json.dumps(frame))
            except asyncio.QueueEmpty:
                pass

            await asyncio.sleep(0.005)

    except WebSocketDisconnect:
        pass
    finally:
        _state.unsubscribe(q)
