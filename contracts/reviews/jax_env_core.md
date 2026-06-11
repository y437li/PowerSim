# Review record — `contracts/env/jax_env_core.md`

**Reviewer:** backend-reviewer
**Area:** env (→ backend-reviewer gates)
**PR:** #33 (`feat/env-jax-env-core`)
**Stage:** contract + tests gate (Stage 1, draft PR)

## Verdict: APPROVE (round-3, commit 4fd668a)

The approved suite = developer cases + reviewer-added cases (below).

## Round history

- **Round 1** (commit b8926540) — REQUEST_CHANGES. Blocker: parity suite (`tests/env/test_env_parity_gansu.py` `TestJaxReferenceParity`) used a stale `env_step(state, action, weather, load, params)` API that did not match the contract's `step(state, action, params, data)` design → D11 JAX-vs-reference parity would error/skip and the JAX core would ship unvalidated. Plus: add jit/vmap value-comparison cases.
- **Round 2** (commit 9bf18219) — REQUEST_CHANGES. Point 1 (parity-harness reconciliation) **resolved**: Suite 2 reworked to `step(...,data)` with a documented bridge (`jax_data` stacks `year_data`→(8760,4) in the contract column order; σ=0 RNG neutralization; §9 bridge doc; correct EnvInfo→StepResult field map). New blocker **B-A**: contract §5.3.7 demand-charge formula booked `P_import × rate` and reset `new_month_peak = P_import`, contradicting the merged reference (`src/reference/gansu_env.py` L484/503/504: `max(month_peak, P_import) × rate`, reset `0.0`) **and** the PR's own `test_month_boundary_books_demand_charge` (150×32000) / `test_year_end_terminal_flush` (200×32000). Two should-fixes: §5.4 invalid `data[t_fc,4_price_column]`; unpinned RNG split between obs-forecast noise and price-spread draw.
- **Round 3** (commit 4fd668a) — **APPROVE.** All resolved:
  - **B-A:** §5.3.7 now `peak_incl_now = max(state.month_peak, P_import)`; `C_demand_charge = where(books_charge, peak_incl_now*rate, 0)`; `new_month_peak = where(books_charge, 0.0, peak_incl_now)`. Matches reference L484/503/504 and both failing tests. Invariant note added. Shape term `C_DC_shape` (L431) correctly still uses `state.month_peak` (pre-update), matching reference L483.
  - **Should-fix 1:** `obs[base+3] = clip(PRICE_TABLE_YPW[t_fc%24] * (1+ε[3]), 0)`; note added that `data` has exactly 4 columns.
  - **Should-fix 2:** 3-way split `rng_spread, rng_fc_init, new_rng = split(state.rng, 3)`; `get_obs()` external derivation pinned.

## Reviewer-added cases (pushed on this branch, marked `# reviewer:`)

Hand-derived; arithmetic in comments. Three in `tests/env/test_env_jax_env_core.py` (new class `TestReviewerAddedJaxCore`), one in `tests/env/test_env_parity_gansu.py` (`TestJaxReferenceParity`):

1. **`test_jit_step_matches_eager`** — value equality of `jax.jit(step)` vs eager `step` on reward, `new_state.{soc,month_peak,t}`, `done`, `EnvInfo.{c_energy_yuan,p_import_mw}`, and obs. §14 only checked jit *compiles* + shapes, and `test_fixed_seed_determinism` calls `step` twice on the same state (trivially equal). Independent jnp.where-purity check: a stray data-dependent Python branch traces away under jit and would diverge here. Oracle = eager result (self-referential; no magic number).
2. **`test_vmap_step_over_batch`** — `vmap(step, in_axes=(0,0,None,None))` over N=8 identical envs → all lanes identical (reward, soc, obs) **and** equal to the serial single-env step. §14 `test_step_vmap_compiles` only checks output shapes, not lane-identity. Oracle = serial result.
3. **`test_month_peak_resets_to_exactly_zero_after_booking`** — pins `new_state.month_peak == 0.0` (abs 1e-6) after a Jan→Feb boundary booking. Tightens the existing `< 300` assertion, which the round-2 B-A bug (reset to P_import≈50) would also have passed. Hand value: 0.0.
4. **`test_month_boundary_demand_charge_parity`** — closes the parity gap that hid B-A (the suite never cross-checked `c_demand_charge`). Step t=743 (last Jan hour) with `month_peak=500` MW (> `grid_max_import_mw`=400, so it dominates the import-capped P_import) → booked charge is deterministically `500×32000 = 16,000,000` ¥. Asserts (1) the hand value on JAX, (2) the hand value on the reference, (3) JAX == reference, (4) both reset `month_peak` to 0.

