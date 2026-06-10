---
name: validate-telemetry
description: Validate any telemetry producer or consumer against the LOCKED shared schema (contracts/shared/telemetry_schema.md v1.0.0). Use when implementing or reviewing anything that emits or reads env_step / train_metrics / eval_compare messages — env harness, training loop, serving websocket, dashboard, 3D scene.
---

# Telemetry Validation

The telemetry contract is **LOCKED** (PR #6, LINEAGE `[LOCKED] 2026-06-10`). Producers and consumers MUST conform exactly — field names, units, and the D13 additive cost identities. Deviation requires a superseding rl-architect DECISION, not a local workaround.

## What to validate

1. **Field conformance** — every emitted/read field exists in the contract with the exact name and type. No extra required fields, no renames, no unit changes (MW not kW, ¥/MWh, SOC as fraction [0,1]).
2. **D13 cost identities** (assert exactly, not approximately):
   - `cost_total_real_yuan == c_energy + c_demand_charge + c_degradation + c_curtail + c_voll`
   - `cost_total_reward_basis_yuan == c_energy + 2.0*c_demand_shape + c_degradation + c_curtail + c_voll`
   - `reward == -(cost_total_reward_basis_yuan + penalty_yuan) * 1e-5`
   - `c_import`/`r_export` are display-only decomposition of `c_energy` — never summands.
3. **Bounds** — SOC ∈ [0.2, 0.9] (D4), export ≤ site `max_export_mw` (D5), import ≤ site `max_import_mw` (D12), all values finite (contract finiteness invariant).
4. **Envelope** — message kind demuxes correctly; `seq` is run-monotonic.

## How

- If `contracts/shared/telemetry_schema.json` + validator utilities exist (task #20), use them: validate your messages in your tests and cite the validator output as evidence.
- Until then: validate by hand against the contract's **golden examples** — reproduce both golden steps and diff your emitted message field-by-field.
- Reviewers: reject any producer/consumer PR whose tests do not include at least one full-message validation against the contract (golden example or schema validator).

## Evidence format

In the PR, show: the message sample, the validation command/output, and which contract section each checked field maps to.
