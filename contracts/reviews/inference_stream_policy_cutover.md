# Review record — `contracts/serving/inference_stream.md` (policy cutover, task #23)

**Reviewer:** backend-reviewer · **Area:** serving · **PR:** #59 (`feat/serving-policy-cutover`)
**Stage:** contract + tests gate

## Verdict: APPROVE (round-2, commit fcc351b)

Approved suite = developer cases + the 5 reviewer-added cases below.

## Round history

- **Round 1** (4faab20) — REQUEST_CHANGES. Blocker **B-LEGACY**: the contract kept a legacy `policy.npz` (`w_0/b_0`) fallback that preserved the non-conformant placeholder D28 said to replace — tanh-hidden + identity-output (fractions in [-1,1] not the §6 sigmoid [0,1]) + `obs_std` normalization (vs canonical `obs_var`+clip) — for a use case that doesn't exist (the placeholder never produced trained policies; real training emits canonical §6 `.npz`). This entangled the dev's Option A/B question: keeping the legacy path while obsoleting `TestPolicyForwardPass` is self-contradictory. Direction: **drop the legacy fallback → Option A** (canonical-only; remove `TestPolicyForwardPass`). Plus minor (case-2 `tanh(8)` precision).
- **Round 2** (fcc351b) — **APPROVE.** Legacy fallback fully dropped: contract §Policy-loading now states `policy.npz`/`normalization.npz` is **not supported**, `policy_not_found` when no canonical checkpoint; `TestPolicyForwardPass` + the legacy forward removed; `_make_policy_npz` retained only to create a *stray* policy.npz in case 4 (which correctly verifies canonical is used and the stray file ignored). Case-2 now computes `np.tanh(np.float32(8.0))`. Canonical path verified correct: `std=sqrt(obs_var+1e-8)`, `clip ±obs_clip` (matches checkpoint_format §6/§4.2); canonical discovery (highest `_step{N}`); `policy_forward → actor_forward_numpy` delegation (§6/D28).

## Reviewer-added cases (pushed to branch, `# reviewer:`, hand-derived)

Class `TestReviewerPolicyCutover`:
1. `test_d28_mean_clip_negative_side` — `actor_out_b[0]=-100` → `tanh(clip(-100,-8,8))=tanh(-8)≈-0.99999977` (not `tanh(-100)=-1.0`); strictly `> -1`. Mirrors case 2's positive side.
2. `test_d28_sigmoid_fraction_negative_clip` — a fraction with mean −100 → `sigmoid(-8)≈0.000335` (not `sigmoid(-100)=0.0`); strictly `> 0`. Pins the sigmoid (fraction) squash under the clip — case 2 only covers the tanh (a_bat) component.
3. `test_obs_clip_clamps_extreme_obs` — two distinct extreme obs (`+1000` vs `+5000`, and `-1000` vs `-5000`) clamp to ±`obs_clip` → **identical** actions (random-weight checkpoint so the action depends on the normalised obs). Pins that `obs_clip` is actually applied.
4. `test_policy_not_found_on_empty_run_dir` — a run dir with no canonical checkpoint → error frame `code="policy_not_found"`. Pins the dropped-legacy error path.
5. `test_discovery_ignores_stray_non_canonical_files` — canonical + a stray `notes.txt` + a malformed `checkpoint_garbled.npz` → discovery streams valid D18 frames (doesn't crash on stray/malformed files).

## Minor (non-blocking, noted on the PR)

- Case 4 (`test_canonical_checkpoint_preferred_over_legacy`) docstring still frames `policy.npz` as "legacy: policy.npz" (2nd fallback) — stale vs the contract's "not supported"; reframe as "a stray policy.npz is ignored". The behaviour tested (canonical used) is correct.
- Case 2 docstring line ~944 still shows `≈ 0.9999977` (6 nines); the binding assertion uses `np.tanh(np.float32(8.0))` so this is cosmetic only.

## Notes for QA / implementation

- Red-phase: tests skip until `energy_go.serving.inference_stream.policy_forward` + the checkpoint format land. Post-implementation: the placeholder loader (`w_N`/tanh-hidden/`obs_std`) must be **removed** (not just unused) — the cutover replaces it with `policy_forward → actor_forward_numpy` (§6 incl. the ±8 D28 clip). Gate on the §6 numpy-vs-JAX action parity (atol=1e-5) + the D28 clip + `obs_var` normalization.