## Notes for QA

- Red-phase: own-file tests fail/error on import until `energy_go.env.jax_env` lands; `TestJaxReferenceParity` skips until then. `py_compile` clean on both files. (Local pytest run blocked only by a system-interpreter arch mismatch; run under the project's Python 3.11 / uv env.)
- Post-implementation, run the `physics-invariants` battery (energy conservation per source, D13 cost identities, physical bounds, fixed-seed determinism, checkpoint round-trip) plus the full parity suite on the Gansu config (D11).

---

## Stage-2 implementation audit — F-IMPORT fix (PR #33 @ dc87b65)

**Reviewer:** backend-reviewer · **Verdict:** APPROVE

Re-audit after the REQUEST_CHANGES on the §3.6-row-9 import-priority bug. All four items resolved:

1. **F-IMPORT, `jax_env.py` STEP 7 — correct (load-first).** `grid_to_load = min(load_deficit, grid_max_import_mw)`; battery receives only `import_headroom_for_bat = max(0, max_import − grid_to_load)`; `load_unserved = max(0, load_deficit − grid_to_load)`. Matches §3.6 row 9 ("load served first, then battery charging reduced, then load shed"). `P_import = grid_to_load + P_grid_to_bat_actual`. Pure `jnp.minimum`/`maximum`, no data-dependent branching.
2. **F-IMPORT, `gansu_env.py` STEP 8 — correct (same load-first logic).** `load_unserved` subtracts all four load sources (wind/solar/bat/grid to-load). Parity now compares two correct implementations (closes the "two wrongs agree" gap the original parity suite had).
3. **Discriminating tests — `TestImportCapPriority` (3 cases).** Reviewer re-derived every expected value by hand against `bat_power_mw=98.16`, `soc=0.5` (SOC-headroom 121.4 MW > 98.16 → no clip → `P_grid_to_bat_raw=98.16`):
   - load=350: `grid_to_load=min(350,400)=350`, `bat=min(98.16,50)=50`, `import=400`, `unserved=0`, VOLL=0. ✓
   - load=400 (== max_import): `grid_to_load=400`, headroom=0, `bat=0`, `import=400`, `unserved=0`. ✓ (boundary)
   - load=500 (> max_import): `grid_to_load=400`, `unserved=100`, `bat=0`, `import=400`, `c_voll=20000×100×1.0=2,000,000 ¥`. ✓
   Assertions correctly depend only on `raw>50` to discriminate, so they are robust to the exact charge-power value. Cases span bat-reduced / bat-zeroed-at-limit / load-shed.
4. **EnvInfo `load_capped` + `import_cap_active`.** Additive-only (no removed/renamed fields). Definitions in code, contract §3.3 (`p_import == p_grid_to_bat + p_grid_to_load`), and contract bool-defs all agree.

**Provenance note (action item, non-blocking):** `git log -S` shows `TestImportCapPriority` was authored in the engineer's `dc87b65`, but it carries `# reviewer:` markers attributing it to "backend-reviewer PR #33 audit". I did not author these — I *verified* them. Resolution: I adopt them as **reviewer-validated** regression tests (every expected value re-derived above). Cleaner going forward: engineer-drafted tests prompted by a review should not self-apply `# reviewer:`; relabel to a plain docstring if preferred. Either way the cases stand and are correct.

**Minor doc nit (non-blocking):** contract §3.6-rule-9 pseudocode references an undefined `P_grid_to_bat_reduction` and is superseded by a "Simpler:" line. The implementation note + actual code are correct; tidy the pseudocode when convenient.

**Closing evidence owed to QA (not runnable in this reviewer env — x86_64/arm64 jaxlib mismatch):** `scripts/run_physics_invariants.py` (INV-1…5), the JAX-vs-reference parity suite, and `TestImportCapPriority` must all pass in QA's run before this closes.
