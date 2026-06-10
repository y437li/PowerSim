# Canonical telemetry examples (golden fixtures)

These four messages are the **single source of golden truth** for the LOCKED telemetry contract (`../telemetry_schema.md` v1.0.0) and validate against `../telemetry_schema.json`. Producers and consumers SHOULD reuse these fixtures in their tests rather than hand-rolling new ones, so every side agrees on the same bytes.

| File | Kind | Pins |
|---|---|---|
| `env_step_a.json` | `env_step` | Golden step A — net-export, no demand activity. `c_energy = 0 − 53100 = −53100`; both cost totals `−52700`; `reward = 0.527`. Per-source conservation exact (solar 30, wind 92.5). |
| `env_step_b.json` | `env_step` | Golden step B — month-boundary, net-import. Pins the D13 split: `cost_total_real = 3 050 400` (includes the `c_demand_charge = 95 MW × 32 000`), `cost_total_reward_basis = 20 400` (uses `2.0 × c_demand_shape`, excludes the monthly charge); `reward = −0.204`. |
| `train_metrics.json` | `train_metrics` | The three reward/cost representations: `reward_scaled_mean`, `reward_norm_mean`, `cost_total_real_mean_yuan`. |
| `eval_compare.json` | `eval_compare` | Real-money basis; per policy `total_cost_yuan` = sum of the five components; SOC/penalty reported but excluded. RL ≤ both baselines. |

## Note on `env_step_b.c_demand_shape_yuan`

The value `5000.0` is an **illustrative raw** `C_DC_shape` chosen to exercise the D13 reward-basis identity (`+2.0 × 5000`); it is deliberately *not* derived from this step's `import` vs `month_peak` (backend-reviewer's non-blocking note on the lock PR). The validator checks only the cost identities, not the derivation. The real env telemetry-emit test (jax-env-engineer, task #8) MUST derive `c_demand_shape` from the §3.4 formula `demand_rate · max(0, P_import − month_peak)` rather than asserting this literal.

## Validate

```
python scripts/validate_telemetry.py --examples      # all four
python scripts/validate_telemetry.py <message.json>  # one message
```
Checks JSON-Schema conformance + D13 cost identities + per-source conservation + finiteness (per the `validate-telemetry` skill).
