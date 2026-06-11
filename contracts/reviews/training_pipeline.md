# Review record — `contracts/training/training_pipeline.md`

**Reviewer:** backend-reviewer · **Area:** training · **PR:** #40 (`feat/training-pipeline`)
**Stage:** contract + tests gate (Stage 1, draft PR)

## Verdict: APPROVE (round-2, commit d9dade1)

Approved suite = developer cases + the reviewer-added cases below.

## Round history

- **Round 1** (e472cae) — REQUEST_CHANGES. Blocker **B1**: action space was 1-dim (battery only), contradicting spec §2.1/§2.2 ("6-dim continuous" Energy Router) and the locked `jax_env_core` §5.3.2. Cascaded through actor (Dense(2)), critic (108), target_entropy (−1), and scalar baselines (incl. the VOLL-dominated "meaningless NoBattery" trap). Non-blocking notes N1 (normalize_reward per-step vs SB3 return-std → document in §12), N2 (sbx-rl 0.26.0 vs pyproject floor). Verified-good: RunningStats/Welford, normalize, RunConfig, telemetry gate, eval identity, n_envs grounded in §7, sbx→sbx-rl fix.
- **Round 2** (d9dade1) — **APPROVE.** B1 fully resolved across contract + tests:
  - §5.1 action = 6-dim mixed ranges (a_bat∈[-1,1], 5 fractions∈[0,1]) per §2.2.
  - §5.2 actor `Dense(12)` → (mean[6], log_std[6]); per-component squash **tanh for a_bat, sigmoid for the 5 fractions**; deterministic eval = the squashed mean.
  - §5.3 critic input `concat(107, 6) = 113`.
  - §6.1.5 `target_entropy = −action_dim = −6.0`.
  - §7 baselines emit meaningful 6-vectors: `NoBatteryPolicy = [0,1,0,1,0,0]` (renewable→load, no VOLL — directly fixes the trap I flagged, with the critical note quoted); `TouPolicy` with sensible per-tier allocation.
  - Tests: `TestNoBatteryPolicy`/`TestTouPolicy` now shape-(6,) + full-vector + all-24-hour checks; new `TestActorOutputShape` pins actor mean/log_std (6,), **a_bat ∈ (-1,1) tanh range**, **fractions ∈ (0,1) sigmoid range**, deterministic action (6,), `critic1_fc1_w (113,256)`, `actor_out_w (256,12)`/`actor_out_b (12,)`, `SAC_TARGET_ENTROPY == -6.0`.
  - N1 addressed (commit msg "fix B1+N1"; reward-norm std-only behavior now pinned by `test_reward_norm_not_mean_shifted`). N2 (version-number mention) is cosmetic, non-blocking, left as-is.

## Reviewer-added cases (pushed to branch, `# reviewer:`, hand-derived)

By backend-reviewer (PR #40 round-2):
1. `test_normalize_reward_var_zero_stays_finite` — constant-reward batch → var=0; `normalize_reward(5)=5/√(1e-8)=50000→clip 10`, finite. Exercises the `_EPS=1e-8` div-0 guard (§4.3), previously untested.
2. `test_normalize_obs_var_zero_stays_finite` — constant-obs batch → var=0; `normalize_obs(3)=0/√(1e-8)=0`, finite.

**Note on labeling:** three dev-authored tests (`test_reward_norm_not_mean_shifted`, `test_eval_obs_stats_frozen`, `test_sub_month_demand_charge_is_zero_per_step`) carry `# reviewer:` markers but were written by the developer in response to round-1. Their content is correct and I endorse them as part of the suite; the marker is a minor convention slip (it denotes reviewer-*added* cases). Not blocking — flagged for tidiness.

## Notes for QA

- Red-phase: tests fail/skip until `energy_go.training.*` lands; `py_compile` clean.
- Post-implementation: SAC architecture conformance (actor 12-out, critic 113-in, target_entropy −6), per-component action ranges, baseline meaningfulness (NoBattery serves load, total_cost not VOLL-dominated), telemetry schema validation (incl. non-finite rejection), eval additive identity, and that RL beats both baselines is reported honestly (§8.1).
