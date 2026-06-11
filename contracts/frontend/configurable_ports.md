# Contract: Configurable Dev Ports

- **Status:** DRAFT — gate pending (frontend-reviewer)
- **Spec:** REBUILD_SPEC.md §9 (install/launch)
- **Owner:** frontend-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend
- **Task:** #31
- **Amends:** `contracts/frontend/app_integration.md §1` (un-defers env-var injection for dev ports)
- **Coordinates:** `contracts/serving/launch_scripts.md` (same env vars passed by backend launch; see §6)

---

## Purpose

A second local project collides with the default dev ports (backend `:8000`, frontend `:5173`).
The proxy targets in `src/config/viteProxy.ts` are currently hardcoded; env-var injection was
explicitly deferred in `contracts/frontend/app_integration.md`. This contract un-defers the dev
half: both ports become configurable via two env vars at Vite startup time.

A temporary untracked `vite.demo.config.mts` (hardcoded `:8801`/`:5174`) is the current workaround;
it is deleted when this contract lands (see §5).

---

## 1. Environment variables

| Var | Default | Meaning |
|-----|---------|---------|
| `ENERGY_GO_BACKEND_PORT` | `8000` | Port the FastAPI/uvicorn backend listens on |
| `ENERGY_GO_FRONTEND_PORT` | `5173` | Port Vite dev server listens on |

Both are optional. When absent the system behaves exactly as before (no observable change for
any developer who does not have a port collision).

Values MUST be valid decimal integers in the range 1–65535. Behavior for out-of-range or
non-numeric values is undefined — operators are responsible for passing valid values.

---

## 2. `src/config/viteProxy.ts` — `buildViteProxy` API

### 2.1 New export: `buildViteProxy`

```typescript
/**
 * Build the Vite dev-server proxy config for a given backend port.
 *
 * @param backendPort - Explicit port. When omitted, reads ENERGY_GO_BACKEND_PORT
 *                      (env var present at call time); falls back to 8000.
 */
export function buildViteProxy(backendPort?: number): ProxyConfig { ... }
```

When `backendPort` is provided it takes precedence; `ENERGY_GO_BACKEND_PORT` is ignored.
When omitted, the function reads `process.env.ENERGY_GO_BACKEND_PORT` at **call time**
(not at module load) and parses it as a decimal integer, defaulting to `8000` when the
var is absent.

### 2.2 Backward-compatible module-level constant

`VITE_PROXY_CONFIG` remains exported and continues to be the value consumed by
`vite.config.ts`. It is now `buildViteProxy()` evaluated once at module-load time
(i.e. reads `ENERGY_GO_BACKEND_PORT` from the process environment at Vite startup):

```typescript
export const VITE_PROXY_CONFIG = buildViteProxy();
```

### 2.3 Proxy structure (unchanged)

For a given `port` the proxy entries are:

| Key | target | Options |
|-----|--------|---------|
| `/api` | `http://localhost:<port>` | `changeOrigin: true`; rewrite strips `/api` prefix |
| `/ws`  | `ws://localhost:<port>`  | `ws: true`; no path rewrite |

The `/api` rewrite rule is unchanged: `/^\/api(\/.*)?$/` → `$1 \|\| '/'`.

---

## 3. `vite.config.ts` — `server.port`

```typescript
server: {
  port: parseInt(process.env.ENERGY_GO_FRONTEND_PORT ?? "5173", 10),
  proxy: VITE_PROXY_CONFIG,
},
```

When `ENERGY_GO_FRONTEND_PORT` is absent the server starts on `5173` (unchanged default).

---

## 4. `playwright.config.ts` — frontend port

`playwright.config.ts` is updated to derive `baseURL` and `webServer.url` from
`ENERGY_GO_FRONTEND_PORT` so E2E tests target the correct port when a custom value is set:

```typescript
const frontendPort = parseInt(process.env.ENERGY_GO_FRONTEND_PORT ?? "5173", 10);
// ...
use: { baseURL: `http://localhost:${frontendPort}` },
// ...
webServer: {
  command: 'npm run dev',
  url: `http://localhost:${frontendPort}`,
  // ...
},
```

The existing test `tests/frontend/playwright_harness.test.ts` asserts
`baseURL === 'http://localhost:5173'` — this assertion continues to pass when
`ENERGY_GO_FRONTEND_PORT` is unset (env is clean in CI and local unit-test runs).

---

## 5. `vite.demo.config.mts` — deleted

The untracked workaround file `vite.demo.config.mts` is deleted in the same PR.
After this contract lands, the equivalent configuration is:

```bash
ENERGY_GO_BACKEND_PORT=8801 ENERGY_GO_FRONTEND_PORT=5174 npm run dev
```

---

## 6. Serving coordination

The same env var names are published to `serving-engineer` for the backend side:

- `ENERGY_GO_BACKEND_PORT` — `uvicorn`/FastAPI MUST bind to this port.
- The frontend proxy target and the backend bind port are both read from the same var,
  ensuring they stay in sync.

Serving-engineer should update `scripts/start_backend.sh` (or equivalent) to pass
`--port ${ENERGY_GO_BACKEND_PORT:-8000}` to uvicorn.

---

## 7. Acceptance criteria

### §T_CP (configurable-ports unit tests)

All tests live in `tests/frontend/configurable_ports.test.tsx`.

| ID | Description | Expected |
|----|-------------|----------|
| CP.1 | `buildViteProxy(8000)` → `/api` target | `"http://localhost:8000"` |
| CP.2 | `buildViteProxy(8000)` → `/ws` target  | `"ws://localhost:8000"` |
| CP.3 | `buildViteProxy(8801)` → `/api` target | `"http://localhost:8801"` |
| CP.4 | `buildViteProxy(8801)` → `/ws` target  | `"ws://localhost:8801"` |
| CP.5 | `buildViteProxy()` with env unset → `/api` target | `"http://localhost:8000"` |
| CP.6 | `buildViteProxy()` with `ENERGY_GO_BACKEND_PORT="9001"` → `/api` target | `"http://localhost:9001"` |
| CP.7 | `buildViteProxy()` with `ENERGY_GO_BACKEND_PORT="9001"` → `/ws` target  | `"ws://localhost:9001"` |
| CP.8 | `/api` entry has `changeOrigin: true` for any port | — |
| CP.9 | `/ws` entry has `ws: true` for any port | — |
| CP.10 | `/api` rewrite: `/api/sites` → `/sites` (unchanged with custom port) | `"/sites"` |
| CP.11 | `/api` rewrite: bare `/api` → `/` | `"/"` |
| CP.12 | `VITE_PROXY_CONFIG` (module const) → `/api` target defaults to `:8000` when env unset | `"http://localhost:8000"` |
