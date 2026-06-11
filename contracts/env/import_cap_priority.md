# Contract: import_cap_priority — Reference Impl F-IMPORT Fix

- **Area:** env
- **Branch:** `fix/env-import-cap-priority`
- **Spec sections:** §3.6 row 9 (grid import — load served first, then battery, then load shed)
- **Decisions:** D11 (parity ground-truth), D12 (import limit 400 MW)
- **Status:** DRAFT — awaiting backend-reviewer APPROVE before implementation
- **Review record:** `contracts/reviews/import_cap_priority.md`
- **Related PR:** #33 (JAX fix already landed), task #24

---

## 1. Scope

This contract specifies a **targeted bug fix** to `src/reference/gansu_env.py` STEP 8 (grid
import priority), exactly mirroring the load-first fix already applied to `jax_env.py` in
PR #33.

No other files are touched. This is NOT a feature extension.

---

## 2. Bug description (F-IMPORT)

### What is wrong

`gansu_env.py` STEP 8 (L445–461) contains a two-branch `if` that applies **battery-first**
priority when `p_import_required > grid_max_import_mw`:

```python
# WRONG — battery-first
if params.grid_max_import_mw < p_g2b:
    p_g2b_actual = params.grid_max_import_mw   # battery gets all headroom
    grid_to_load = 0.0                          # load gets nothing
else:
    p_g2b_actual = p_g2b                        # battery fully honoured
    grid_to_load = min(grid_to_load_required, params.grid_max_import_mw - p_g2b)
```

### What §3.6 row 9 requires

> "Load served first, then battery charging reduced, then load shed."

Load has **first claim** on the import budget. Battery charging is reduced to whatever
headroom remains after load is served.

### Concrete impact

Scenario: `load_deficit = 350 MW`, `p_g2b = 98.16 MW`, `grid_max_import_mw = 400 MW`:

| | old (battery-first) | correct (load-first) |
|---|---|---|
| `grid_to_load` | 301.84 MW | 350 MW |
| `p_g2b_actual` | 98.16 MW | 50 MW |
| `load_unserved` | **48.16 MW** | **0 MW** |
| `c_voll_yuan` | **963,200 ¥ (spurious)** | **0 ¥** |
| `p_import` | 400 MW | 400 MW |

VOLL = 20,000 ¥/MWh is the most expensive cost term; spurious VOLL corrupts reward and cost
metrics whenever `load_deficit < max_import < load_deficit + p_grid_to_bat`.

### Why parity couldn't catch it

The 29-case `TestJaxReferenceParity` suite (PR #33) uses scenarios that do not include
grid-charging competing with load under the import cap — both implementations agreed on the
wrong result, so parity passed. This PR adds a parity-discriminating test that specifically
triggers the scenario.

---

## 3. Fix specification

Replace the two-branch battery-priority logic with single-path load-first logic:

```python
# Correct — load-first (§3.6 row 9)
grid_to_load  = min(grid_to_load_required, params.grid_max_import_mw)
p_g2b_actual  = max(0.0, min(p_g2b, params.grid_max_import_mw - grid_to_load))
load_unserved = max(0.0, grid_to_load_required - grid_to_load)
p_import      = grid_to_load + p_g2b_actual
```

This handles all three cases with one code path:
- `load_deficit ≤ max_import ≤ load_deficit + p_g2b` → load served, battery reduced
- `load_deficit = max_import` → load served, battery gets zero headroom
- `load_deficit > max_import` → load partially shed, battery gets zero

The `load_unserved = max(0.0, ...)` floating-point guard (L463 in original) is subsumed by
the new formula and can be removed. The `p_import = grid_to_load + p_g2b_actual` line is
unchanged.

---

## 4. Test cases

All cases test `env_step()` directly with controlled `weather` / `load` / `action` inputs.
Battery charging from grid is triggered by setting `a_bat = 1.0` with zero renewables
(nighttime: wind=0, irr=0).

With `GansuParams()` defaults: `bat_power_mw = 98.16`, `grid_max_import_mw = 400`.
`a_bat = 1.0` → `p_g2b = 98.16 MW` (no SOC clip at SOC=0.5).

### TC-1 — Discriminating case (bat reduced)
```
load = 350 MW,  p_g2b_raw = 98.16,  max_import = 400
Condition: 350 < 400 < 350 + 98.16 = 448.16

Correct:
  grid_to_load = min(350, 400) = 350 MW
  import_headroom = 400 - 350 = 50 MW
  p_g2b_actual = min(98.16, 50) = 50 MW
  p_import = 350 + 50 = 400 MW
  load_unserved = 0 MW  (zero VOLL)

Old (wrong):
  p_g2b_actual = 98.16 MW  (bat fully honoured)
  grid_to_load = 400 - 98.16 = 301.84 MW
  load_unserved = 48.16 MW  (963,200 ¥ spurious VOLL)
```

### TC-2 — Load exactly at import limit (bat gets zero headroom)
```
load = 400 MW,  p_g2b_raw = 98.16,  max_import = 400
  grid_to_load = min(400, 400) = 400 MW
  import_headroom = 400 - 400 = 0 MW
  p_g2b_actual = min(98.16, 0) = 0 MW
  p_import = 400 MW
  load_unserved = 0 MW
```

### TC-3 — Load exceeds import limit (load shed, bat gets nothing)
```
load = 500 MW,  p_g2b_raw = 98.16,  max_import = 400
  grid_to_load = min(500, 400) = 400 MW
  load_unserved = 500 - 400 = 100 MW
  import_headroom = 0 MW
  p_g2b_actual = 0 MW
  p_import = 400 MW
  c_voll_yuan = 20000 * 100 * 1.0 = 2,000,000 ¥
```

### TC-4 — No cap triggered (load + bat fits within limit)
```
load = 200 MW,  p_g2b_raw = 98.16,  max_import = 400
  p_import_required = 200 + 98.16 = 298.16 < 400 → no cap
  grid_to_load = 200 MW
  p_g2b_actual = 98.16 MW
  p_import = 298.16 MW
  load_unserved = 0 MW
```

---

## 5. Out of scope

- `jax_env.py` — already fixed in PR #33
- Any other cost/physics formula
- Parity tests against the JAX env are NOT added here (JAX is in `feat/env-jax-env-core`,
  not yet on main when this PR opens). Cross-implementation parity validation occurs when
  both branches merge and `TestJaxReferenceParity` is re-run.

---

## 6. Deliberate deviations

| Old behaviour | New behaviour | Reason |
|---|---|---|
| Two-branch: `max_import < p_g2b` → bat gets all, load gets 0 | Single-path load-first | §3.6 row 9 spec |
| `max_import ≥ p_g2b` → bat fully honoured, load capped | Load served first, bat gets remainder | §3.6 row 9 spec |

Both deviate from the original reference in the same direction: load is prioritised over
battery charging, matching `jax_env.py` after PR #33.
