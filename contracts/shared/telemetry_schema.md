# Contract: Telemetry Schema (SHARED)

- **Status:** DRAFT — requires APPROVE from BOTH backend-reviewer and frontend-reviewer before it can be LOCKED. Do not implement producers/consumers against it until locked.
- **Spec:** REBUILD_SPEC.md §2 (MDP / obs), §3 (physics & costs), §3.4 (costs), §3.5 (reward), §3.7 (tariff), §5 (training/eval), §8.5 (per-asset growth)
- **Owner:** rl-architect · **Reviewers:** backend-reviewer + frontend-reviewer
- **Area:** shared (env / training / harness / serving emit → frontend dashboard + 3D scene consume)
- **Depends on DECISIONS:** D3 (Δt=1 h), D4 (SOC 0.2–0.9), D5 (export 945 MW physics / per-site PCC cap), D6–D11 (forecast/cost fixes). Units below are fixed by those decisions.

## Purpose

One wire format for everything the rebuild streams out of the simulation/training/serving stack and into the React app. Three **message kinds** share an envelope so a single websocket/file consumer can demux them:

1. `env_step` — live per-step env telemetry that drives the 3D power-flow animation and the live dashboard tiles.
2. `train_metrics` — training-loop scalars for the training dashboard (loss curves, throughput, eval checkpoints).
3. `eval_compare` — end-of-eval rollup comparing the RL policy against the §5 baselines (no-battery, rule-based TOU).

This contract is the **stable boundary**: producers (JAX env harness, sbx/purejaxrl training loop, FastAPI serving) MUST emit exactly these shapes; consumers (dashboard, 3D scene) MUST read only these fields. The legacy `live_metrics.json` shape is **superseded** by `env_step` (§6 rebuild order step 6 — the contract is now this file, not the old JSON).

## Units (project rule — units are part of the interface)

| Quantity | Unit | Notes |
|---|---|---|
| Power flows (all `*_mw`) | **MW** | Site scale. NOT kW. Battery, PCC, per-asset flows all MW. |
| Energy / SOC capacity | **MWh** | `battery.energy_mwh`, `battery.capacity_mwh` |
| SOC | **fraction [0,1]** | unitless; bounds 0.2–0.9 (D4). NOT percent — frontend multiplies by 100 for display. |
| Prices | **¥/MWh** | buy price, sell price, feed-in. NOT ¥/kWh. |
| Costs / revenue (all `c_*`, `r_*`) | **¥** | per-step ¥ for that step (already × Δt). Cumulative variants suffixed `_cum`. |
| Demand charge rate | **¥/MW·month** | 32 000 (§3.7). |
| Reward | **unitless** | post-1e-5 scaling (§3.5). Raw ¥ also provided as `cost_total_yuan`. |
| H₂ (Δ§8) | **kg** | electrolyzer fields, present only when composition includes one. |
| Time | **ISO-8601 UTC string** + **integer step index** | both, so frontend never does datetime math on the hot path. |

All unit conversions (MW↔kW, ¥↔display, SOC↔%) live in ONE named tested utility on each side; raw wire values are canonical per this table.

## Envelope (every message)

```jsonc
{
  "schema_version": "1.0.0",     // semver; see Versioning
  "kind": "env_step",            // "env_step" | "train_metrics" | "eval_compare"
  "ts_utc": "2026-06-10T08:00:00Z",
  "run_id": "string",            // ties a stream to one training/serving/eval run
  "seq": 12345,                  // monotonic per (run_id, kind); gap-detectable
  "payload": { ... }             // shape determined by `kind`
}
```

- `schema_version` is the **contract** version (this file), independent of any model/run version.
- `seq` is per kind so a consumer can detect drops; `env_step.seq` equals the env step index within the episode.

## Kind 1: `env_step` payload — live env telemetry (drives 3D + live dashboard)

Cadence: one per env step. With Δt = 1 h (D3), wall-clock cadence is set by the serving layer's replay/realtime speed, NOT by Δt — `dt_hours` is carried so the consumer can label the sim clock.

