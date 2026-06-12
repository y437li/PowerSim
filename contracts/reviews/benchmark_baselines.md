# Review record — `contracts/training/benchmark_baselines.md` (PR #76, task #51)

**Reviewer:** backend-reviewer
**Feature:** §11 benchmark baselines — greedy myopic, DP oracle, MPC
**Tests:** `tests/training/test_training_benchmark_baselines.py`

## Stage 1 — contract + tests gate: APPROVE @ 3fefed0

### Verified against jax_env (re-derived, not trusted)
- **Section B hand-arithmetic** (greedy 1-step, load=200, soc=0.6, h=0 valley):
  discharge `max_P_dis=(soc−soc_min)·cap·eta_dis=(0.6−0.2)·294.5·0.97=114.27`, capped to
  `bat_power 98.16` (jax_env.py L337); `P_import=200−98.16=101.84`; `PRICE_TABLE_YPW[0]=250`
  (L20) → `energy=250·101.84=25,460 ¥`; `C_deg=c_deg·(ch+dis)=10·98.16=981.6 ¥` (L468);
  `total=26,441.6 ¥`. All exact. ✓
- **§3.1 greedy fractions**: `f_wl=f_sl=1` in the surplus case correctly **exports** the
  load-capped surplus — jax_env STEP 5 computes `P_wind_to_grid = P_wind − wind_to_load −
  wind_to_bat` (leftover after the load cap, L398), NOT the `(1−f_wl−f_wb)` remainder. ✓
- **Invariants I1–I5** well-defined. I1/I2 (`dp_oracle ≤ greedy`/`tou`) full-year tolerance
  set to `150_000 ¥` ≥ the derived §3.2 discretization bound (~110k); the 3-step exact DP
  test keeps `+1e-3`. ✓
- **Slow-marking complete**: all `run_benchmark`/DP/MPC tests (incl. Section B single-step,
  which JIT-compiles even at episode_len=1) are `@pytest.mark.slow`; `TestGreedyPolicyAction`
  (only `policy.action()`) stays fast. ✓
- **Telemetry (§11.5)**: `eval_compare.policies` has `additionalProperties: true`, so the new
  `greedy`/`dp_oracle`/`mpc` keys are an additive minor bump; Section G tests run `validate()`. ✓

### Reviewer-added cases (2, `# reviewer:`, hand-derived)
- `test_discharge_soc_limited_not_power_limited` — soc=0.25 → `max_P_dis=14.283 MW < bat_power`,
  the SOC-limited branch of `P_dis_max`; `a_bat=−0.1455`.
- `test_deficit_exactly_bat_power_full_discharge` — deficit==98.16==bat_power → `a_bat=−1.0`.
(Both deleted by c5de350 and restored @ 8ee09f5.)

**Approved suite = developer's 35 + reviewer's 2 = 37.** Implementation pending; this is the
contract+tests gate only.

### Process note
Reviewer cases were dropped twice during fixes (c5de350); restored. Pre-push
`git diff <prior-HEAD>..HEAD` adopted to prevent recurrence.
