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

## 1. Vite dev proxy (`vite.config.ts`)

Add a `server.proxy` block — active only during `vite dev`, inert in production builds.

| Proxy key | Target | Options |
|-----------|--------|---------|
| `/api` | `http://localhost:8000` | `changeOrigin: true`; rewrite: strip `/api` prefix (e.g. `/api/sites` → `/sites`) |
| `/ws` | `ws://localhost:8000` | `ws: true`; no path rewrite |

**Rewrite rule:** `/^\/api(\/.*)?$/` → `$1 || '/'`

This matches the backend's FastAPI routes which have no `/api` prefix.

**Acceptance criterion (§T1):** The exported config object has `server.proxy['/api'].target === 'http://localhost:8000'`
and `server.proxy['/ws'].ws === true`.

---

## 2. WebSocket client singleton (`src/clients/wsClientSingleton.ts`)

A new module that calls `createWsClient` **once** at module-init time, wiring store actions:

```typescript
// src/clients/wsClientSingleton.ts
import { createWsClient, type WsClient } from './wsClient';
import { useTelemetryStore } from '../stores/telemetryStore';
import { useTrainingStore } from '../stores/trainingStore';

export const wsClientSingleton: WsClient = createWsClient({
  url: '/ws',
  onEnvStep: (msg) => useTelemetryStore.getState().receiveEnvStep(msg),
  onTrainMetrics: (msg) => useTrainingStore.getState().receiveTrainMetrics(msg),
  onEvalCompare: (_msg) => { /* reserved — no eval_compare consumer in v1 */ },
  onStatusChange: (status) => useTelemetryStore.getState().setWsStatus(status),
});
```

Rules:
- The singleton is not connected at import time — `connect()` is called by `App`.
- The URL `/ws` is relative; the Vite proxy (§1) rewrites it to `ws://localhost:8000` in dev, and the production server must serve the WS endpoint at the same path.
- `evalCompare` handler is a no-op; this is intentional (no eval_compare consumer exists yet). It does NOT suppress the `wsClient` unknown-kind warning for genuinely unknown kinds.

**Shape:** `{ connect(): void; disconnect(): void }` — identical to `WsClient` from `wsClient.ts`.

**Acceptance criterion (§T2):** Exports `wsClientSingleton` with `typeof connect === 'function'` and `typeof disconnect === 'function'`.

---

## 3. App-level ws lifecycle (`src/App.tsx`)

`App` gains a `useEffect` that connects on mount and disconnects on unmount:

```typescript
useEffect(() => {
  wsClientSingleton.connect();
  return () => wsClientSingleton.disconnect();
}, []); // empty array — connect once on mount, disconnect on tree teardown
```

The effect **precedes** the router render in the component body (standard React order: effects register after render, but the empty-dep effect fires once after the first paint — before any data arrives).

`wsClient.ts` guarantees `connect()` is idempotent (no-op if already connecting/connected).

**Acceptance criteria (§T3, §T4):**
- §T3: Mounting `<App>` inside `MemoryRouter` calls `wsClientSingleton.connect()` exactly once.
- §T4: Unmounting `<App>` calls `wsClientSingleton.disconnect()` exactly once.

Both tests mock `wsClientSingleton` at the module level to avoid real WebSocket connections.

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

Representative static configuration for the Gansu site (REBUILD_SPEC §3):

| Field | Value | Source |
|-------|-------|--------|
| `site_id` | `"gansu"` | site name |
| `wind_capacity_mw` | `400` | §3 nameplate (D4) |
| `solar_capacity_mw` | `330` | §3 nameplate |
| `turbines` | ≥ 1 × `vestas-v150-4.2` | registry key |
| `pv_arrays` | ≥ 1 × `trina-vertex-n-670w` | registry key |
| `battery.assetId` | `"catl-lmp-300mwh"` | registry key |
| `battery.capacity_mwh` | `300` | §3 |
| `battery.max_charge_mw` | `60` | §3 |
| `battery.max_discharge_mw` | `60` | §3 |
| `grid.pcc.assetId` | valid key in registry | |
| `terrain.assetId` | valid key in registry | |

All `assetId` values **must** be valid keys in `ASSET_REGISTRY.assets`.

### `ASSET_REGISTRY: AssetRegistry`

Direct JSON import of `assets/3d/registry.json`, typed as `AssetRegistry`:

```typescript
import rawRegistry from '../../assets/3d/registry.json';
export const ASSET_REGISTRY = rawRegistry as unknown as AssetRegistry;
```

**Acceptance criteria (§T8, §T9):**
- §T8: `GANSU_SITE_CONFIG.site_id === 'gansu'`, `turbines.length >= 1`, and
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
| `vite.config.ts` | Add `server.proxy` block |
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
