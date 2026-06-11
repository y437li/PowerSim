# Review record: Reference Implementation (Gansu) + Physics Invariant Helpers

- **Contract:** `contracts/env/reference_implementation.md`
- **Tests:** `tests/env/test_env_reference_implementation.py`, `tests/env/test_env_parity_gansu.py`
- **Helpers:** `src/energy_go/testing/invariants.py` (task #21)
- **Spec:** REBUILD_SPEC.md §2.1–§2.2, §3.1–§3.7, §4.1–§4.2, §6
- **Decisions:** D3, D4, D5, D6–D10, D11, D12, D13, **D19** (load ×100)
- **PR:** #14 (`feat/env-reference-implementation`) — tasks #5 + #21
- **Reviewer:** backend-reviewer
- **Verdict:** **APPROVE** — 2026-06-10 (commit 9adfced, + reviewer commit)
  - R1 (ac3bc32→a0050be): REQUEST_CHANGES — B1–B4 + M1–M6.
  - R2/R3 (845ff5d): B1, B3, M1–M6 resolved; new C1 (self-test fixture) + B4/D19 citation + STEP 10/11 ordering raised.
  - R4 (b7ac172): C1 fixed, D19 cited, B3-minor (per-source curtailment) fixed.
  - R4b (09c99c0): STEP 10/11 ordering fixed (10a/10b/10c) + assert_cost_identities at the M1 boundary step → APPROVE.

## Round-4 verification (all hand-derived)

- **C1 (self-test fixture)** — FIXED. `_make_good_result` now sets `p_import_mw=0.0` (pure wind-export step): c_import=0, c_energy=−17247.12, cost_total_real=cost_total_reward_basis=−17247.12, reward=+0.1724712. Grid-import decomp `0+0==0` now passes; identity 10 `c_import==250×0==0` consistent.
- **B4 / D19** — RESOLVED. Contract §4.2 cites D19 (×100, base 75 MW; α=4500, β=3750, σ=5000 kW); the round-2 tentative flag is removed.
- **B3-minor** — FIXED. STEP 7 derives `wind/solar/bat_curtailed_mw` per-source from pre-curtailment grid flows; STEP 10 `C_curtail` uses the three-source sum (no `ren_curtailed_mw` alias). M4 now also asserts the proportional split.
- **B1 / M1 / M2 / M3 / M5 / M6** — verified correct in R2/R3 (c_demand_charge field; 80×32000=2,560,000 at t=743; Σ=4,480,000 two-month; soc_violation 95.2152 MWh / penalty 1,904,304 ¥; import-shed branch). Arithmetic re-derived, all correct.
- Invariant helpers (task #21): `assert_energy_conserved` (per-source ==, grid-import decomp), `assert_cost_identities` (D13 identities 1–10, opt-in formula checks), `assert_physical_bounds` (D4/D5/D12 + price_sell∈[0,price_buy]), `assert_soc_dynamics`, `assert_demand_charge_timing` (D10), determinism + episode runners. Battery = invariants 1–5 (inv-6 removed per PR #18). Sound.

## Reviewer-added case (pushed this round, `# reviewer:`)

`test_d13_boundary_divergence_real_vs_reward_basis` — the locked round-4 D13 check (endorsed by rl-architect). M3 verified `cost_total_real` *includes* the monthly charge, but no test verified `cost_total_reward_basis` *excludes* it at a boundary. At t=743 (Jan→Feb), month_peak=80, load=0, no RE/battery → import=0:
- c_energy=0; c_demand_charge=80×32000=**2,560,000**; c_demand_shape=32000·max(0,0−80)=**0**.
- `cost_total_real==2,560,000` (includes monthly charge); `cost_total_reward_basis==0` (excludes it); divergence == `c_demand_charge_yuan`; reward==0.
This isolates the real-vs-reward divergence purely to `c_demand_charge` inclusion/exclusion (cleaner than telemetry golden-B's hardcoded shape value). The approved suite = developer cases (incl. dev-authored M1–M6) + this case.

## STEP 10/11 ordering — RESOLVED in 09c99c0

Contract STEP 10 was restructured into 10a (intermediate cost components) → 10b (month-boundary
detection + `c_demand_charge_yuan`, formerly STEP 11) → 10c (the two totals). `cost_total_real`
now uses `c_demand_charge_yuan` (defined above it); the undefined `monthly_demand_charge_this_step`
placeholder is gone. §3.6 physical order (export→import→costs) untouched. Verified.

The dev also added `assert_cost_identities(result, PARAMS)` at the M1 boundary step (t=743,
c_demand_charge=2,560,000 ≠ 0): identity 3 pins `cost_total_real` INCLUDING the charge, and
identity 2 pins `cost_total_reward_basis` == the formula WITHOUT the charge (so excluding it).
That satisfies the locked round-4 D13-divergence condition; my reviewer case below is a
complementary explicit value-pin.

## Notes
- `validate-telemetry` N/A (reference is a test fixture, not a telemetry producer); `physics-invariants` battery (1–5) IS contracted here via the task #21 helpers — satisfied.

## Post-merge-review: team-lead blocker + D21 (commit 9adfced)
team-lead's independent review found real-money c_demand_charge never books for a truncated mid-month training episode. Scoped (backend-reviewer): real-money/eval ONLY — reward uses 2·c_demand_shape every step (L513), c_demand_charge stays out of cost_total_reward_basis (D13). rl-architect ruled **D21**: terminal flush = year-end (full-year horizon), NOT per-episode → impl conformant, no signature change.
Resolved in 9adfced + reviewer tests:
- D21 cite at contract line 450; gate test `test_truncated_episode_books_zero_demand_charge` (t=100..267 ⊂ Jan, no boundary → Σ c_demand_charge==0). Verified: Σ==0.
- D6 forecast-price clip ≥0 via `_noised_feature` helper (structural). Tests `test_noised_feature_clips_to_floor` (seed-independent: 250·(1−2)=−250→0; 250·1.2=300) + `test_forecast_price_obs_nonnegative` (σ=2.0/seed=999 → all≥0, 4 clip events, non-vacuous). Note: clipped to ≥0 (universal physical floor) rather than the site-specific tariff band [250,780] — more general for the reusable helper; accepted.
- SOC penalty rate parameterized → GansuParams.soc_penalty_yuan_per_mwh (single source; env + invariants read it). Tautology resolved.
Full env suite: 128 passed + 3 reviewer tests = 131 passed / 9 skipped. APPROVE restored.
