# Review record — `contracts/serving/inference_stream.md` (PR #71 real-env-wiring amendment)

**Reviewer:** backend-reviewer
**Feature:** wire the real JAX env into inference_stream (task #48) + `has_policy` canonical fix (task #38)
**Tests:** `tests/serving/test_serving_inference_stream.py`
(Earlier feature-slice review records: `contracts/reviews/inference_stream_policy_cutover.md` (PR #59),
`contracts/reviews/inference_session.md`.)

## Stage 1 — contract + tests gate: APPROVE @ d5c3819
- EnvInfo→payload mapping: all 34 `info.*` fields cross-checked against `EnvInfo` on main
  (incl. `info.penalty_yuan`, not the `c_penalty_yuan` bug).
- Episode-boundary convention pinned: terminal step belongs to its episode
  (frame 167 → episode 0, frame 168 → episode 1); test asserts BOTH frames.
- `cost_cum` accumulation invariant test fixed to the LOCKED schema path
  (`payload.cost_cum.<field>_cum`, payload-level sibling of `costs`).
- Reviewer-added case: `test_has_policy_true_with_both_canonical_and_legacy`
  (canonical checkpoint must not be suppressed by a legacy `policy.npz`).
- `importorskip("energy_go.env.jax_env")` on real-env classes; real-env tests `@pytest.mark.slow`.

## Stage 2 — implementation audit: APPROVE @ af25839
Real-env path (`_JaxEnvSession`) verified against the code:
- `done_bool = bool(done)` from `jax_env.step()` — single source, no recompute.
- Episode increments AFTER the frame-167 payload (`episode = self.episode` then `+= 1`
  inside `if done_bool:`) → frame 167 = episode 0.
- `cost_cum` `+=`-accumulated; the `done` block only resets the env + bumps `episode`,
  never touches `self._cost_cum`.
- All 34 mapping fields present with correct names; `month_peak ← new_state.month_peak`.
- `datetime`/`sim_time_utc` computed in the non-jitted Python wrapper (not inside
  `jax_env.step`'s jit).
- `has_policy` (rest_api.py): `glob("checkpoint_*.npz")` + `"_step" in stem` on both the
  list and detail endpoints — consistent with the loader.

Stage-2 REQUEST_CHANGES (resolved @ af25839): `_SyntheticEnv` (no-jax fallback) had the old
episode off-by-one (frame 167 = episode 1), contradicting the locked amendment. Fixed by
capturing `current_episode` before the increment — now mirrors `_JaxEnvSession` exactly
(verified: `current_episode = self.episode` at L220 precedes the L221/L224 increments).

**Both gates APPROVE @ `af25839`.** Clear for QA (full suite incl. slow).
