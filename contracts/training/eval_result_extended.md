# Extended PolicyEvalResult — per-stream + physical-quantity accumulators

**Contract:** `contracts/training/eval_result_extended.md`
**Area:** training (env eval path)  
**Spec:** §5.5 (eval loop), §3 (physics / EnvInfo), master plan §5.5/§8 (finance finding)  
**Decisions:** D3 (Δt=1h, 8760 eval steps), D13 (cost separation: real-money vs reward-basis), D17 (E1 deferred — no new physics)  
**Owners:** jax-env-engineer + training-engineer  
**Reviewer:** backend-reviewer  
**Prerequisite for:** workstream D (project finance — LCOE/LCOS/OPEX/replacement cost inputs)

---

## 1. Motivation and scope

Today's `PolicyEvalResult` reports only 9 fields: 5 annual cost aggregates, 1 derived total, and 3 safety/penalty metrics.  
This is insufficient for workstream D finance (LCOE requires wind/PV MWh generated; LCOS requires battery charge/discharge MWh; OPEX breakdown requires r_export and c_import split).

All physical flows needed already exist in `EnvInfo` (per-step outputs of the JAX env core, PR #33).  
This contract adds **accumulation only** — no new physics, no new EnvInfo fields.

**Binding constraint (rl-architect, telemetry-lock owner):** the LOCKED `eval_compare` wire message does NOT gain any new fields (no minor version bump). New fields live in the Python `PolicyEvalResult` dataclass and the `eval_results.json` file stored on disk; the REST `/eval` endpoint amendment is workstream D (serving-engineer follow-on, out of scope here).

---

## 2. Extended `PolicyEvalResult` dataclass

Location: `src/energy_go/training/eval.py`  
Type: `@dataclass` (unchanged from today's pattern)

```python
@dataclass
class PolicyEvalResult:
    # -----------------------------------------------------------------------
    # EXISTING 9 FIELDS — WIRE-LOCKED (eval_compare payload, D13 real money)
    # _policy_dict() in telemetry.py serialises ONLY these 9 to the wire.
    # DO NOT REMOVE or RENAME any of these.
    # -----------------------------------------------------------------------
    energy_cost_yuan:     float   # Σ c_energy_yuan = c_import_yuan − r_export_yuan (D13)
    demand_charge_yuan:   float   # Σ c_demand_charge_yuan (month-boundary, D10/D21)
    degradation_yuan:     float   # Σ c_degradation_yuan
    curtailment_yuan:     float   # Σ c_curtail_yuan
    voll_yuan:            float   # Σ c_voll_yuan
    total_cost_yuan:      float   # = sum of the 5 above (real money)
    soc_violations_count: int     # steps where soc_violation_mwh > 0
    soc_violation_mwh:    float   # total SOC overshoot energy (MWh)
    penalty_yuan:         float   # Σ penalty_yuan (reward-shaping; NOT in total_cost_yuan)

    # -----------------------------------------------------------------------
    # NEW: per-stream cost split (¥) — D13 identity: energy_cost_yuan = c_import_yuan − r_export_yuan
    # -----------------------------------------------------------------------
    r_export_yuan:        float   # Σ info.r_export_yuan (revenue; ≥ 0)
    c_import_yuan:        float   # Σ info.c_import_yuan (cost; ≥ 0)

    # -----------------------------------------------------------------------
    # NEW: aggregate physical-quantity accumulators (MWh)
    # Δt = 1 h (D3); accumulation = Σ p_X_mw × 1 h over 8760 steps.
    # All ≥ 0.
    # -----------------------------------------------------------------------
    wind_generated_mwh:   float   # Σ info.p_wind_mw
    pv_generated_mwh:     float   # Σ info.p_pv_mw
    bat_charge_mwh:       float   # Σ info.p_bat_ch_mw
    bat_discharge_mwh:    float   # Σ info.p_bat_dis_mw
    grid_import_mwh:      float   # Σ info.p_import_mw
    grid_export_mwh:      float   # Σ info.p_export_mw
    load_served_mwh:      float   # Σ info.p_load_served_mw
    load_unserved_mwh:    float   # Σ info.p_load_unserved_mw
    curtailed_mwh:        float   # Σ info.p_curtailed_mw (aggregate = wind + pv + bat curtailed)

    # -----------------------------------------------------------------------
    # NEW: per-source flow breakdown (MWh) — 13 EnvInfo per-source fields × Δt
    # Energy-conservation identities (§3, §6):
    #   wind_generated_mwh = wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed
    #   pv_generated_mwh   = pv_to_load   + pv_to_bat   + pv_to_grid   + pv_curtailed
    #   bat_discharge_mwh  = bat_to_load  + bat_to_grid  + bat_curtailed
    # All ≥ 0.
    # -----------------------------------------------------------------------
    wind_to_load_mwh:     float   # Σ info.p_wind_to_load_mw
    wind_to_bat_mwh:      float   # Σ info.p_wind_to_bat_mw
    wind_to_grid_mwh:     float   # Σ info.p_wind_to_grid_mw
    wind_curtailed_mwh:   float   # Σ info.p_wind_curtailed_mw
    pv_to_load_mwh:       float   # Σ info.p_sol_to_load_mw
    pv_to_bat_mwh:        float   # Σ info.p_sol_to_bat_mw
    pv_to_grid_mwh:       float   # Σ info.p_sol_to_grid_mw
    pv_curtailed_mwh:     float   # Σ info.p_sol_curtailed_mw
    bat_to_load_mwh:      float   # Σ info.p_bat_to_load_mw
    bat_to_grid_mwh:      float   # Σ info.p_bat_to_grid_mw
    bat_curtailed_mwh:    float   # Σ info.p_bat_curtailed_mw
    grid_to_bat_mwh:      float   # Σ info.p_grid_to_bat_mw
    grid_to_load_mwh:     float   # Σ info.p_grid_to_load_mw
```

**Total new fields:** 2 cost-stream + 9 aggregate + 13 per-source = **24 new fields** (dataclass goes from 9 → 33 fields).

---

## 3. Accumulation formula

For each new field, the accumulation rule is:

```
field_mwh = float(jnp.sum(infos.p_X_mw))   # Δt = 1 h (D3), so MW × 1 h = MWh
```

`infos` is the stacked `EnvInfo` output of `jax.lax.scan(_step, init_state, None, length=8760)` — shape `(8760,)` per scalar field.

Since Δt = 1 h (D3), no explicit multiplication is needed: `Σ p_X_mw` in MW units over 8760 steps equals MWh (each step contributes 1 MW-hour).

### Extracted helper (independently testable)

A standalone helper `_accumulate_physical_quantities(infos)` is introduced in `eval.py`:

```python
def _accumulate_physical_quantities(infos) -> dict[str, float]:
    """Accumulate per-step EnvInfo fields into physical-quantity totals (MWh, ¥).

    Args:
        infos: stacked EnvInfo from lax.scan — each field has shape (N,).

    Returns:
        Dict of the 24 new PolicyEvalResult fields.
        Pure accumulation — ZERO new physics.
    """
```

`run_eval()` calls this helper after the scan and merges its output into the `PolicyEvalResult` constructor call alongside the existing 9 fields.

---

## 4. Conservation identities (must hold)

These are derivable from the existing per-step EnvInfo invariants (§3, physics-invariants skill):

1. **Wind conservation:**  
   `wind_generated_mwh == wind_to_load_mwh + wind_to_bat_mwh + wind_to_grid_mwh + wind_curtailed_mwh`

2. **PV conservation:**  
   `pv_generated_mwh == pv_to_load_mwh + pv_to_bat_mwh + pv_to_grid_mwh + pv_curtailed_mwh`

3. **Battery discharge conservation:**  
   `bat_discharge_mwh == bat_to_load_mwh + bat_to_grid_mwh + bat_curtailed_mwh`

4. **D13 cost identity:**  
   `energy_cost_yuan == c_import_yuan - r_export_yuan` (exact, to float32 precision)

Tolerance for identities 1–3: `atol = max(1e-3, 1e-5 × sum_mwh)` (float32 accumulation error over 8760 steps).  
Identity 4: exact (both sides derive from the same `c_energy_yuan` EnvInfo field).

---

## 5. Wire isolation — LOCKED eval_compare unchanged

**`_policy_dict()` in `src/energy_go/training/telemetry.py` is NOT modified.**  
It explicitly constructs a dict with exactly the 9 LOCKED keys — new dataclass fields are invisible to the wire by construction.

**Contract test:** given an extended `PolicyEvalResult` populated with non-zero values in all 24 new fields, `_policy_dict(result)` must return a dict with **exactly** these 9 keys (no extras):  
`energy_cost_yuan`, `demand_charge_yuan`, `degradation_yuan`, `curtailment_yuan`, `voll_yuan`, `total_cost_yuan`, `soc_violations_count`, `soc_violation_mwh`, `penalty_yuan`.

---

## 6. Storage — `eval_results.json` extension

After this contract is implemented, `eval_results.json` is extended:

```jsonc
{
  // existing eval_compare payload (unchanged — fed directly to eval_compare wire)
  "eval_horizon_steps": 8760,
  "checkpoint_id": "...",
  "cost_basis": "real_money",
  "policies": {
    "rl":          { /* 9 LOCKED fields */ },
    "no_battery":  { /* 9 LOCKED fields */ },
    "rule_based_tou": { /* 9 LOCKED fields */ }
  },

  // NEW top-level key — physical quantities per policy (NOT part of eval_compare wire)
  "physical_quantities": {
    "units": {
      "*_mwh":   "MWh (Δt=1h × MW accumulated over 8760 steps)",
      "r_export_yuan": "¥ revenue from grid export",
      "c_import_yuan": "¥ cost of grid import"
    },
    "rl":          { /* 24 new fields */ },
    "no_battery":  { /* 24 new fields */ },
    "rule_based_tou": { /* 24 new fields */ }
  }
}
```

The `GET /runs/{run_id}/eval` REST endpoint currently serves `eval_results.json` **verbatim**.  
Post-implementation it will pass through the `physical_quantities` key automatically — no serving-layer code change required (the endpoint is a pass-through; the extension is additive and the JSON Schema uses `additionalProperties: true`).  
Explicit workstream D REST endpoint amendment (e.g., typed response schema, units display) is a serving-engineer follow-on.

---

## 7. API summary

```python
# src/energy_go/training/eval.py

def _accumulate_physical_quantities(infos) -> dict[str, float]:
    """Accumulate (N,)-shaped EnvInfo into 24 physical-quantity totals.
    Pure accumulation — no physics. Called by run_eval() after lax.scan.
    """

def run_eval(
    checkpoint: "CheckpointData",
    data: object,
    params=None,
) -> PolicyEvalResult:
    """Deterministic policy rollout over 8760 steps.
    Returns an extended PolicyEvalResult with 33 total fields (9 existing + 24 new).
    eval_compare wire serialization unchanged (telemetry._policy_dict uses 9 LOCKED keys).
    """
```

---

## 8. Out of scope

1. **Any changes to `EnvInfo`** — ZERO new physics, zero new env fields.
2. **eval_compare wire format** — LOCKED, NO field additions, NO version bump.
3. **REST `/eval` typed response schema amendment** — workstream D, serving-engineer follow-on.
4. **Hourly time series (8760-length arrays)** — only annual totals (scalar MWh/¥ per year).
5. **SOC time series or SOC-related physical quantities** — out of scope; SOC safety metrics are the existing fields.
6. **§10 E1 battery aging** — deferred per D17; wear/lifetime fields are task #57 (device_models.yaml v1.1.0).

---

## 9. Deliberate deviations from current code

None — this contract is purely additive. No §6 bug fixes; no behavioral changes to existing fields; the 9 LOCKED fields are computed identically to today.

---

## 10. Implementation checklist (for QA)

- [ ] `PolicyEvalResult` has exactly 33 fields (9 existing + 2 cost-stream + 9 aggregate + 13 per-source)
- [ ] `_accumulate_physical_quantities()` extracted as standalone helper, tested independently
- [ ] `run_eval()` returns extended result; the 9 existing fields are numerically unchanged
- [ ] `_policy_dict()` in `telemetry.py` is unmodified (still 9 keys)
- [ ] `eval_results.json` gains `physical_quantities` top-level key with 24 fields per policy
- [ ] All 4 conservation identities hold in `test_training_eval_result_extended.py`
- [ ] `@pytest.mark.slow` on any test that runs the full 8760-step JAX scan (D30)
