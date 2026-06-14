# `src/energy_go/serving`

<!-- curated -->
## Purpose

This package is the HTTP/WebSocket boundary between the trained policy and the browser. It exposes a FastAPI application (assembled in `app.py`, listening on `ENERGY_GO_BACKEND_PORT`, default 8000) that wires together four concerns:

- **Live inference** (`inference_stream.py`): a WebSocket endpoint that accepts env-step observations and streams per-step actions from a loaded checkpoint, calling the §6 actor forward pass (see `contracts/serving/inference_stream.md`).
- **Training proxy** (`training_proxy.py`): REST routes and a WebSocket endpoint that relay start/pause/resume/stop commands to the harness and forward `train_metrics` / `eval_compare` telemetry frames to connected dashboard clients (see `contracts/serving/training_proxy.md`).
- **REST API** (`rest_api.py`): read-only endpoints for site configs, run history, eval results, and training curves (see `contracts/serving/rest_api.md`).
- **Wizard stage ① surface** (`geo_site_api.py`, `site_assembly.py`, `tariff_bands.py`): endpoints that support the site-configuration wizard — listing/fetching tariff regions and device models, starting weather-fetch jobs, assembling a canonical `site_config` dict from wizard form inputs (D37), and deriving `TariffBand` lists from the (12, 24) price table (see `contracts/serving/geo_site_api.md`, `contracts/serving/site_assemble.md`).

What does NOT live here: JAX env physics (that is the `env` package), the training loop (that is the `training` package), and all frontend UI code.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `__init__.py`

> energy_go.serving — FastAPI serving layer (implementation pending gate approval).

_No public symbols exported._

### `app.py`

> energy_go.serving.app — FastAPI application factory.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `not_found_handler` | `function` | — |
| `validation_error_handler` | `function` | — |
| `request_validation_error_handler` | `function` | Convert Pydantic request-body validation errors to HTTP 400 for geo routes. |

### `compare.py`

> energy_go.serving.compare — Compare-workbench endpoints (SC2).

| Symbol | Kind | Purpose |
|--------|------|---------|
| `EnsembleCache` | `class` | In-memory LRU cache for PolicyEnsemble objects (§5). |
| `PolicyRef` | `class` | — |
| `VariantRequest` | `class` | — |
| `SharedScenario` | `class` | — |
| `PlanRequest` | `class` | — |
| `FinanceParamField` | `class` | One tunable parameter in FinanceParamSet. |
| `FinanceParamSet` | `class` | Request body for POST /api/compare/recompute-finance (§2.3). |
| `RecomputeFinanceRequest` | `class` | — |
| `RunRequest` | `class` | — |
| `SizingSweepRequest` | `class` | — |
| `compare_plan` | `function` | Tier estimation — pure read; does NOT modify the PolicyEnsemble LRU cache. |
| `compare_recompute_finance` | `function` | Instant-tier synchronous finance recompute (§4). |
| `compare_run` | `function` | Submit async batch eval + finance run (202 Accepted). |
| `compare_run_status` | `function` | Poll batch run status (§7). |
| `compare_sizing_sweep` | `function` | Submit sizing sweep (202 Accepted). Stub — expands in task #18. |
| `compare_sizing_sweep_status` | `function` | Poll sizing sweep status (§9). |

### `geo_site_api.py`

> energy_go.serving.geo_site_api — Workstream A serving surface (wizard stage ①).

| Symbol | Kind | Purpose |
|--------|------|---------|
| `site_validate` | `function` | D32(i)/D18: pure passthrough of energy_go.env.config_validation.validate(). |
| `site_assemble` | `function` | D37: wizard form → canonical site_config dict + immediate validation. |
| `list_tariff_regions` | `function` | List all tariff region IDs with summary (price range, demand rate, provenance). |
| `get_tariff_region` | `function` | Full region detail: (12,24) price table + monthly TariffBand lists. |
| `get_tariff_bands` | `function` | Single-month TariffBand list (run-length encoded from the price table row). |
| `start_weather_fetch` | `function` | Start a weather fetch job; returns job_id immediately (non-blocking). |
| `get_weather_job` | `function` | Poll the status of a weather fetch job. |
| `weather_coverage` | `function` | Lightweight coverage check — no network call, no cache write. |
| `list_device_models` | `function` | Return active device models from config/device_models.yaml. |
| `get_device_model` | `function` | Single active device model detail. |
| `search_device_models` | `function` | Case-insensitive substring search against model_id. |

### `inference_stream.py`

> energy_go.serving.inference_stream — WebSocket live inference stream.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `policy_forward` | `function` | Run the §6 actor forward pass for a canonical CheckpointData. |
| `ws_inference` | `function` | — |

### `main.py`

> energy_go.serving.main — Application entry point re-export.

_No public symbols exported._

### `rest_api.py`

> energy_go.serving.rest_api — REST endpoint implementations.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `health` | `function` | Always 200.  Monitoring probes depend on this never erroring. |
| `list_sites` | `function` | — |
| `get_site` | `function` | — |
| `list_assets` | `function` | — |
| `list_runs` | `function` | — |
| `get_latest_run` | `function` | — |
| `get_run` | `function` | — |
| `get_eval` | `function` | — |
| `get_train_curve` | `function` | — |

### `site_assembly.py`

> energy_go.serving.site_assembly — wizard-form → site_config assembly.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `assemble_site_config` | `function` | Assemble a canonical site_config dict from wizard form inputs. |

### `tariff_bands.py`

> energy_go.serving.tariff_bands — server-side TariffBand derivation.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TariffBandDTO` | `class` | Serialisable TariffBand for the REST response. |
| `derive_bands` | `function` | Run-length encode a 24-element hourly price row into TariffBand list. |

### `training_proxy.py`

> energy_go.serving.training_proxy — Training control proxy (REST + WebSocket).

| Symbol | Kind | Purpose |
|--------|------|---------|
| `set_harness_stub` | `function` | Inject mock train_metrics frames for test isolation (no live harness). |
| `StartRequest` | `class` | — |
| `training_status` | `function` | — |
| `training_start` | `function` | — |
| `training_stop` | `function` | — |
| `training_pause` | `function` | — |
| `training_resume` | `function` | — |
| `ws_training_stream` | `function` | — |

<!-- generated:end -->