```jsonc
{
  "step": 168,                   // env step index in episode (== seq)
  "episode": 3,
  "dt_hours": 1.0,               // D3: 1 h. Carried, not assumed, by consumers.
  "sim_time_utc": "2026-03-02T08:00:00Z",
  "hour_of_day": 8,              // 0–23, integer; tariff tier boundaries honor minutes
  "minute_of_hour": 0,           // 0 at Δt=1h, but field exists for a future 15-min Δt

  // --- exogenous / weather (obs base block, real values pre-noise) ---
  "wind_speed_mps": 6.4,
  "irradiance_wm2": 540.0,
  "temperature_c": 18.2,
  "load_mw": 72.5,               // total served-demand target this step (Σ load instances)

  // --- prices (¥/MWh) ---
  "price_buy_yuan_per_mwh": 620.0,
  "price_sell_yuan_per_mwh": 590.0,   // D11: spread clamped ≥0, so always ≤ price_buy
  "tariff_tier": "peak",         // "critical_peak"|"peak"|"mid"|"valley" (§3.7)

  // --- battery state ---
  "battery": {
    "soc": 0.55,                 // fraction [0.2,0.9] (D4)
    "p_charge_mw": 0.0,          // ≥0
    "p_discharge_mw": 40.0,      // ≥0; charge XOR discharge (one is 0)
    "soc_violation_mwh": 0.0,    // overshoot energy this step (D4 / §3.6 row 5)
    "capacity_mwh": 294.5
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
    "ren_curtailed_mw": 0.0,     // §3.3 step 3 curtailment
    "bat_curtailed_mw": 0.0,
    "load_unserved_mw": 0.0      // §3.6 row 9 VOLL
  },

  // --- PCC / grid aggregates (MW) ---
  "pcc": {
    "export_mw": 90.0,           // ≤ max_export_mw for the site (D5)
    "import_mw": 0.0,            // ≤ max_import_mw (400 MW Gansu)
    "max_export_mw": 945.0,      // D5: site PCC cap, carried so 3D can scale the wire
    "max_import_mw": 400.0
  },

  // --- per-step costs (¥, already × Δt) and cumulative (¥) ---
  "costs": {
    "c_energy_yuan": 0.0,        // C_E = C_import − R_export (§3.4)
    "c_import_yuan": 0.0,
    "r_export_yuan": 53100.0,
    "c_demand_shape_yuan": 0.0,  // incremental shaping term (§3.4); see month_peak
    "c_degradation_yuan": 400.0, // §3.4 throughput
    "c_curtail_yuan": 0.0,
    "c_voll_yuan": 0.0,
    "penalty_yuan": 0.0,         // SOC overshoot etc. (§3.5)
    "cost_total_yuan": -52700.0  // signed ¥ that feeds reward (negative = net revenue)
  },
  "cost_cum": {                  // running episode totals (¥), for dashboard rollup
    "c_energy_yuan_cum": 0.0,
    "c_demand_charge_yuan_cum": 0.0,  // D10: booked once at month end; no terminal double-count
    "c_degradation_yuan_cum": 0.0,
    "c_curtail_yuan_cum": 0.0,
    "c_voll_yuan_cum": 0.0
  },

  "month_peak_mw": 95.0,         // current calendar-month max import (¥/MW·month basis)
  "reward": 0.527,               // scaled (×1e-5) per §3.5

  // --- Δ§8 OPTIONAL blocks: present iff the composition includes the asset type ---
  "assets_ext": {
    "gas": [ { "id": "gt_1", "p_mw": 0.0, "c_fuel_yuan": 0.0, "setpoint": 0.0 } ],
    "electrolyzer": [ { "id": "pem_1", "p_mw": -5.0, "h2_kg": 90.9,
                        "h2_level_kg": 1200.0, "tank_kg": 2000.0,
                        "r_h2_yuan": 2727.0, "setpoint": 0.25 } ]
  }
}
```

Frontend/3D commitments:
- The 3D scene animates **only** `flows.*` edges + `pcc.*` + `battery.soc`; it must not infer flows it can't see. Every flow edge it draws maps to one field above.
- `flows` satisfies per-source energy conservation each step (§3.6 row 14): for each source, `to_load+to_bat+to_grid+curtailed == gross_source_mw` within tolerance — producer asserts this; consumer may assert in tests but must not crash on float tolerance.
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
  "reward_mean": 0.61,           // batch mean of scaled reward
  "reward_unnorm_mean_yuan": -61000.0, // eval-env reward is unnormalized (§5)
  "is_eval_checkpoint": false,
  "checkpoint_id": null          // set when a checkpoint is written; ties to checkpoint contract
}
```

## Kind 3: `eval_compare` payload — RL vs baselines

Cadence: once per full 365-day eval (§5). One message carries all policies.

```jsonc
{
  "eval_horizon_steps": 8760,    // D3: 8760 at Δt=1h
  "checkpoint_id": "string",
  "policies": {
    "rl":            { "energy_cost_yuan": 0, "demand_charge_yuan": 0,
                       "degradation_yuan": 0, "curtailment_yuan": 0,
                       "voll_yuan": 0, "soc_violations_count": 0,
                       "total_cost_yuan": 0 },
    "no_battery":    { /* same keys */ },
    "rule_based_tou":{ /* same keys */ }
  }
}
```

Acceptance: RL `total_cost_yuan` must be ≤ both baselines or the run is flagged (§5 "must beat these"). The frontend renders this as the headline comparison.

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
- Units test: a flows/cost message with hand-computed values (arithmetic shown) matches §3.4 numbers in ¥ and MW exactly.
- Conservation test: per-source `to_load+to_bat+to_grid+curtailed == gross` for a golden step.
- Versioning test: a consumer built for 1.0.0 ignores an injected unknown field (minor-forward-compat) and rejects a `2.0.0` message.
- Gansu config: `assets_ext` key is absent; adding a gas asset makes it present without changing any existing field.
