# Inference sessions

An **inference session** is a live run of the trained policy against the simulator: each step, the policy chooses a dispatch action, the environment advances, and an `env_step` telemetry frame streams to the browser — driving both the [dashboard](dashboard.md) and the [3D site view](site_view_3d.md).

Session controls live in the **session control strip** at the top of the Site View (`/`).

## Starting a session

You don't press a "start" button — the session **auto-starts** as soon as the browser's websocket to the backend is ready. The control strip walks through these states:

| State | What the strip shows |
|---|---|
| **Connecting…** | The websocket is still opening. |
| **Starting session…** | The connection is ready and the start request is in flight. |
| **Running — step N ep M** | Live: a step/episode counter, a **Pause** button, and a **speed** selector. |
| **Paused — step N ep M** | A **Resume** button. |
| **Session stopped** | The session ended. |
| **Error** | An error message and a **Retry** button (which re-attempts the start). |

For the live data to flow, a policy must be loaded on the backend (a `serving`/`full` launch with a `--checkpoint`). With no policy loaded, `GET /health` reports `"policy_loaded": false` and the dashboard stays on "Waiting for live data…".

## Pause / Resume

Use **Pause** to freeze the run (the dashboard and scene hold their last frame) and **Resume** to continue. The step/episode counter shows where you are.

## Replay speed

While running, the **speed selector** controls how fast steps are emitted:

| Option | Effect |
|---|---|
| **Max speed** | As fast as the backend can step (uncapped). |
| **0.5×** | Half real-time. |
| **1× (real-time)** | One step per second — the default. |
| **2×** | Two steps per second. |
| **5×** | Five steps per second. |

Speed only changes the **emission rate** of telemetry, not the simulation itself — the trajectory is identical at any speed. (Streaming defaults to 1 Hz; "Max speed" removes the throttle — decision D24.)
