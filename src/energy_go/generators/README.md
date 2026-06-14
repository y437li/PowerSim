# `src/energy_go/generators`

<!-- curated -->
## Purpose

This package provides the pure-JAX synthetic weather and load generator specified in REBUILD_SPEC §4. Its single public entry point, `generate_year(key)` in `synthetic.py`, produces one `SyntheticYear` — an 8760 × 4 float32 array with columns `[wind_mps, irr_wm2, temp_c, load_mw]` — following the §4.1 weather model and the §4.2 load model (D19: AR(1)-on-temperature). A fixed JAX PRNG key always produces an identical output, satisfying the determinism requirement of the JAX core.

The `data` package's `pipeline.py` calls `generate_year` when its mode switch is set to `"synthetic"`. No other caller should need to invoke this package directly.

What does NOT live here: real-weather fetching, caching, and transformation (those are in the `data` package, REBUILD_SPEC §12), and the JAX env step function itself (that is the `env` package).
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `synthetic.py`

> energy_go.generators.synthetic — pure-JAX synthetic year generator.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `generate_year` | `function` | Generate one synthetic year (8760 × 4) float32 following §4.1, §4.2 (D19). |

<!-- generated:end -->
