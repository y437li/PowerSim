# Extended PolicyEvalResult — per-stream + physical-quantity accumulators

**Contract:** `contracts/training/eval_result_extended.md`
**Area:** training (env eval path)
**Spec:** §5.5 (eval loop), §3 (physics / EnvInfo), master plan §5.3/§5.5/§8 (finance finding)
**Decisions:** D3 (Δt=1h, 8760 eval steps), D10/D21 (demand charge booking), D13 (cost separation), D17 (no new physics), D31/F1 (constant real-price escalation at finance layer)
**Owners:** jax-env-engineer + training-engineer
**Reviewer:** backend-reviewer
**Prerequisite for:** workstream D (project finance — LCOE/LCOS/OPEX/replacement cost inputs)
**Finance input:** §5.3 rev4 (stream list + quantity requirements, finance-expert advisory)
**Architecture ruling:** rl-architect (stream-keyed structure; #82 gate)

---

## 1. Motivation and scope

Today's `PolicyEvalResult` reports only 9 fields: 5 annual cost aggregates, 1 derived total, and 3 safety/penalty metrics. This is insufficient for workstream D finance (LCOE needs generation MWh; LCOS needs battery discharge/throughput; OPEX needs grid-export/import volumes + revenue/cost; demand-charge reconciliation needs the annual peak MW).

All physical flows needed already exist in `EnvInfo` (PR #33). This contract adds **accumulation only** — zero new physics, zero new EnvInfo fields.

### Stream structure (rl-architect ruling, #82 gate)

`PolicyEvalResult` carries a **stream-keyed dict** `streams: dict[str, StreamAccumulator]` with all **6 rev4 streams pre-declared**. The goal is that when a dormant stream activates (hydrogen, token market, avoided-cost), it transitions from `{0.0, 0.0}` to `{nonzero, nonzero}` with **no structural change** — D doesn't need an eval-contract change. Fixed string keys → valid JAX pytree; accumulates under `lax.scan` cleanly.

### F1 / D31 note

All `value_yuan` accumulators are **real year-1 ¥** (constant-real-price, D31/F1). The env/eval layer applies **no escalation** — finance layer applies escalation factors post-eval.

### Sign convention

All `StreamAccumulator.value_yuan` fields store **non-negative magnitudes**. Finance applies cash-flow signs by stream type:
- **inflow (+):** `grid_export`, `h2_sale`, `token_sale`, `avoided_cost`
- **outflow (−):** `grid_import`, `demand_charge`

**Binding constraint (rl-architect, telemetry-lock owner):** the LOCKED `eval_compare` wire message does NOT gain any new fields. `_policy_dict()` in `telemetry.py` is NOT modified.

---

## 2. `StreamAccumulator` NamedTuple

Location: `src/energy_go/training/eval.py`

```python
from typing import NamedTuple

class StreamAccumulator(NamedTuple):
    """Per-stream annual accumulator for workstream D finance.

    volume:     Physical volume. Units are stream-specific (see §4 stream table).
                Always ≥ 0.
    value_yuan: Real year-1 ¥ magnitude (D31/F1 constant-real-price).
                Always ≥ 0. Sign applied by the finance layer, not here.
    """
    volume:     float
    value_yuan: float
```

---

## 3. Extended `PolicyEvalResult` dataclass

Location: `src/energy_go/training/eval.py`
Field count: **9 existing + 1 streams + 9 physical-qty + 13 per-source = 32 total**.

```python
@dataclass
class PolicyEvalResult:
    # -----------------------------------------------------------------------
    # EXISTING 9 FIELDS — WIRE-LOCKED (eval_compare payload, D13 real money)
    # _policy_dict() in telemetry.py serialises ONLY these 9 to the wire.
    # DO NOT REMOVE or RENAME any of these.
    # -----------------------------------------------------------------------
    energy_cost_yuan:     float   # Σ c_energy_yuan = c_import − r_export (D13 identity)
    demand_charge_yuan:   float   # Σ c_demand_charge_yuan (D10/D21 monthly bookings)
    degradation_yuan:     float   # Σ c_degradation_yuan
    curtailment_yuan:     float   # Σ c_curtail_yuan
    voll_yuan:            float   # Σ c_voll_yuan
    total_cost_yuan:      float   # = sum of the 5 above (real money, D13)
    soc_violations_count: int     # steps where soc_violation_mwh > 0
    soc_violation_mwh:    float   # total SOC overshoot energy (MWh)
    penalty_yuan:         float   # Σ penalty_yuan (reward-shaping; NOT in total_cost_yuan)

    # -----------------------------------------------------------------------
    # NEW: 6-stream keyed dict — all rev4 streams pre-declared (rl-architect ruling)
    # Keys (verbatim from §5.3 rev4): grid_export, grid_import, demand_charge,
    #                                  h2_sale, avoided_cost, token_sale
    # v1 active streams: grid_export, grid_import, demand_charge
    # v1 zero placeholders: h2_sale, avoided_cost, token_sale
    # -----------------------------------------------------------------------
    streams: dict  # dict[str, StreamAccumulator]

    # -----------------------------------------------------------------------
    # NEW: physical-quantity accumulators (MWh) — required by finance for
    # LCOE/LCOS/OPEX/replacement. Δt=1h (D3) → Σ p_X_mw = MWh. All ≥ 0.
    # -----------------------------------------------------------------------
    generation_mwh:       float   # Σ (p_wind_mw + p_pv_mw)  ← LCOE denominator
    wind_generated_mwh:   float   # Σ p_wind_mw
    pv_generated_mwh:     float   # Σ p_pv_mw
    bat_charge_mwh:       float   # Σ p_bat_ch_mw
    bat_discharge_mwh:    float   # Σ p_bat_dis_mw            ← LCOS denominator
    bat_throughput_mwh:   float   # Σ (p_bat_ch_mw + p_bat_dis_mw)  ← VarOM, cycle-life
    load_served_mwh:      float   # Σ p_load_served_mw
    load_unserved_mwh:    float   # Σ p_load_unserved_mw      ← INV-VOLL reliability
    curtailed_mwh:        float   # Σ p_curtailed_mw          ← INV-CURT

    # -----------------------------------------------------------------------
    # NEW: per-source flow breakdown (13 fields, MWh = MW × 1h per step)
    # Conservation identities (§3):
    #   wind_generated_mwh = wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed
    #   pv_generated_mwh   = pv_to_load   + pv_to_bat   + pv_to_grid   + pv_curtailed
    #   bat_discharge_mwh  = bat_to_load  + bat_to_grid  + bat_curtailed
    # Additional (reviewer-required, §3.6 F-IMPORT):
    #   streams["grid_import"].volume = grid_to_bat_mwh + grid_to_load_mwh
    # All ≥ 0.
    # -----------------------------------------------------------------------
    wind_to_load_mwh:     float   # Σ p_wind_to_load_mw
    wind_to_bat_mwh:      float   # Σ p_wind_to_bat_mw
    wind_to_grid_mwh:     float   # Σ p_wind_to_grid_mw
    wind_curtailed_mwh:   float   # Σ p_wind_curtailed_mw
    pv_to_load_mwh:       float   # Σ p_sol_to_load_mw
    pv_to_bat_mwh:        float   # Σ p_sol_to_bat_mw
    pv_to_grid_mwh:       float   # Σ p_sol_to_grid_mw
    pv_curtailed_mwh:     float   # Σ p_sol_curtailed_mw
    bat_to_load_mwh:      float   # Σ p_bat_to_load_mw
    bat_to_grid_mwh:      float   # Σ p_bat_to_grid_mw
    bat_curtailed_mwh:    float   # Σ p_bat_curtailed_mw
    grid_to_bat_mwh:      float   # Σ p_grid_to_bat_mw
    grid_to_load_mwh:     float   # Σ p_grid_to_load_mw
```

---

## 4. Stream table — v1 volumes and values

| stream_id | volume field | volume unit | value_yuan | value unit | v1 status |
|---|---|---|---|---|---|
| `grid_export` | Σ `p_export_mw` | MWh | Σ `r_export_yuan` | ¥ (real yr-1) | wired |
| `grid_import` | Σ `p_import_mw` | MWh | Σ `c_import_yuan` | ¥ (real yr-1) | wired |
| `demand_charge` | annual peak MW¹ | MW | Σ `c_demand_charge_yuan` | ¥ (real yr-1) | wired |
| `h2_sale` | 0.0 | MWh (future) | 0.0 | ¥ | zero placeholder |
| `avoided_cost` | 0.0 | MWh (future)² | 0.0 | ¥ | zero placeholder |
| `token_sale` | 0.0 | MWh (future) | 0.0 | ¥ | zero placeholder |

¹ `demand_charge.volume` = annual peak MW = `max(infos.c_demand_charge_yuan) / params.demand_rate_yuan_per_mw_month`. This is the **single largest monthly peak** (D31/F1 fidelity boundary: monthly granularity deferred to non-uniform escalation scenario). Reconciliation: `demand_charge.value_yuan = demand_charge.volume × demand_rate` is **not exact** (annual peak × rate ≠ Σ monthly bookings in general); the ¥ field is authoritative.

² `avoided_cost.volume` (when activated): locally served industrial load MWh; `value_yuan = served_mwh × counterfactual_import_price`. Distinct from VOLL (`voll_yuan` is penalty for *unserved* energy). Finance-expert defines the exact price basis at activation.

---

## 5. Helper functions

### `_build_streams(infos, params) → dict[str, StreamAccumulator]`

Builds the 6-stream dict. Requires `params` for `demand_charge.volume` derivation.

```python
def _build_streams(infos, params) -> dict[str, StreamAccumulator]:
    """Build the 6-key streams dict from per-step EnvInfo + EnvParams.

    demand_charge.volume = annual peak MW = max(c_demand_charge_yuan) / demand_rate.
    h2_sale / avoided_cost / token_sale = zero placeholders.
    Pure accumulation — no new physics.
    """
```

### `_accumulate_physical_quantities(infos) → dict[str, float]`

Accumulates the **22 flat physical-quantity fields** (9 aggregate + 13 per-source). Does NOT need `params`. Returns exactly 22 keys.

```python
def _accumulate_physical_quantities(infos) -> dict[str, float]:
    """Accumulate (N,)-shaped EnvInfo into 22 physical-quantity totals.
    Returns 22 keys: 9 aggregate (generation_mwh etc.) + 13 per-source.
    Pure accumulation — no physics.
    """
```

### `run_eval()` flow (post-scan)

```python
# After jax.lax.scan:
acc = _accumulate_physical_quantities(infos)     # 22 flat fields
streams = _build_streams(infos, env_params)      # 6-stream dict
# ...build existing 9 fields (unchanged)...
return PolicyEvalResult(
    # existing 9...
    streams=streams,
    **acc,
)
```

---

## 6. Conservation and reconciliation identities (must hold)

1. **Wind source conservation:**
   `wind_generated_mwh == wind_to_load_mwh + wind_to_bat_mwh + wind_to_grid_mwh + wind_curtailed_mwh`

2. **PV source conservation:**
   `pv_generated_mwh == pv_to_load_mwh + pv_to_bat_mwh + pv_to_grid_mwh + pv_curtailed_mwh`

3. **Battery discharge conservation:**
   `bat_discharge_mwh == bat_to_load_mwh + bat_to_grid_mwh + bat_curtailed_mwh`

4. **D13 cost identity:**
   `energy_cost_yuan == streams["grid_import"].value_yuan - streams["grid_export"].value_yuan`

5. **generation decomposition:**
   `generation_mwh == wind_generated_mwh + pv_generated_mwh` (exact)

6. **bat_throughput decomposition:**
   `bat_throughput_mwh == bat_charge_mwh + bat_discharge_mwh` (exact)

7. **Aggregate curtailed = Σ per-source (reviewer-required):**
   `curtailed_mwh == wind_curtailed_mwh + pv_curtailed_mwh + bat_curtailed_mwh`

8. **Grid import = to_bat + to_load (§3.6 row 9, F-IMPORT; reviewer-required):**
   `streams["grid_import"].volume == grid_to_bat_mwh + grid_to_load_mwh`

Tolerance for identities 1–3, 7–8: `atol = max(1e-3, 1e-5 × max_operand)` (float32 accumulation error over 8760 steps).
Identities 4–6: computed from the same JAX arrays — exact to float32 round-trip.

---

## 7. Wire isolation — LOCKED eval_compare unchanged

**`_policy_dict()` in `src/energy_go/training/telemetry.py` is NOT modified.**
New fields (including `streams`) are NOT serialised to the eval_compare wire.

Contract test: given a fully-populated 32-field `PolicyEvalResult`, `_policy_dict(result)` must return a dict with **exactly the 9 LOCKED keys** — no `streams` key, no MWh keys.

---

## 8. Storage — `eval_results.json` extension

```jsonc
{
  // existing eval_compare payload (LOCKED, unchanged)
  "eval_horizon_steps": 8760,
  "checkpoint_id": "...",
  "cost_basis": "real_money",
  "policies": { "rl": { /* 9 LOCKED fields */ }, ... },

  // NEW: physical quantities + streams (NOT part of eval_compare wire)
  "physical_quantities": {
    "units": {
      "*.volume (grid_export|grid_import)": "MWh",
      "*.volume (demand_charge)": "MW (annual peak)",
      "*.value_yuan": "¥ real year-1 magnitude (D31/F1)",
      "*_mwh": "MWh (Δt=1h × MW accumulated over 8760 steps)"
    },
    "rl": {
      "streams": {
        "grid_export":   {"volume": 500.0, "value_yuan": 40.0},
        "grid_import":   {"volume": 300.0, "value_yuan": 140.0},
        "demand_charge": {"volume": 100.0, "value_yuan": 3200000.0},
        "h2_sale":       {"volume": 0.0,   "value_yuan": 0.0},
        "avoided_cost":  {"volume": 0.0,   "value_yuan": 0.0},
        "token_sale":    {"volume": 0.0,   "value_yuan": 0.0}
      },
      "generation_mwh": 9050.0,
      "bat_throughput_mwh": 1630.0,
      /* ... 20 more flat physical-qty + per-source fields */
    },
    "no_battery":     { /* same shape */ },
    "rule_based_tou": { /* same shape */ }
  }
}
```

---

## 9. Out of scope

1. Any changes to `EnvInfo` — ZERO new physics.
2. `eval_compare` wire format — LOCKED, NO additions, NO version bump.
3. REST `/eval` typed response schema amendment — workstream D, serving-engineer follow-on.
4. Hourly time series (8760-length arrays) — only annual totals.
5. Monthly peak granularity for `demand_charge.volume` — D31/F1 fidelity boundary; annual peak MW is the v1 volume.
6. `h2_sale`, `avoided_cost`, `token_sale` non-zero values — additive minor-bump when their scenarios land; zero placeholders now.
7. §10 E1 battery aging — deferred per D17 (task #57).

---

## 10. Deliberate deviations from current code

None — purely additive. The 9 LOCKED fields are computed identically to today.

---

## 11. Implementation checklist (for QA)

- [ ] `StreamAccumulator` NamedTuple with `volume: float`, `value_yuan: float` in `eval.py`
- [ ] `PolicyEvalResult` has exactly **32 fields** (9 existing + 1 `streams` + 9 physical-qty + 13 per-source)
- [ ] `streams` dict has exactly the 6 rev4 keys; all 3 v1-zero placeholders present
- [ ] `demand_charge.volume` = `max(infos.c_demand_charge_yuan) / demand_rate` (annual peak MW)
- [ ] `_build_streams(infos, params)` helper: 6 keys, requires params
- [ ] `_accumulate_physical_quantities(infos)` helper: returns exactly 22 keys, no params needed
- [ ] `run_eval()` returns extended result; 9 existing fields numerically unchanged
- [ ] `_policy_dict()` in `telemetry.py` is unmodified (still 9 keys, no streams)
- [ ] `eval_results.json` gains `physical_quantities` key with `streams` sub-dict + 22 flat fields per policy
- [ ] All 8 conservation/reconciliation identities hold
- [ ] `@pytest.mark.slow` on full 8760-step JAX scan tests (D30)
- [ ] Branch rebased on main after PR #79 squash-merges
- [ ] No hardcoded Gansu constants — works for any resolved-site EnvParams
