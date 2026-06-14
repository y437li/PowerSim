# `src/energy_go/env`

<!-- curated -->
## Purpose

The `env` package is the **pure-JAX environment core** (REBUILD_SPEC §3, §7). It owns the
Markov Decision Process (§2) — physics, battery dynamics, power-balance, cost accounting,
and observation assembly — expressed as jittable, vmappable pure functions with no
data-dependent Python branching. Every agent's training and evaluation runs against this
package.

**Key entry points:**
- `jax_env.step` / `reset` — jitted environment step and episode reset (§3.6 constraint order).
- `jax_env.get_obs` — assemble the 107-dim observation vector (§2.1) without advancing time.
- `resolver.resolve_site` — load a `config/*.yaml` site description and device-model library
  into an `EnvParams` pytree ready to pass into `step`.
- `config_validation.validate` — two-tier site-config validator (D26); hard errors reject
  the config before any JAX compilation runs.
- `tariff_model_schema.load_tariff_schema` — parse the tariff region library (§3.4, D7/D8)
  and return typed `TariffRegion` objects used by `resolve_site`.

**Boundaries:** no training loop logic, no serving layer, no data-pipeline code lives here.
The `generators` package owns synthetic weather/load data generation (§4); `training` owns
the SAC loop and baselines. Physics constants (MW, MWh, ¥/MWh) are explicit in every
public interface — see CLAUDE.md engineering rules.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `config_validation.py`

> energy_go.env.config_validation — two-tier site-config validator.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `ValidationIssue` | `class` | — |
| `ValidationResult` | `class` | — |
| `ConfigValidationError` | `class` | Raised by resolve_site() when ValidationResult.errors is non-empty. |
| `validate` | `function` | Validate a parsed site config dict against physics and economics rules. |
| `validate_from_paths` | `function` | Convenience: load YAMLs from disk, then call validate(). |

### `jax_env.py`

> energy_go.env.jax_env — pure-JAX Energy GO environment core.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `EnvState` | `class` | Mutable env state — all fields are JAX scalar arrays. |
| `EnvParams` | `class` | Site/cost parameters — Gansu defaults.  Shared across vmapped envs. |
| `EnvInfo` | `class` | Per-step outputs — all float32 scalars. |
| `get_obs` | `function` | Build the 107-dim observation vector (§2.1) for *state* without stepping. |
| `step` | `function` | Full environment step — jittable and vmappable with in_axes=(0,0,None,None). |
| `reset` | `function` | Initialise a new episode starting at *episode_start*. |

### `resolver.py`

> energy_go.env.resolver — device-model schema resolver.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `DeviceModelError` | `class` | Raised when model_id is missing or a site override conflicts with a |
| `is_surfaceable` | `function` | Return True if a device model entry should appear in the live device feed. |
| `resolve_site` | `function` | Resolve a site YAML + device model schema to (EnvParams, obs_dim, action_dim). |
| `resolve_gansu` | `function` | Convenience: resolve the Gansu site (config/site_gansu.yaml). |
| `get_unit_counts` | `function` | Return resolved unit counts for discretely-instanced assets. |

### `tariff_model_schema.py`

> energy_go.env.tariff_model_schema — tariff region library loader and validator.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `SellClamp` | `class` | D7 sell-price clamp parameters. |
| `TariffRegion` | `class` | One region entry parsed from config/tariff_model_schema.yaml. |
| `load_tariff_schema` | `function` | Load config/tariff_model_schema.yaml; parse region entries into TariffRegion objects. |
| `validate_tariff_region` | `function` | Validate one raw region dict against the tariff schema rules (§5). |

<!-- generated:end -->
