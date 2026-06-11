# The 3D site view

The **Site View** (`/` route) renders the Gansu plant as an interactive 3D scene next to the [live dashboard](dashboard.md). It's built with Three.js / React Three Fiber and is driven by the same live `env_step` telemetry, so the scene animates in step with the dashboard numbers.

## What you see

The scene composes the plant from its assets — wind turbines, PV arrays, a battery bank, and the grid connection (PCC substation). Asset models are resolved through the locked 3D asset registry (`assets/3d/registry.json`), so the scene always matches the configured site. The Gansu site totals it represents:

| Asset | Capacity |
|---|---|
| Wind | 615 MW |
| Solar (PV) | 330 MW |
| Battery | 294.5 MWh / 98.16 MW |
| Grid connection (PCC) | export limit 945 MW, import limit 400 MW |

(See [`docs/spec/section_01_overview.md`](../docs/spec/section_01_overview.md).)

## Reading the animation

The scene is a legibility aid, not a separate data source — its motion encodes the live telemetry:

- **Turbine rotation** tracks wind generation — faster spin = more wind power.
- **Battery state** reflects charge/discharge and state-of-charge.
- **Power-flow lines** between assets, the load, and the grid show where energy is moving each step (generation → load / battery / export, or grid import → load).

When no [inference session](sessions.md) is streaming, the scene renders the static plant; once a session runs, the flows and turbines come alive in sync with the dashboard.

## Interacting

It's a standard orbit camera — drag to rotate, scroll to zoom — so you can frame the turbines, the battery bank, or the grid tie as you like.

> **Heads-up.** A 3D-scene legibility pass on real GPU hardware (lighting, framing, model visibility) is still open work. If the scene looks dim or oddly framed on your machine, that's known and being tracked — the telemetry and dashboard remain the source of truth for actual values.
