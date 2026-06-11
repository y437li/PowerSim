# Contract: App Integration Wiring

- **Status:** DRAFT — gate pending (frontend-reviewer)
- **Spec:** REBUILD_SPEC.md §9 (install/launch), §3 (env physics, site config)
- **Owner:** frontend-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend
- **Task:** #22
- **Depends on contracts:**
  - `contracts/frontend/app_shell.md` (stores: `useTelemetryStore`, `useTrainingStore`, `SceneMountPoint`)
  - `contracts/frontend3d/site_scene.md` (`SiteScene`, `SiteSceneConfig`, `AssetRegistry`)
  - `contracts/frontend/live_dashboard.md` (`LiveDashboard` — LOCKED, PR #34)
  - `contracts/shared/telemetry_schema.md` v1.0.0 (LOCKED, PR #6)
  - `assets/3d/registry.json` v1.0.1 (LOCKED, PR #24)

---

## Purpose

Wire the four integration gaps that caused the demo to render empty:

1. **Vite dev proxy** — `/api` → REST backend, `/ws` → WebSocket backend (uvicorn :8000)
2. **App-level `wsClient` singleton** — created once, drives `telemetryStore` + `trainingStore`
3. **`SiteScene` mounted in `SiteView`** — via `SceneMountPoint.onReady` callback
4. **`LiveDashboard` rendered within `SiteView`** — already merged (PR #34); missing from DOM

No new stores, no new routes, no new nav links. This contract wires existing pieces together.

---

## 1. Vite dev proxy (`src/config/viteProxy.ts` + `vite.config.ts`)

The proxy config lives in a new plain-TS module `src/config/viteProxy.ts` that exports
`VITE_PROXY_CONFIG`. This module is imported by `vite.config.ts` and directly by tests,
avoiding esbuild environment issues when vite.config.ts is imported in jsdom.

`vite.config.ts` adds `server: { proxy: VITE_PROXY_CONFIG }` — active only during `vite dev`,
inert in production builds.

| Proxy key | Target | Options |
|-----------|--------|---------|
| `/api` | `http://localhost:8000` | `changeOrigin: true`; rewrite: strip `/api` prefix (e.g. `/api/sites` → `/sites`) |
| `/ws` | `ws://localhost:8000` | `ws: true`; no path rewrite |

**Rewrite rule:** `/^\/api(\/.*)?$/` → `$1 || '/'`

This matches the backend's FastAPI routes which have no `/api` prefix.

**Acceptance criterion (§T1):** `VITE_PROXY_CONFIG['/api'].target === 'http://localhost:8000'` and
`VITE_PROXY_CONFIG['/api'].changeOrigin === true` and `VITE_PROXY_CONFIG['/ws'].ws === true`.

---

## 2. WebSocket client singletons (`src/clients/wsClientSingleton.ts`)

The serving layer exposes **two** WebSocket endpoints with different message kinds:

| Endpoint | kinds served | Source contract |
|----------|-------------|-----------------|
| `WS /ws/inference` | `env_step`, `status` | `contracts/serving/inference_stream.md:24` |
| `WS /ws/training/stream` | `train_metrics` | `contracts/serving/training_proxy.md:98` |

`wsClientSingleton.ts` creates **two** `createWsClient` instances, one per endpoint.

### Exports

```typescript
// src/clients/wsClientSingleton.ts
import { createWsClient, type WsClient } from './wsClient';
import type { TelemetryEnvelope, WsStatus } from '../types/telemetry';
import { useTelemetryStore } from '../stores/telemetryStore';
import { useTrainingStore } from '../stores/trainingStore';

// URL constants — exported for direct testing (§T_url)
export const TELEMETRY_WS_URL = '/ws/inference';
export const TRAINING_WS_URL = '/ws/training/stream';

// Handler functions — exported for direct testing (§T_wire)
export function handleEnvStep(msg: TelemetryEnvelope): void {
  useTelemetryStore.getState().receiveEnvStep(msg);
}
export function handleTrainMetrics(msg: TelemetryEnvelope): void {
  useTrainingStore.getState().receiveTrainMetrics(msg);
}
export function handleStatusChange(status: WsStatus): void {
  useTelemetryStore.getState().setWsStatus(status);
}

// Clients — NOT connected at import time; connected by App.useEffect (§3)
export const telemetryWsClient: WsClient = createWsClient({
  url: TELEMETRY_WS_URL,
  onEnvStep: handleEnvStep,
  onTrainMetrics: () => {},      // /ws/inference never sends train_metrics
  onEvalCompare: () => {},       // eval_compare: no v1 consumer
  onStatusChange: handleStatusChange,
});

export const trainingWsClient: WsClient = createWsClient({
  url: TRAINING_WS_URL,
  onEnvStep: () => {},           // /ws/training/stream never sends env_step
  onTrainMetrics: handleTrainMetrics,
  onEvalCompare: () => {},
  onStatusChange: () => {},      // training WS status not exposed in UI (TrainingPanel
                                 // reads wsStatus from telemetryStore — confirmed correct)
});
```

Rules:
- Neither client connects at import time — `connect()` is called by `App`.
- URLs are relative; Vite proxy (§1) rewrites `/ws/*` during dev.
- `handleStatusChange` routes to `telemetryStore.setWsStatus`. `trainingWsClient`'s
  `onStatusChange` is a no-op — both panels read `wsStatus` from `telemetryStore`.
- `evalCompare` handlers are no-ops (no v1 consumer); this does NOT suppress `wsClient`
  unknown-kind warnings for genuinely unknown kinds.

**Acceptance criteria (§T2):** `telemetryWsClient` and `trainingWsClient` each have
`typeof connect === 'function'` and `typeof disconnect === 'function'` (real module, via
`vi.importActual`).

**Acceptance criteria (§T_url):** `TELEMETRY_WS_URL === '/ws/inference'` and
`TRAINING_WS_URL === '/ws/training/stream'`.

**Acceptance criteria (§T_wire):** Calling `handleEnvStep(envStepEnvelope)` routes to
`telemetryStore.receiveEnvStep`; calling `handleTrainMetrics(trainMetricsEnvelope)` routes to
`trainingStore.receiveTrainMetrics`; calling `handleStatusChange('connected')` routes to
`telemetryStore.setWsStatus`.

---

## 3. App-level ws lifecycle (`src/App.tsx`)

`App` gains a `useEffect` that connects **both** clients on mount and disconnects both on unmount:

```typescript
useEffect(() => {
  telemetryWsClient.connect();
  trainingWsClient.connect();
  return () => {
    telemetryWsClient.disconnect();
    trainingWsClient.disconnect();
  };
}, []); // empty array — connect once on mount, disconnect on tree teardown
```

`wsClient.ts` guarantees `connect()` is idempotent (no-op if already connecting/connected), so
React 18 StrictMode's double-invocation (mount→unmount→mount) is safe: the synthetic unmount
disconnects cleanly, and the second mount re-connects without side effects.

**Acceptance criteria (§T3, §T4):**
- §T3: Mounting `<App>` inside `MemoryRouter` calls `telemetryWsClient.connect()` exactly once
  **and** `trainingWsClient.connect()` exactly once.
- §T4: Unmounting `<App>` calls `telemetryWsClient.disconnect()` exactly once **and**
  `trainingWsClient.disconnect()` exactly once.

Both tests mock the `wsClientSingleton` module at module level to avoid real WebSocket connections.

---

## 4. SiteScene mount in SiteView (`src/routes/SiteView.tsx`)

Updated `SiteView`:

```typescript
import { useState } from 'react';
import { SceneMountPoint } from '../components/SceneMountPoint';
import { SiteScene } from '../scene/SiteScene';
import { LiveDashboard } from './LiveDashboard';
import { GANSU_SITE_CONFIG, ASSET_REGISTRY } from '../config/gansuSiteConfig';

export default function SiteView() {
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);

  return (
    <div data-testid="site-view" className="route-site-view">
      <SceneMountPoint onReady={setContainerEl} />
      <SiteScene
        config={GANSU_SITE_CONFIG}
        registry={ASSET_REGISTRY}
        containerEl={containerEl}
      />
      <LiveDashboard />
    </div>
  );
}
```

`SiteScene` handles `containerEl === null` gracefully per its own contract (no-op until non-null).

**Acceptance criteria (§T5, §T6, §T7):**
- §T5: Rendering `<SiteView>` yields `data-testid="scene-mount-point"` in the DOM.
- §T6: Rendering `<SiteView>` yields `data-testid="live-dashboard"` in the DOM.
- §T7: After mount, `SiteScene` receives a non-null `containerEl` (the `HTMLDivElement` provided by `SceneMountPoint.onReady`). Verified via a mock `SiteScene` that exposes its `containerEl` prop.

SiteScene is mocked in all SiteView unit tests to prevent R3F/Three.js in jsdom.

---

## 5. Static Gansu site config (`src/config/gansuSiteConfig.ts`)

Exports two named constants:

### `GANSU_SITE_CONFIG: SiteSceneConfig`

Representative static configuration for the Gansu site. **Nameplates from
`docs/spec/section_01_overview.md:12`** (authoritative source — NOT D4 which is SOC bounds,
NOT D12 which is import limit):

| Field | Value | Source |
|-------|-------|--------|
| `site_id` | `"gansu"` | site name |
| `wind_capacity_mw` | **`615`** | §1 overview (615 MW nameplate; 400 = import limit D12) |
| `solar_capacity_mw` | **`330`** | §1 overview |
| `turbines` | ≥ 1 × `vestas-v150-4.2` | registry key |
| `pv_arrays` | ≥ 1 × `trina-vertex-n-670w` | registry key |
| `battery.assetId` | `"catl-lmp-300mwh"` | registry key |
| `battery.capacity_mwh` | **`294.5`** | §1 overview (294.5 MWh) |
| `battery.max_charge_mw` | **`98.16`** | §1 overview (98.16 MW) |
| `battery.max_discharge_mw` | **`98.16`** | §1 overview (98.16 MW) |
| `grid.pcc.assetId` | valid key in registry | |
| `terrain.assetId` | valid key in registry | |

All `assetId` values **must** be valid keys in `ASSET_REGISTRY.assets`.

These nameplates feed `SiteScene`'s flow-line normalization (`site_max_mw`); incorrect values
would mis-scale every power-flow animation.

### `ASSET_REGISTRY: AssetRegistry`

Direct JSON import of `assets/3d/registry.json`, typed as `AssetRegistry`:

```typescript
import rawRegistry from '../../assets/3d/registry.json';
export const ASSET_REGISTRY = rawRegistry as unknown as AssetRegistry;
```

**Acceptance criteria (§T8, §T9):**
- §T8: `GANSU_SITE_CONFIG.site_id === 'gansu'`, `turbines.length >= 1`,
  `wind_capacity_mw === 615`, `solar_capacity_mw === 330`,
  `battery.capacity_mwh === 294.5`, `battery.max_charge_mw === 98.16`,
  `battery.max_discharge_mw === 98.16`, and
  `ASSET_REGISTRY.assets[GANSU_SITE_CONFIG.battery.assetId]` is defined.
- §T9: `ASSET_REGISTRY` deep-equals the raw import of `assets/3d/registry.json`.

---

## 6. Nav link

`LiveDashboard` is a panel **within** `SiteView` at `/`. It is NOT a separate route. The existing
"Site View" nav link at `/` already covers it. No new `<Route>` or `<NavLink>` is added.

---

## Files changed

| File | Change |
|------|--------|
| `src/config/viteProxy.ts` | **New** — plain-TS proxy config constant (no esbuild dep) |
| `vite.config.ts` | Add `server: { proxy: VITE_PROXY_CONFIG }` |
| `src/clients/wsClientSingleton.ts` | **New** — singleton WsClient wired to stores |
| `src/App.tsx` | Add `useEffect` for ws connect/disconnect lifecycle |
| `src/routes/SiteView.tsx` | Add `SceneMountPoint.onReady` + `SiteScene` + `LiveDashboard` |
| `src/config/gansuSiteConfig.ts` | **New** — static Gansu `SiteSceneConfig` + `ASSET_REGISTRY` |

---

## Out of scope

- Eval compare consumer (`eval_compare` kind is a no-op in v1 — no panel exists yet)
- YAML-driven site config loading (future: REST `GET /api/sites/gansu` feeds SiteSceneConfig)
- Production WebSocket URL configuration (env-var injection; deferred)
- Task #16 (NDJSON relocation) — separate contract amendment
- Task #14 (D18 real-env policy) — separate contract
