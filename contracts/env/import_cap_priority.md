# Test plan: reference F-IMPORT test hardening

**Area:** env  
**Branch:** `feat/env-import-cap-hardening`  
**Source of truth:** `contracts/env/jax_env_core.md` §5.3 STEP 7, §3.6 rule 9  
**Related PR:** #33 (ships the fix; these tests validate it on the reference side)

---

## Purpose

PR #33 fixes §3.6 row 9 (load-first grid import priority) in both `jax_env.py` and
`gansu_env.py`. It ships a 3-case `TestImportCapPriority` in `test_env_jax_env_core.py`.

This PR adds **11 reference-side tests** in a separate file
(`tests/env/test_env_import_cap_priority.py`) that are a superset of PR #33's cases,
with additional coverage:

- Asserts `grid_to_load_mw` directly (not just `load_unserved`)
- Asserts zero VOLL in TC-1 AND checks `cost_total_real_yuan` is below spurious-VOLL threshold
- Parametrised identity checks (`p_import = grid_to_bat + grid_to_load`, `p_import ≤ max`,
  `load_unserved ≥ 0`) across all 4 load scenarios

## Test file

`tests/env/test_env_import_cap_priority.py`  
Calls `gansu_env.env_step()` directly. No JAX dependency — pure Python/NumPy.

Tests are **RED on `main`** (reference buggy) and **GREEN after #33 merges**.

## What this PR does NOT do

- Does not change `gansu_env.py` (fix is in PR #33)
- Does not re-specify §3.6 row 9 behaviour (owned by `jax_env_core.md`)
- Does not touch `jax_env.py` or any JAX file

## How to run (after #33 merges)

```bash
uv run pytest tests/env/test_env_import_cap_priority.py -v
```

Expected: 11 passed.
