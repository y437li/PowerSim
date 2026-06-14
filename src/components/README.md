# `src/components`

<!-- curated -->
## Purpose

Shared React UI primitives reused across routes and panels. Every component here is display-only: it receives props or reads from a Zustand store and renders; it performs no data-fetching, opens no WebSocket connections, and contains no JAX or backend logic.

Current components: `Card` (generic content wrapper with optional header), `ErrorBoundary` (class-based boundary that self-heals when its `resetKey` prop changes — contract `contracts/frontend/error_boundary_reset_key.md`), `FrameErrorBanner` (surfaces the frame-validation failure ring-buffer maintained by `telemetryStore`), `NumberDisplay` (renders a numeric value and unit label, handling null/NaN/Infinity gracefully), `SceneMountPoint` (DOM anchor for the Three.js canvas — used by `scene/SiteScene.tsx`), `SessionControlStrip` (pause/resume/speed controls for the live inference session), `TimeAxis` (simulation time and step counter widget), and `TouBadge` (TOU tier badge; wire values are in ¥/MWh, formatted via `utils/units.ts`).

Domain-specific panel components are co-located with their route: `components/live/` owns the live-dashboard panels and `components/training/` owns the training-panel components.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `Card.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `Card` | `function` | Shared card container — wraps a content block with optional header title. |

### `ErrorBoundary.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `ErrorBoundary` | `class` | Class-based error boundary. Catches render errors in children and shows a fallback. |

### `FrameErrorBanner.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `FrameErrorBanner` | `function` | — |

### `NumberDisplay.tsx`

> Displays a numeric value with unit; shows nullText for null/NaN/Infinity. */

| Symbol | Kind | Purpose |
|--------|------|---------|
| `NumberDisplay` | `function` | — |

### `SceneMountPoint.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `SceneMountPoint` | `function` | A plain div that the 3d-assets-engineer mounts Three.js/R3F into. |

### `SessionControlStrip.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `SessionControlStrip` | `function` | — |

### `TimeAxis.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TimeAxis` | `function` | Displays the current simulation time (UTC) and step counter. |

### `TouBadge.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TouBadge` | `function` | TOU-tier coloured badge. Tier label from TIER_LABELS; colour tokens from touColors.ts. |

<!-- generated:end -->
