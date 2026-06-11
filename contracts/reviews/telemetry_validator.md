# Review Record: frontend/telemetry_validator (contract + tests gate)

- **PR:** #27 (`feat/frontend-telemetry-validator`, task #24) · **Reviewer:** frontend-reviewer
- **Date:** 2026-06-10 · **Stage:** 1 · **Verdict:** REQUEST_CHANGES

## Findings (blockers first)
1. **[blocker] eval_compare cost identity not validated.** §4 runs D13 (`checkD13Identities`) on env_step only; eval_compare is checked for golden-pass + missing-policies but NOT for the per-policy additive identity `total_cost_yuan == energy+demand_charge+degradation+curtailment+voll`. A broken eval total passes validation and mislabels the headline best-policy. Add a pipeline step + helper + error code `eval_total:<policy>:<delta>` (tol ≤ 1.0 ¥). Reviewer test pushed.
2. [should] §8 finiteness wording — "arrays not checked" means NaN/Inf inside `assets_ext.gas[]` / `electrolyzer[]` would be missed. Either recurse array elements or state assets_ext finiteness is out of scope v1.
3. [nit] §4.4 forward-compat warning fires for major=1 & minor>0; confirm a `1.0.x` patch produces no warning (intended).

## Good (no change)
- D13 §6 identities all correct vs locked schema (real / reward-basis with 2.0× shape / c_energy=c_import−r_export / reward formula), tolerances sane.
- Per-source conservation §7 correct (0.001 MW tol). Version handling, error-code catalogue, finiteness path reporting, Zod payload conformance, golden-fixture pass all well specified and tested.

## Reviewer-added tests (`// reviewer:`)
1. eval_compare policy with `total_cost_yuan` off by 1000 → `ok:false` (`eval_total…`)
2. golden eval_compare still passes (no false positive)

Approved suite = author cases + these 2. Re-request when finding 1 lands.
