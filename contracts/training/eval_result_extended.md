# Extended PolicyEvalResult — per-stream + physical-quantity accumulators

**Contract:** `contracts/training/eval_result_extended.md`
**Area:** training (env eval path)
**Spec:** §5.5 (eval loop), §3 (physics / EnvInfo), master plan §5.3/§5.5/§8 (finance finding)
**Decisions:** D3 (Δt=1h, 8760 eval steps), D10/D21 (demand charge booking), D13 (cost separation: real-money vs reward-basis), D17 (E1 deferred — no new physics)
**Owners:** jax-env-engineer + training-engineer
**Reviewer:** backend-reviewer
**Prerequisite for:** workstream D (project finance — LCOE/LCOS/OPEX/replacement cost inputs)
**Finance input:** §5.3 rev4 (stream list + quantity requirements, finance-expert advisory)

---

## 1. Motivation and scope

Today's `PolicyEvalResult` reports only 9 fields: 5 annual cost aggregates, 1 derived total, and 3 safety/penalty metrics. This is insufficient for workstream D finance:
- LCOE needs total generation MWh (wind + solar)
- LCOS needs battery discharge MWh + throughput MWh
- OPEX needs grid-export/import volumes + revenue/cost
- Demand-charge reconciliation needs Σ monthly-peak volume

