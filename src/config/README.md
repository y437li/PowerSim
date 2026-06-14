# `src/config`

<!-- curated -->
## Purpose

Static frontend configuration and build-time data. Nothing here performs runtime fetching or maintains state.

`gansuSiteConfig.ts` exports `GANSU_SITE_CONFIG` (a `SiteSceneConfig` with the Gansu site nameplates: Wind 615 MW, Solar 330 MW, Battery 294.5 MWh / 98.16 MW, sourced from `docs/spec/section_01_overview.md`) and `ASSET_REGISTRY` (the static asset registry for the 3D scene — contract `contracts/frontend/app_integration.md §5`). `registryData.json` is the raw asset registry JSON consumed by `scene/registry.ts`. `viteProxy.ts` defines the Vite dev-server proxy rules for `/api` (strips the `/api` prefix before forwarding to the FastAPI backend) and `/ws` (WebSocket passthrough), per `contracts/frontend/app_integration.md §1` and `configurable_ports.md §2`.

Backend API contracts and serving-layer port assignments are defined in `contracts/serving/`; this folder only holds the build-time representation of those agreements.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `gansuSiteConfig.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `ASSET_REGISTRY` | `const` | Direct JSON import of the locked assets/3d/registry.json (v1.0.1, PR #24). |
| `GANSU_SITE_CONFIG` | `const` | — |

### `viteProxy.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `buildViteProxy` | `function` | Build the Vite dev-server proxy config for a given backend port. |
| `VITE_PROXY_CONFIG` | `const` | Module-level constant — evaluated once at Vite startup, reads |

<!-- generated:end -->
