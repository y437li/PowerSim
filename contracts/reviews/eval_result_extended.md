# Review record — `contracts/training/eval_result_extended.md` (PR #82, task #55)

**Reviewer:** backend-reviewer · **Routing:** training area (backend-reviewer binding gate; not shared)
**Tests:** `tests/training/test_training_eval_result_extended.py`

## Stage 1 — contract + tests gate: APPROVE @ 2b12566

### Verified
- **Q5 / scope creep — NONE.** All 24 new fields are pure `Σ info.X` accumulations of
  **existing** EnvInfo fields (zero new physics). I cross-checked all 16 `info.*` source
  names against `EnvInfo` on main — every one exists (no `penalty_yuan`-class typo). No
  EnvInfo change, no `eval_compare` wire change → no LOCKED contract touched, no DECISION
  needed. The contract correctly cites the rl-architect telemetry-lock constraint (§1).
- **Q1 / wire isolation — STRONG.** `TestWireIsolation.test_policy_dict_has_exactly_9_keys`
  asserts `set(_policy_dict(result).keys()) == {the 9 LOCKED keys}` with a fully-populated
  33-field result — an exact-set check that fails if any new field leaks to the wire (e.g.
  an `asdict()`-based `_policy_dict`). Plus `no_mwh`, `no_cost_stream_split`,
  `existing_values_unchanged`. The LOCKED eval_compare wire is protected.
- **Q2 / conservation + Q3 / 24-key** — per-source wind/pv/bat conservation + D13 cost
  identity (`energy_cost = c_import − r_export`) tested with hand-computed values;
  `_accumulate_physical_quantities` returns exactly 24 keys (2+9+13), verified.
- **Q4 / eval_results.json** — `physical_quantities` top-level key parallel to `policies`;
  `policies` stays 9-locked (`test_policies_dict_has_only_9_locked_fields`). Sensible for
  workstream-D (LCOE/LCOS/OPEX) consumers.

### Reviewer-added cases (2, `# reviewer:`, hand-derived) @ 2b12566
- `test_aggregate_curtailed_equals_per_source_sum` — `curtailed_mwh == wind+pv+bat
  curtailed_mwh` (aggregate-vs-per-source consistency the suite didn't cross-check).
- `test_grid_import_equals_to_bat_plus_to_load` — `grid_import_mwh == grid_to_bat_mwh +
  grid_to_load_mwh`; **cross-checks the F-IMPORT §3.6-row-9 fix** (a battery-first
  regression would break this accumulated identity).

**Approved suite = developer's ~40 + reviewer's 2.** Implementation pending; this is the
contract+tests gate.