All physical flows needed already exist in `EnvInfo` (per-step outputs of the JAX env core, PR #33). This contract adds **accumulation only** — no new physics, no new EnvInfo fields.

### Stream structure (§5.3 rev4)

Finance workstream D uses a **stream-keyed map** at the REST `/api/finance/compare` layer for forward-compat. `PolicyEvalResult` itself grows **additively** (flat fields) — each new future stream genuinely needs new EnvInfo accumulators, so minor-bump additions are correct. Do **NOT** add zero-placeholder fields for v1-inactive streams (h2_sale, avoided_cost, token_sale); they require physical quantities that don't exist in power-only dispatch.

**v1 wired streams (power-only dispatch):**

| Stream | Volume field | Value field |
|---|---|---|
| `grid_export` | `grid_export_mwh` (MWh) | `r_export_yuan` (¥ revenue) |
| `grid_import` | `grid_import_mwh` (MWh) | `c_import_yuan` (¥ cost) |
| `demand_charge` | `demand_billing_mw_month` (MW·month) | `demand_charge_yuan` (¥, **existing field**) |

**Reconciliation identity (demand_charge stream):**
`demand_charge_yuan = demand_billing_mw_month × params.demand_rate_yuan_per_mw_month`
i.e., `demand_billing_mw_month = demand_charge_yuan / params.demand_rate_yuan_per_mw_month`

**Out-of-scope v1 streams:** `h2_sale`, `avoided_cost`, `token_sale` — no placeholder fields; these are additive minor-bump additions when their scenarios land (§5.3 v1 scope guard).

**Binding constraint (rl-architect, telemetry-lock owner):** the LOCKED `eval_compare` wire message does NOT gain any new fields. New fields live in `PolicyEvalResult` and `eval_results.json`; the REST `/eval` endpoint serves `eval_results.json` verbatim (pass-through already handles additive extension). Typed REST schema amendment is workstream D (serving-engineer follow-on, out of scope here).

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
    total_cost_yuan:      float   # = sum of the 5 above (real money, D13)
    soc_violations_count: int     # steps where soc_violation_mwh > 0
    soc_violation_mwh:    float   # total SOC overshoot energy (MWh)
    penalty_yuan:         float   # Σ penalty_yuan (reward-shaping; NOT in total_cost_yuan)

    # -----------------------------------------------------------------------
    # NEW: grid_export stream — volume + value (¥)
    # D13 identity: energy_cost_yuan = c_import_yuan − r_export_yuan
    # -----------------------------------------------------------------------
    grid_export_mwh:      float   # Σ info.p_export_mw × 1h  (stream volume, MWh; ≥ 0)
    r_export_yuan:        float   # Σ info.r_export_yuan      (stream value, ¥ revenue; ≥ 0)

    # -----------------------------------------------------------------------
    # NEW: grid_import stream — volume + value (¥)
    # -----------------------------------------------------------------------
    grid_import_mwh:      float   # Σ info.p_import_mw × 1h  (stream volume, MWh; ≥ 0)
    c_import_yuan:        float   # Σ info.c_import_yuan      (stream value, ¥ cost; ≥ 0)

    # -----------------------------------------------------------------------
    # NEW: demand_charge stream — volume (demand_charge_yuan is the existing wire-locked value)
    # demand_billing_mw_month = demand_charge_yuan / params.demand_rate_yuan_per_mw_month
    # Reconciliation: demand_charge_yuan = demand_billing_mw_month × demand_rate
    # -----------------------------------------------------------------------
    demand_billing_mw_month: float  # Σ_m month_peak_m (MW·month; ≥ 0)

    # -----------------------------------------------------------------------
    # NEW: physical-quantity accumulators — required by finance for LCOE/LCOS/OPEX
    # Δt = 1 h (D3); accumulation = Σ p_X_mw × 1 h = MWh.
    # All ≥ 0.
    # -----------------------------------------------------------------------
    generation_mwh:       float   # Σ (info.p_wind_mw + info.p_pv_mw)  ← LCOE denominator
    wind_generated_mwh:   float   # Σ info.p_wind_mw                    (component of generation)
    pv_generated_mwh:     float   # Σ info.p_pv_mw                      (component of generation)
    bat_charge_mwh:       float   # Σ info.p_bat_ch_mw
    bat_discharge_mwh:    float   # Σ info.p_bat_dis_mw                  ← LCOS denominator
    bat_throughput_mwh:   float   # Σ (info.p_bat_ch_mw + info.p_bat_dis_mw)  ← VarOM, cycle-life
    load_served_mwh:      float   # Σ info.p_load_served_mw
    load_unserved_mwh:    float   # Σ info.p_load_unserved_mw            ← reliability (INV-VOLL)
    curtailed_mwh:        float   # Σ info.p_curtailed_mw                ← INV-CURT

    # -----------------------------------------------------------------------
    # NEW: per-source flow breakdown (13 fields, MWh = MW × 1h per step)
    # Conservation identities (§3, physics-invariants):
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

**Field count:** 9 existing + 27 new = **36 total fields**.

New fields breakdown: 5 stream (grid_export×2 + grid_import×2 + demand_billing×1) + 9 physical-quantity + 13 per-source = 27.

---

## 3. Accumulation formulas

### `_accumulate_physical_quantities(infos) → dict[str, float]`

A standalone helper in `eval.py`, independently testable without running the full eval loop.
Takes the stacked `EnvInfo` output of `jax.lax.scan` (each field shape `(N,)`) and returns a dict of the **26 directly-accumulated** new fields (all except `demand_billing_mw_month`).

```python
def _accumulate_physical_quantities(infos) -> dict[str, float]:
    """Accumulate per-step EnvInfo fields into physical-quantity totals (MWh, ¥).

    Args:
        infos: stacked EnvInfo from lax.scan — each field has shape (N,).

    Returns:
        Dict of 26 new PolicyEvalResult fields (all except demand_billing_mw_month).
        Pure accumulation of existing EnvInfo fields — ZERO new physics.
    """
```

Since Δt = 1 h (D3), `Σ p_X_mw` in MW equals MWh directly — no explicit multiplication needed.

### `demand_billing_mw_month` (derived in `run_eval()`, not in helper)

```python
demand_charge_yuan = float(jnp.sum(infos.c_demand_charge_yuan))  # existing accumulation
demand_billing_mw_month = (
    demand_charge_yuan / params.demand_rate_yuan_per_mw_month
    if params.demand_rate_yuan_per_mw_month != 0.0
    else 0.0
)
```

Requires `params` (from `run_eval`'s argument), so it's computed in `run_eval()` after the helper call.
Reconciliation identity: `demand_charge_yuan = demand_billing_mw_month × demand_rate` (exact, float32 division).

### Summary of accumulations

```python
# Δt = 1h (D3)
grid_export_mwh      = float(jnp.sum(infos.p_export_mw))
r_export_yuan        = float(jnp.sum(infos.r_export_yuan))
grid_import_mwh      = float(jnp.sum(infos.p_import_mw))
c_import_yuan        = float(jnp.sum(infos.c_import_yuan))
# demand_billing_mw_month: see above (derived in run_eval)
generation_mwh       = float(jnp.sum(infos.p_wind_mw + infos.p_pv_mw))
wind_generated_mwh   = float(jnp.sum(infos.p_wind_mw))
pv_generated_mwh     = float(jnp.sum(infos.p_pv_mw))
bat_charge_mwh       = float(jnp.sum(infos.p_bat_ch_mw))
bat_discharge_mwh    = float(jnp.sum(infos.p_bat_dis_mw))
bat_throughput_mwh   = float(jnp.sum(infos.p_bat_ch_mw + infos.p_bat_dis_mw))
load_served_mwh      = float(jnp.sum(infos.p_load_served_mw))
load_unserved_mwh    = float(jnp.sum(infos.p_load_unserved_mw))
curtailed_mwh        = float(jnp.sum(infos.p_curtailed_mw))
# per-source (13 fields, same pattern)
wind_to_load_mwh     = float(jnp.sum(infos.p_wind_to_load_mw))
# ... etc.
```

---

## 4. Conservation and reconciliation identities (must hold)

1. **Wind source conservation:**
   `wind_generated_mwh == wind_to_load_mwh + wind_to_bat_mwh + wind_to_grid_mwh + wind_curtailed_mwh`

2. **PV source conservation:**
   `pv_generated_mwh == pv_to_load_mwh + pv_to_bat_mwh + pv_to_grid_mwh + pv_curtailed_mwh`

3. **Battery discharge conservation:**
   `bat_discharge_mwh == bat_to_load_mwh + bat_to_grid_mwh + bat_curtailed_mwh`

4. **D13 cost identity:**
   `energy_cost_yuan == c_import_yuan - r_export_yuan` (exact, float32 precision)

5. **generation decomposition:**
   `generation_mwh == wind_generated_mwh + pv_generated_mwh` (exact — computed from same arrays)

6. **bat_throughput decomposition:**
   `bat_throughput_mwh == bat_charge_mwh + bat_discharge_mwh` (exact)

7. **demand_charge reconciliation:**
   `demand_charge_yuan == demand_billing_mw_month × params.demand_rate_yuan_per_mw_month`
   (holds to float32 round-trip precision of division + multiplication)

Tolerance for identities 1–3: `atol = max(1e-3, 1e-5 × sum_mwh)` (float32 accumulation over 8760 steps).
Identities 4–6: exact (computed from same JAX arrays in the same scan).
Identity 7: to float32 division precision (~1e-5 relative).

---

## 5. Wire isolation — LOCKED eval_compare unchanged

**`_policy_dict()` in `src/energy_go/training/telemetry.py` is NOT modified.**
It explicitly constructs a dict with exactly the 9 LOCKED keys — new dataclass fields are invisible to the wire by construction.

Contract test: given an extended `PolicyEvalResult` with all 36 fields populated, `_policy_dict(result)` must return a dict with **exactly** the 9 LOCKED keys.

---

## 6. Storage — `eval_results.json` extension

```jsonc
{
  // existing eval_compare payload (unchanged — fed to eval_compare wire)
  "eval_horizon_steps": 8760,
  "checkpoint_id": "...",
  "cost_basis": "real_money",
  "policies": { "rl": { /* 9 LOCKED fields */ }, ... },

  // NEW: physical quantities + stream volumes (NOT part of eval_compare wire)
  "physical_quantities": {
    "units": {
      "*_mwh":              "MWh (Δt=1h × MW accumulated over eval horizon)",
      "demand_billing_mw_month": "MW·month (Σ monthly peaks)",
      "r_export_yuan":      "¥ revenue from grid export",
      "c_import_yuan":      "¥ cost of grid import"
    },
    "rl":          { /* 27 new fields */ },
    "no_battery":  { /* 27 new fields */ },
    "rule_based_tou": { /* 27 new fields */ }
  }
}
```

The `GET /runs/{run_id}/eval` REST endpoint serves `eval_results.json` verbatim — the `physical_quantities` key is passed through automatically. No serving-layer code change required. Explicit typed REST schema amendment is workstream D (serving-engineer follow-on).

---

## 7. API summary

```python
# src/energy_go/training/eval.py

def _accumulate_physical_quantities(infos) -> dict[str, float]:
    """Accumulate (N,)-shaped EnvInfo into 26 physical-quantity totals.
    Returns dict with 26 keys — all new fields except demand_billing_mw_month.
    Pure accumulation — no physics.
    """

def run_eval(
    checkpoint: "CheckpointData",
    data: object,
    params=None,
) -> PolicyEvalResult:
    """Deterministic policy rollout over 8760 steps.
    Returns extended PolicyEvalResult with 36 total fields (9 existing + 27 new).
    eval_compare wire serialization unchanged (telemetry._policy_dict uses 9 LOCKED keys).
    """
```

---

## 8. Out of scope

1. **Any changes to `EnvInfo`** — ZERO new physics, zero new env fields.
2. **eval_compare wire format** — LOCKED, NO field additions, NO version bump.
3. **REST `/eval` typed response schema amendment** — workstream D, serving-engineer follow-on.
4. **Hourly time series (8760-length arrays)** — only annual totals (scalar MWh/¥/MW·month).
5. **h2_sale, avoided_cost, token_sale streams** — v1 scope guard; additive minor-bump when their scenarios land. No zero-placeholder fields.
6. **`avoided_cost` stream** — a View-II comparison (`baseline_grid_cost − project_grid_cost`) computed from two dispatch runs in the finance engine; NOT a single EnvInfo accumulator. Out of scope.
7. **§10 E1 battery aging** — deferred per D17; wear/lifetime fields are task #57.

---

## 9. Deliberate deviations from current code

None — purely additive. The 9 LOCKED fields are computed identically to today.

---

## 10. Implementation checklist (for QA)

- [ ] `PolicyEvalResult` has exactly **36 fields** (9 existing + 27 new)
- [ ] `_accumulate_physical_quantities()` returns exactly **26 keys** (27 new − 1 derived)
- [ ] `demand_billing_mw_month` computed in `run_eval()` as `demand_charge_yuan / demand_rate`
- [ ] `run_eval()` returns extended result; the 9 existing fields are numerically unchanged
- [ ] `_policy_dict()` in `telemetry.py` is unmodified (still 9 keys, no MWh fields)
- [ ] `eval_results.json` gains `physical_quantities` top-level key with 27 fields per policy
- [ ] All 7 conservation/reconciliation identities hold in tests
- [ ] `@pytest.mark.slow` on any test that runs the full 8760-step JAX scan (D30)
- [ ] Zero placeholder fields for h2_sale/avoided_cost/token_sale
