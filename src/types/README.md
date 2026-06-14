# `src/types`

<!-- curated -->
## Purpose

TypeScript type definitions shared across the frontend. No runtime logic lives here — only type and interface declarations.

`telemetry.ts` contains the types generated from the LOCKED telemetry schema v1.0.0 (`contracts/shared/telemetry_schema.md`, D18, PR #6): `WsStatus`, `TelemetryKind`, `TelemetryEnvelope`, `EnvStepPayload`, `TrainMetricsPayload`, `EvalComparePayload`, `PerStepCosts`, `RunInfo`, `SiteConfig`, `TariffTier`, and related interfaces. The file header marks these as not to be hand-drifted — if the locked schema changes, these types change with it through the contract-first-dev process.

`stageConfig.ts` defines the Stage-① wizard types: `StageOneState`, `DeviceRow` (with `DeviceRowPhysics` for resolved per-unit physics per §4.1/T-FLEET-6), `ValidationResult`, `WeatherCoverage`, `TariffRegion`, and the discriminated-union fleet entry types (`WindEntry`, `PVEntry`, `BatteryEntry`, `GridEntry`, `FleetEntry`).
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `stageConfig.ts`

> src/types/stageConfig.ts

| Symbol | Kind | Purpose |
|--------|------|---------|
| `StageOneState` | `type` | — |
| `WeatherMode` | `type` | — |
| `LatLon` | `interface` | — |
| `DeviceRowPhysics` | `interface` | Per-unit physics stored in DeviceRow after resolution (§4.1, T-FLEET-6). |
| `DeviceRow` | `interface` | — |
| `ValidationIssue` | `interface` | — |
| `ValidationResult` | `interface` | — |
| `WeatherCoverage` | `interface` | — |
| `TariffRegion` | `interface` | Mirrors one entry from GET /api/tariff/regions (geo_site_api §3.2). |
| `WindEntry` | `type` | — |
| `PVEntry` | `type` | — |
| `BatteryEntry` | `type` | — |
| `GridEntry` | `type` | — |
| `FleetEntry` | `type` | — |

### `telemetry.ts`

> TypeScript types — generated from contracts/shared/telemetry_schema.md v1.0.0 (LOCKED, PR #6)

| Symbol | Kind | Purpose |
|--------|------|---------|
| `WsStatus` | `type` | — |
| `TelemetryKind` | `type` | — |
| `TelemetryEnvelope` | `interface` | — |
| `BatteryState` | `interface` | — |
| `GenerationBlock` | `interface` | — |
| `PowerFlows` | `interface` | — |
| `PccState` | `interface` | — |
| `TariffTier` | `type` | — |
| `PerStepCosts` | `interface` | — |
| `CumulativeCosts` | `interface` | — |
| `GasAsset` | `interface` | — |
| `ElectrolyzerAsset` | `interface` | — |
| `AssetsExt` | `interface` | — |
| `EnvStepPayload` | `interface` | — |
| `TrainMetricsPayload` | `interface` | — |
| `PolicyMetrics` | `interface` | — |
| `EvalComparePayload` | `interface` | — |
| `ServerStatusFrame` | `interface` | Server → client session status frame (no `payload` wrapper). |
| `ServerErrorFrame` | `interface` | Server → client error frame (no `payload` wrapper). |
| `RunInfo` | `interface` | REST API schema for GET /runs and GET /runs/latest — contracts/serving/rest_api.md §GET-runs. |
| `SiteConfig` | `interface` | — |

<!-- generated:end -->
