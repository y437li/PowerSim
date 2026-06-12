# Review record — `contracts/training/eval_result_extended.md` (PR #82, task #55)

**Reviewer:** backend-reviewer · **Routing:** training area (backend-reviewer binding gate; not shared)
**Tests:** `tests/training/test_training_eval_result_extended.py`

## Stage 1 — contract + tests gate: APPROVE (stream-shaped revision @ 91c641a + reviewer restore)

### Design
Extends `PolicyEvalResult` 9 → **36** fields (9 existing wire-locked + 27 new), stream-shaped per
finance §5.3. All new fields are **pure accumulation/derivation of existing EnvInfo** — zero new
physics, zero LOCKED-env touch (my forward-looking flag was heeded):
- `generation_mwh = Σ(p_wind_mw + p_pv_mw)` (LCOE denominator), `bat_throughput_mwh = Σ(p_bat_ch_mw
  + p_bat_dis_mw)` (cycle-life/VarOM) — existing fields.
- `demand_billing_mw_month = demand_charge_yuan / params.demand_rate_yuan_per_mw_month` — a pure
  **derivation** (no new EnvInfo field); reconciliation `billing × rate = demand_charge_yuan` tested.

### Verified
- **Wire isolation — STRONG.** `test_policy_dict_has_exactly_9_keys` still asserts the *exact* 9-key
  set on the fully-populated 36-field result → any leak to the LOCKED `eval_compare` wire fails.
- **Scope creep — NONE.** All `info.*` accumulation sources cross-checked against EnvInfo; no
  EnvInfo/eval_compare LOCKED change → no DECISION needed. h2/avoided/token confirmed v1-out-of-scope
  (tests guard against their presence).
- **Identities/hand-values** — wind/pv/bat conservation, D13 cost (`energy_cost = c_import − r_export`),
  generation/throughput decomposition, demand-billing reconciliation — all with correct hand-values.

### Reviewer-added cases (2, `# reviewer:`, hand-derived)
- `test_aggregate_curtailed_equals_per_source_sum` — `curtailed_mwh == Σ per-source curtailed`.
- `test_grid_import_equals_to_bat_plus_to_load` — `grid_import_mwh == grid_to_bat + grid_to_load`;
  **cross-checks the F-IMPORT §3.6-row-9 fix**.

### Process note
These 2 cases (originally @ 2b12566) + this review record were **dropped by the 91c641a revision**;
restored. Fifth reviewer-artifact drop across PRs — pre-push `git diff <prior-HEAD>..HEAD` must be
adopted to catch `# reviewer:` / `contracts/reviews/` deletions.
