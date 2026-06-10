# Contract: Telemetry Schema (SHARED)

- **Status:** LOCKED (PR #6, 2026-06-10) — APPROVED by backend-reviewer and frontend-reviewer. Consumers/producers implement against this; deviations require a superseding rl-architect DECISION + re-review by both reviewers (see Versioning).
- **Spec:** REBUILD_SPEC.md §2 (MDP / obs), §3 (physics & costs), §3.4 (costs), §3.5 (reward), §3.7 (tariff), §5 (training/eval), §8.5 (per-asset growth)
- **Owner:** rl-architect · **Reviewers:** backend-reviewer + frontend-reviewer
- **Area:** shared (env / training / harness / serving emit → frontend dashboard + 3D scene consume)
- **Depends on DECISIONS:** D3 (Δt=1 h), D4 (SOC 0.2–0.9), D5 (export 945 MW physics / per-site PCC cap), D6–D11 (forecast/cost fixes), D12 (import limit per-site field), D13 (real-money vs reward-basis cost split). Units below are fixed by those decisions.

## Purpose

One wire format for everything the rebuild streams out of the simulation/training/serving stack and into the React app. Three **message kinds** share an envelope so a single websocket/file consumer can demux them:

1. `env_step` — live per-step env telemetry that drives the 3D power-flow animation and the live dashboard tiles.
2. `train_metrics` — training-loop scalars for the training dashboard (loss curves, throughput, eval checkpoints).
3. `eval_compare` — end-of-eval rollup comparing the RL policy against the §5 baselines (no-battery, rule-based TOU).

This contract is the **stable boundary**: producers (JAX env harness, sbx/purejaxrl training loop, FastAPI serving) MUST emit exactly these shapes; consumers (dashboard, 3D scene) MUST read only these fields. The legacy `live_metrics.json` shape is **superseded** by `env_step` (§6 rebuild order step 6 — the contract is now this file, not the old JSON).

## Cost-accounting model (READ FIRST — resolves reviewer blockers)

Two distinct quantities exist in §3.4/§3.5 and the schema keeps them **separately named and individually reconstructable**. Conflating them was the core blocker on both advisory reviews; D13 binds the resolution.

**Real money** — actual ¥ in/out of the operation. This is what every cost dashboard, the monthly peak tracker, and the `eval_compare` headline render. Per-step additive identity:

```
cost_total_real_yuan = c_energy_yuan + c_demand_charge_yuan + c_degradation_yuan + c_curtail_yuan + c_voll_yuan
```

- `c_energy_yuan = c_import_yuan − r_export_yuan` (§3.4). `c_import`/`r_export` are a **decomposition** of `c_energy`, display-only — NOT additional summands. A consumer summing the breakdown uses `c_energy_yuan`, never the two parts.
- `c_demand_charge_yuan` is the **real monthly demand charge** `month_peak_mw × demand_rate_yuan_per_mw_month` (§3.4), booked once per calendar month (D10). Per-step it is **0 except** on a month-boundary step and the terminal flush step (D10, no double-count).
- Real money does **not** include `c_demand_shape_yuan` (a reward-shaping term, not money) and does **not** include `penalty_yuan` (a reward-shaping safety penalty, not money).

**Reward basis** — the shaped RL objective (§3.5). This drives `reward`; it is NOT money. Per-step:

```
cost_total_reward_basis_yuan = c_energy_yuan + 2.0·c_demand_shape_yuan + c_degradation_yuan + c_curtail_yuan + c_voll_yuan
reward = −(cost_total_reward_basis_yuan + penalty_yuan) · 1e-5      (§3.5)
```

- The `2.0` weight on the demand-shaping term (§3.5) is applied **by the reward, not stored pre-weighted**: `c_demand_shape_yuan` carries the **raw** `C_DC_shape`. The total above shows the weight explicitly.
- Reward basis uses the §3.4 shaping term `c_demand_shape_yuan`, NOT the real monthly `c_demand_charge_yuan`. The real monthly demand charge is absent from the reward by design (§3.5).
- `penalty_yuan` (SOC overshoot etc., D4 / §3.5) enters `reward` but is **not** part of `cost_total_reward_basis_yuan`; it is added inside the reward formula above and tracked as its own line.

`c_demand_shape_yuan` (reward-shaping term, §3.4) and `c_demand_charge_yuan` (real monthly ¥ charge, §3.4/D10) are **distinct quantities** that happen to share a stem — they are never interchangeable.

## Units (project rule — units are part of the interface)

| Quantity | Unit | Notes |
|---|---|---|
| Power flows (all `*_mw`) | **MW** | Site scale. NOT kW. Battery, PCC, per-asset flows all MW. |
| Energy / SOC capacity | **MWh** | `battery.energy_mwh`, `battery.capacity_mwh` |
| SOC | **fraction [0,1]** | unitless; bounds 0.2–0.9 (D4). NOT percent — frontend multiplies by 100 for display. |
| Prices | **¥/MWh** | buy price, sell price, feed-in. NOT ¥/kWh. |
| Costs / revenue (all `c_*`, `r_*`) | **¥** | per-step ¥ for that step (already × Δt). Cumulative variants suffixed `_cum`. Negative `cost_total_*` = net revenue. |
| Demand charge rate | **¥/MW·month** | 32 000 (§3.7); carried on the wire as `demand_rate_yuan_per_mw_month`. |
| Reward | **unitless** | post-1e-5 scaling (§3.5). |
| H₂ (Δ§8) | **kg** | electrolyzer fields, present only when composition includes one. |
| Asset power sign (Δ§8 `assets_ext.*.p_mw`) | **MW, signed** | **positive = generating/injecting** (gas turbine output), **negative = consuming/withdrawing** (electrolyzer load). Sign is per-asset and documented here, not inferred. |
| Time | **ISO-8601 UTC string** + **integer step index** | both, so frontend never does datetime math on the hot path. |

All unit conversions (MW↔kW, ¥↔display, SOC↔%) live in ONE named tested utility on each side; raw wire values are canonical per this table.

## Envelope (every message)

```jsonc
{
  "schema_version": "1.0.0",     // semver; see Versioning
  "kind": "env_step",            // "env_step" | "train_metrics" | "eval_compare"
  "ts_utc": "2026-06-10T08:00:00Z",  // EMIT/wall-clock time (when the producer sent it)
  "run_id": "string",            // ties a stream to one training/serving/eval run
  "seq": 12345,                  // strictly monotonic per (run_id, kind) across the WHOLE run; gap-detectable
  "payload": { ... }             // shape determined by `kind`
}
```

- `schema_version` is the **contract** version (this file), independent of any model/run version.
- `seq` is per `(run_id, kind)` and strictly increases by 1 across the entire run — it does **not** reset at episode boundaries and is **decoupled from the episode-local `step` index** (a run contains many episodes; D3). Gap detection = `seq` discontinuity. (Episode position is `payload.step`/`payload.episode`, NOT `seq`.)
- `ts_utc` is the **emit clock** (wall-clock send time). It is for transport/logging only. **All dashboard timelines and the 3D sim clock key off `payload.sim_time_utc` / `payload.step`, never `ts_utc`** (M3).

## Global numeric invariant

Every numeric field in every payload is **finite** — no `NaN`, `+Inf`, or `−Inf`. Producers MUST guarantee this (clip/guard before emit). Consumers MAY reject a message containing any non-finite number; a single NaN otherwise breaks chart auto-scales and the 3D flow animation.

## Kind 1: `env_step` payload — live env telemetry (drives 3D + live dashboard)

Cadence: one per env step. With Δt = 1 h (D3), wall-clock cadence is set by the serving layer's replay/realtime speed, NOT by Δt — `dt_hours` is carried so the consumer can label the sim clock.

```jsonc
{
  "step": 168,                   // env step index WITHIN the episode (NOT the envelope seq)
  "episode": 3,
  "dt_hours": 1.0,               // D3: 1 h. Carried, not assumed, by consumers.
  "sim_time_utc": "2026-03-02T08:00:00Z",  // SIM clock — all timelines key off this
  "hour_of_day": 8,              // 0–23, integer; tariff tier boundaries honor minutes
  "minute_of_hour": 0,           // 0 at Δt=1h, but field exists for a future 15-min Δt

  // --- exogenous / weather (obs base block, real values pre-noise) ---
  "wind_speed_mps": 6.4,
  "irradiance_wm2": 540.0,
  "temperature_c": 18.2,
  "load_mw": 72.5,               // total served-demand target this step (Σ load instances)

  // --- prices (¥/MWh) ---
  "price_buy_yuan_per_mwh": 620.0,
  "price_sell_yuan_per_mwh": 590.0,   // D7: spread clamped ≥0, so always ≤ price_buy
  "tariff_tier": "peak",         // "critical_peak"|"peak"|"mid"|"valley" — PRICE LABEL for THIS step only

  // --- battery state ---
  "battery": {
    "soc": 0.55,                 // fraction [0.2,0.9] (D4)
    "p_charge_mw": 0.0,          // ≥0
    "p_discharge_mw": 40.0,      // ≥0; charge XOR discharge (one is 0)
    "p_max_charge_mw": 98.16,    // §3.6 row 3 — carried so the 3D can scale the battery wire
    "p_max_discharge_mw": 98.16, // §3.6 row 3
    "soc_violation_mwh": 0.0,    // overshoot energy this step (D4 / §3.6 row 5)
    "capacity_mwh": 294.5
  },

  // --- gross generation per source (MW) — makes conservation real + lets 3D label totals ---
  "generation": {
    "gross_solar_mw": 30.0,      // §3.1 P_pv before any curtailment/dispatch
    "gross_wind_mw": 92.5        // §3.1 P_wind before any curtailment/dispatch
  },

  // --- power flows (MW) — the 3D animation reads these edge-by-edge ---
  "flows": {
    "solar_to_load_mw": 30.0,
    "solar_to_bat_mw": 0.0,
    "solar_to_grid_mw": 0.0,
    "wind_to_load_mw": 12.5,
    "wind_to_bat_mw": 0.0,
    "wind_to_grid_mw": 80.0,
    "bat_to_load_mw": 30.0,
    "bat_to_grid_mw": 10.0,
    "grid_to_load_mw": 0.0,
    "grid_to_bat_mw": 0.0,
    "solar_curtailed_mw": 0.0,   // §3.3 step 3 — per-source so conservation is verifiable
    "wind_curtailed_mw": 0.0,    // §3.3 step 3
    "bat_curtailed_mw": 0.0,
    "load_unserved_mw": 0.0      // §3.6 row 9 VOLL
  },

  // --- PCC / grid aggregates (MW) ---
  "pcc": {
    "export_mw": 90.0,           // ≤ max_export_mw for the site (D5)
    "import_mw": 0.0,            // ≤ max_import_mw for the site (D12)
    "max_export_mw": 945.0,      // D5: per-site grid_connection.max_export_mw, carried so 3D can scale the wire
    "max_import_mw": 400.0       // D12: per-site grid_connection.max_import_mw (Gansu default 400)
  },

  // --- per-step costs (¥, already × Δt). See "Cost-accounting model" for the two additive identities. ---
  "costs": {
    "c_energy_yuan": -53100.0,   // C_E = c_import − r_export (§3.4). Additive summand.
    "c_import_yuan": 0.0,        // decomposition of c_energy — display-only, NOT a summand
    "r_export_yuan": 53100.0,    // decomposition of c_energy — display-only, NOT a summand
    "c_demand_charge_yuan": 0.0, // REAL monthly charge; 0 except month-boundary/terminal step (D10). Real-money summand.
    "c_demand_shape_yuan": 0.0,  // RAW C_DC_shape reward-shaping term (§3.4); reward applies the 2.0 weight. Reward-basis only.
    "c_degradation_yuan": 400.0, // §3.4 throughput. Summand in BOTH totals.
    "c_curtail_yuan": 0.0,       // §3.4 (ren_curtailed + bat_curtailed)·800. Summand in BOTH totals.
    "c_voll_yuan": 0.0,          // §3.6 row 9. Summand in BOTH totals.
    "penalty_yuan": 0.0,         // SOC overshoot etc. (D4/§3.5). Enters reward, NOT a cost summand.
    "demand_rate_yuan_per_mw_month": 32000.0,  // §3.7 rate, carried so the peak tracker needs no hardcoded constant
    "cost_total_real_yuan": -52700.0,         // = c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
    "cost_total_reward_basis_yuan": -52700.0  // = c_energy + 2.0·c_demand_shape + c_degradation + c_curtail + c_voll
  },
  "cost_cum": {                  // running EPISODE totals (¥); cum of the per-step set above
    "c_energy_yuan_cum": 0.0,
    "c_demand_charge_yuan_cum": 0.0,  // D10: steps once at each month boundary; equals Σ per-step c_demand_charge_yuan
    "c_demand_shape_yuan_cum": 0.0,
    "c_degradation_yuan_cum": 0.0,
    "c_curtail_yuan_cum": 0.0,
    "c_voll_yuan_cum": 0.0,
    "penalty_yuan_cum": 0.0,
    "cost_total_real_yuan_cum": 0.0,
    "cost_total_reward_basis_yuan_cum": 0.0
  },

  "month_peak_mw": 95.0,         // current calendar-month max import (¥/MW·month basis)
  "reward": 0.527,               // = −(cost_total_reward_basis_yuan + penalty_yuan)·1e-5 (§3.5)

  // --- Δ§8 OPTIONAL blocks: present iff the composition includes the asset type ---
  "assets_ext": {
    "gas": [ { "id": "gt_1", "p_mw": 0.0, "c_fuel_yuan": 0.0, "setpoint": 0.0 } ],
    "electrolyzer": [ { "id": "pem_1", "p_mw": -5.0, "h2_kg": 90.9,
                        "h2_level_kg": 1200.0, "tank_kg": 2000.0,
                        "r_h2_yuan": 2727.0, "setpoint": 0.25 } ]
  }
}
```

### Golden step A (reproduced above — net-export, no demand activity)
- `c_energy = c_import − r_export = 0 − 53100 = −53100`. (`r_export = 90 MW × 1 h × 590 ¥/MWh = 53 100`.)
- `cost_total_real = −53100 + 0 + 400 + 0 + 0 = −52700`.
- `cost_total_reward_basis = −53100 + 2.0·0 + 400 + 0 + 0 = −52700`.
- `reward = −(−52700 + 0)·1e-5 = 0.527`.

### Golden step B (month-boundary; demand-shape active — pins the 2.0 weight and the real/reward divergence)
```jsonc
"costs": {
  "c_energy_yuan": 10000.0,       // c_import 10000 − r_export 0
  "c_import_yuan": 10000.0,
  "r_export_yuan": 0.0,
  "c_demand_charge_yuan": 3040000.0,  // month boundary: month_peak 95 MW × 32000 ¥/MW·month
  "c_demand_shape_yuan": 5000.0,      // raw C_DC_shape
  "c_degradation_yuan": 400.0,
  "c_curtail_yuan": 0.0,
  "c_voll_yuan": 0.0,
  "penalty_yuan": 0.0,
  "demand_rate_yuan_per_mw_month": 32000.0,
  "cost_total_real_yuan": 3050400.0,        // 10000 + 3040000 + 400 + 0 + 0
  "cost_total_reward_basis_yuan": 20400.0   // 10000 + 2.0·5000 + 400 + 0 + 0
}
// reward = −(20400 + 0)·1e-5 = −0.204
```
This step proves: (i) the reward applies `2.0×` to demand-shape (20400 uses `2·5000`, not `5000`); (ii) the real total includes the monthly demand charge while the reward-basis total excludes it; (iii) `c_demand_shape` ≠ `c_demand_charge`.

Frontend/3D commitments:
- The 3D scene animates **only** `flows.*` edges + `pcc.*` + `battery.soc`; it must not infer flows it can't see. Every flow edge it draws maps to one field above.
- `flows` + `generation` satisfy **per-source** energy conservation each step (§3.6 row 14), now verifiable because gross is on the wire:
  - solar: `solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed == gross_solar_mw`
  - wind:  `wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == gross_wind_mw`
  within float tolerance — producer asserts this; consumer may assert in tests but must not crash on float tolerance.
- TOU band geometry (C1): per-step `tariff_tier` is the correct **price label for that step**, but it is **NOT** band geometry. At Δt=1 h steps land on `:00` (D8) while the critical-peak window is **10:30–11:30** (§3.7) — never aligned to an hourly step, so reconstructing band edges from `tariff_tier` mislabels the band as 11:00–12:00. TOU band edges MUST be read from the static §3.7 tariff schedule (a shared tariff config the dashboard holds), not derived from the `tariff_tier` stream.
- Optional `assets_ext` blocks are **absent** (not null) for the Gansu parity config (§8.4). Consumers feature-detect by key presence.

## Kind 2: `train_metrics` payload — training scalars

Cadence: every N gradient steps (producer config; default every 1000), plus one on each eval checkpoint.

```jsonc
{
  "global_step": 250000,         // env steps consumed
  "wall_seconds": 184.2,
  "env_steps_per_sec": 1.35e6,   // throughput (§7 target 1e6–1e7)
  "actor_loss": 0.42,
  "critic_loss": 1.31,
  "ent_coef": 0.18,              // ent_coef="auto" (§5)
  "reward_scaled_mean": 0.61,    // batch mean of the ×1e-5-scaled env reward (same basis as env_step.reward); unitless
  "reward_norm_mean": 0.83,      // VecNormalize-normalized reward seen by the optimizer (§5 norm_reward=True during training); null on eval checkpoints (eval is unnormalized)
  "cost_total_real_mean_yuan": -61000.0,  // mean per-episode REAL-money cost (negative = net revenue); this is the ¥ number, explicitly a cost not a reward
  "is_eval_checkpoint": false,
  "checkpoint_id": null          // set when a checkpoint is written; ties to checkpoint contract
}
```

- Three distinct reward/cost representations each have an unambiguous home: `reward_scaled_mean` (×1e-5 scaled, matches the per-step `reward`), `reward_norm_mean` (VecNormalize-normalized, training-only, `null` at eval), and `cost_total_real_mean_yuan` (real money, named as a cost so its sign is never mistaken for a reward). These are independent aggregates and need not be exact negatives of one another (penalties and the real-vs-reward basis differ).

## Kind 3: `eval_compare` payload — RL vs baselines

Cadence: once per full 365-day eval (§5). One message carries all policies. **Basis: real money** — every ¥ field here is real-money (the `cost_total_real_yuan` basis), so RL-vs-baseline is apples-to-apples.

```jsonc
{
  "eval_horizon_steps": 8760,    // D3: 8760 at Δt=1h
  "checkpoint_id": "string",
  "cost_basis": "real_money",    // explicit: all *_yuan fields below are real money, not reward-basis
  "policies": {
    "rl": {
      "energy_cost_yuan": 0,
      "demand_charge_yuan": 0,
      "degradation_yuan": 0,
      "curtailment_yuan": 0,
      "voll_yuan": 0,
      "total_cost_yuan": 0,         // == energy_cost + demand_charge + degradation + curtailment + voll (real money)
      "soc_violations_count": 0,    // safety metric, NOT in total_cost_yuan
      "soc_violation_mwh": 0.0,     // safety metric, NOT in total_cost_yuan
      "penalty_yuan": 0.0           // reward-basis penalty total, reported for transparency, NOT in total_cost_yuan
    },
    "no_battery":     { /* same keys */ },
    "rule_based_tou": { /* same keys */ }
  }
}
```

- Additive identity (per policy): `total_cost_yuan = energy_cost_yuan + demand_charge_yuan + degradation_yuan + curtailment_yuan + voll_yuan`. The SOC penalty/violations are reward-shaping safety metrics and are **excluded** from `total_cost_yuan` (so the comparison is real money); they are reported alongside so a policy that "wins" on cost while violating SOC is visible.
- Acceptance: RL `total_cost_yuan` must be ≤ both baselines or the run is flagged (§5 "must beat these"). The frontend renders this as the headline comparison.

## Machine-readable schema (v1.0.0, task #20)

This prose contract has a machine-readable companion derived from it — **additive, no field change** (the wire format and `schema_version` stay `1.0.0`):

- **`telemetry_schema.json`** (this directory) — JSON Schema (draft 2020-12) for the envelope + all three payload kinds: field names, types, enums, required lists, and bounds (SOC `[0.2,0.9]`, non-negative flows/prices, `cost_basis` const). `additionalProperties` is `true` everywhere to honor the minor-forward-compat rule above, so a higher-minor message still validates; the required lists guarantee no LOCKED field is dropped or renamed.
- **`telemetry_examples/`** — the canonical golden fixtures (`env_step_a`, `env_step_b`, `train_metrics`, `eval_compare`). The single source of golden truth; see its `readme.md`.
- **`scripts/validate_telemetry.py`** — reference validator: JSON-Schema conformance **plus** the checks JSON Schema can't express — the D13 cost identities, per-source energy conservation, and finiteness. CI validates the golden examples on every PR.

**Producer/consumer obligation:** every producer (env harness, training loop, serving) and consumer (dashboard, 3D scene) MUST validate its emitted/consumed messages against `telemetry_schema.json` in its tests (reuse the `telemetry_examples/` fixtures), and cite the validator output as evidence (per the `validate-telemetry` skill). The importable validator utilities — Python `energy_go.telemetry.validate` and the frontend TS module — are delegated implementation tasks that wrap this same schema + examples.

## Versioning

- `schema_version` is **semver on this contract**:
  - **patch** — doc clarification, no field change.
  - **minor** — additive only (new optional field / new `assets_ext` asset type / new optional kind). Consumers MUST ignore unknown fields; producers MUST NOT remove or retype fields in a minor bump.
  - **major** — any field removal/rename/retype or unit change. Requires a superseding rl-architect DECISION and re-review by both reviewers.
- Consumers MUST reject a message whose major version exceeds the one they were built against, and SHOULD warn-and-continue on a higher minor.
- The Δ§8 `assets_ext` growth (§8.5) is a **minor** bump path by design — adding gas/electrolyzer fields never breaks the Gansu parity consumer.

## Out of scope (fidelity boundary — §3.6 "Not modeled")

No ramp-rate (except gas, Δ§8), no line/transformer losses, no reactive power/voltage, no calendar aging, no frequency services. Telemetry carries only what the env computes; the schema does not invent fields for unmodeled physics. Adding any requires a spec change first, then a minor/major bump here.

## Acceptance criteria (for the eventual implementation, post-lock)

- A golden `env_step` message validates against this schema and round-trips producer→JSON→consumer with no field loss.
- Units test: golden steps A and B with hand-computed values (arithmetic shown above) match §3.4 numbers in ¥ and MW exactly, including `c_energy = c_import − r_export`, the two cost totals, and `reward`.
- Two-totals test: step B pins `cost_total_reward_basis_yuan` using the `2.0×` demand-shape weight and the exclusion of `c_demand_charge_yuan`; `cost_total_real_yuan` pins inclusion of the monthly demand charge.
- Cumulative test: for every per-step line X, `Σ(c_X_yuan over steps) == c_X_yuan_cum` (including `c_demand_charge` whose per-step value is 0 except month-boundary steps, D10); `cost_total_real_yuan_cum` and `cost_total_reward_basis_yuan_cum` match their cumulated summands.
- Conservation test: per-source `to_load+to_bat+to_grid+curtailed == gross_*_mw` for solar and wind on a golden step, using the `generation.*` gross fields.
- Finiteness test: a message with a `NaN`/`Inf` in any numeric field is rejected by the consumer.
- TOU geometry test: critical-peak band is drawn 10:30–11:30 from the static tariff schedule, NOT 11:00–12:00 from the `tariff_tier` stream.
- Versioning test: a consumer built for 1.0.0 ignores an injected unknown field (minor-forward-compat) and rejects a `2.0.0` message.
- `eval_compare` test: per policy, the five ¥ components sum to `total_cost_yuan`; SOC/penalty metrics are present and excluded from the total.
- Gansu config: `assets_ext` key is absent; adding a gas asset makes it present without changing any existing field.
