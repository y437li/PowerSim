# `src/energy_go/testing`

<!-- curated -->
## Purpose

This package provides shared physics invariant assertion helpers for use across the test suite (see `contracts/env/reference_implementation.md`). All helpers live in `invariants.py` and are framework-agnostic: they are duck-typed to accept both NumPy reference `StepResult` instances and JAX NamedTuples, so the same assertions cover both the Python reference implementation and the JAX core.

The helpers assert four categories of correctness:

- **Energy conservation** (`assert_energy_conserved`): per-source power balance for one env step.
- **Cost identities** (`assert_cost_identities`): all D13 cost-accounting algebraic identities for one step.
- **Physical bounds** (`assert_physical_bounds`): hard limits from D3, D4, D5, D7, D10, and D12.
- **SOC dynamics** (`assert_soc_dynamics`): consistency of the SOC update with §3.2; demand-charge booking timing per D10 (`assert_demand_charge_timing`).

Episode-level helpers (`run_episode`, `assert_episode_invariants`) drive a step function for N steps and run every invariant assertion on every step in sequence. `run_determinism_check` asserts that repeated calls with identical inputs always produce identical outputs.

What does NOT live here: production code of any kind. This package is test-only and is never imported at runtime.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `__init__.py`

> energy_go.testing — reusable physics invariant helpers.

_No public symbols exported._

### `invariants.py`

> Physics invariant helpers for Energy GO.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `assert_energy_conserved` | `function` | Assert per-source power balance for one env step. |
| `assert_cost_identities` | `function` | Assert all D13 cost-accounting algebraic identities for one step. |
| `assert_physical_bounds` | `function` | Assert all hard physical limits are respected. |
| `assert_demand_charge_timing` | `function` | Assert D10 demand-charge booking is correct for one step. |
| `assert_soc_dynamics` | `function` | Assert that the SOC update in *result* is consistent with §3.2 dynamics. |
| `run_determinism_check` | `function` | Assert that ``step_fn`` is deterministic: n_runs calls with identical inputs |
| `run_episode` | `function` | Run n_steps of ``step_fn`` from ``initial_state`` and return a list of results. |
| `assert_episode_invariants` | `function` | Run all invariant assertions on every step of an episode. |

<!-- generated:end -->
