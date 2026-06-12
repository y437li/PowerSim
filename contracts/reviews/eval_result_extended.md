# Review record — `contracts/training/eval_result_extended.md` (PR #82, task #55)

**Reviewer:** backend-reviewer · **Routing:** training area (backend-reviewer binding gate; not shared)
**Tests:** `tests/training/test_training_eval_result_extended.py`

## Stage 1 — contract + tests gate: APPROVE (v3 stream-keyed @ 67e9033)

### Design (v3, per rl-architect D31/F1 architectural ruling)
`PolicyEvalResult` gains `streams: dict[str, StreamAccumulator]` where
`StreamAccumulator(volume, value_yuan)` is a 2-leaf NamedTuple. 6 rev4 keys pre-declared:
`grid_export`, `grid_import`, `demand_charge`, `h2_sale`, `avoided_cost`, `token_sale`
(last three = zero placeholders, no structural change needed to activate). Plus the
physical-quantity accumulators. All `value_yuan` are **real year-1 ¥** (D31/F1 constant-real;
escalation is finance-layer post-eval). Pure accumulation/derivation of existing EnvInfo —
no new physics, no LOCKED-env touch.

### Verified
- **Wire isolation — STRONG.** `test_wire_has_exactly_9_locked_keys` asserts the exact 9-key
  set on the full v3 result, and `assert "streams" not in wire` — the `streams` dict does NOT
  leak to the LOCKED `eval_compare` wire. ✓
- **D13 identity — correct.** `energy_cost_yuan == streams["grid_import"].value_yuan −
  streams["grid_export"].value_yuan` (= Σc_import − Σr_export = Σc_energy); both import+export
  and export-dominant cases tested. ✓
- **`demand_charge` (D31/F1) — correct.** `volume = max(c_demand_charge_yuan)/demand_rate` =
  annual peak MW (the highest monthly peak); `value_yuan = Σ c_demand_charge_yuan` (total).
  Tested separately (volume=5.0, value=800 in the worked case) — correctly does NOT assert a
  `volume×rate=value` identity (they are different quantities in v3). ✓
- **Conservation / hand-values** — wind/pv/bat conservation, generation/throughput
  decomposition, the 8 identities all tested with correct hand-computed values.
- **Scope creep — NONE.** No EnvInfo or eval_compare LOCKED change → no DECISION needed.

### Reviewer-added cases (2, `# reviewer:`)
- `test_aggregate_curtailed_equals_per_source_sum` — unchanged from v2 (`curtailed_mwh ==
  Σ per-source curtailed`).
- `test_grid_import_volume_equals_to_bat_plus_to_load` — **adapted** for v3 (LHS now
  `streams["grid_import"].volume`); same F-IMPORT §3.6-row-9 physics assertion, adaptation
  disclosed in the docstring. Reviewer-verified: the adaptation preserves the cross-check.

### Lineage
v2 (flat 36-field) was APPROVED @ d61bc27; rl-architect ruled the stream-keyed structure → v3.
Reviewer cases survived the v3 restructure (grid-import correctly adapted, not dropped).
