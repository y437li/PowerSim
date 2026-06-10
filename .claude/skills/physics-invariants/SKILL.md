---
name: physics-invariants
description: Run the Energy GO physics invariant battery — energy conservation, D13 cost identities, physical bounds, fixed-seed determinism. Use when implementing, reviewing, or QA-verifying any env physics code (reference implementation, JAX core).
---

# Physics Invariant Battery

Every env-physics PR must pass this battery in addition to its contract tests. "Tests pass" without these invariants is not acceptance — these are the laws the spec guarantees regardless of scenario.

## The invariants

1. **Per-source energy conservation** (§3 power balance), each step:
   - `wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == p_wind_mw`
   - same identity for solar; battery: `SOC_{t+1} == SOC_t + (η_ch·P_ch − P_dis/η_dis)·Δt / capacity` exactly at every step.
2. **D13 cost identities** — both additive totals reconstruct exactly from their components (see validate-telemetry skill §2).
3. **Physical bounds, never violated post-enforcement** (§3.6 order): SOC ∈ [0.2, 0.9] (D4; overshoot must appear in `soc_violation_mwh`, not in SOC), export ≤ 945 MW Gansu default (D5), import ≤ 400 MW (D12), all flows ≥ 0.
4. **Constraint enforcement order** is §3.6's: parse/clip actions → battery/SOC → cap flows-to-load → PCC export → grid import → costs. Spot-check with a scenario that triggers ≥2 constraints simultaneously.
5. **Fixed-seed determinism** — same seed ⇒ bit-identical trajectory (JAX: identical across jit/no-jit and under vmap).

## How

- Use the shared helpers (`assert_energy_conserved`, `assert_cost_identities`, `assert_physical_bounds`, determinism harness — task #21) once they land; until then assert these inline with hand-computed expected numbers and the arithmetic in a comment (project rule).
- Run on: the golden examples, a full 168-step episode with random actions (fixed seed), and the boundary scenarios (SOC pinned at 0.2 and 0.9, export-limit-binding hour, month boundary for the demand charge per D10).

## Evidence format

Paste the pytest output of the invariant tests plus the seed(s) used. A QA verdict citing this battery must list which invariants ran on which scenarios.
