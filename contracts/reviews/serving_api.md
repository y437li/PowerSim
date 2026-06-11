# Review record: Serving API (REST + inference stream + training proxy)

- **Contracts:** `contracts/serving/rest_api.md`, `inference_stream.md`, `training_proxy.md`
- **Tests:** `tests/serving/test_serving_rest_api.py`, `test_serving_inference_stream.py`, `test_serving_training_proxy.py`
- **PR:** #29 (`feat/serving-api`) · **Reviewer:** backend-reviewer (frontend-reviewer advisory on the wire format)
- **Verdict:** APPROVE — commit 19f8590
  - R1: REQUEST_CHANGES — B1 /eval vs LOCKED eval_compare; B2 policy forward-pass test missing; B3 (training_proxy add) train_metrics used REST train_curve shape; +no_session/seq-boundary adds.
  - R2 (19f8590): all resolved.

## R2 verification (static; suite not run here — energy_go.telemetry.validate [PR #23] not yet on branch + pytest_asyncio absent locally)
- B1 — EVAL_RESULTS fixture now full LOCKED eval_compare: eval_horizon_steps=8760, checkpoint_id, cost_basis="real_money", per-policy soc_violations_count/soc_violation_mwh/penalty_yuan. Additive identities hand-checked: rl 42000, no_battery 60000, rule_based_tou 50000. `test_eval_payload_passes_validate` wraps in eval_compare envelope + validate()==[]. /eval is now a true passthrough + serving "units".
- B2 — TestPolicyForwardPass: reference = tanh hidden / identity output / clip[-1,1] (matches inference_stream.md policy format); known weights (3→4→4→2) within 1e-5; clip test (150/-125→±1); tanh-vs-relu discriminator (tanh(-0.5)≈-0.462 ≠ relu 0). policy_forward exposed as public util.
- B3 — MOCK_TRAIN_FRAMES now conform to LOCKED train_metrics (global_step, wall_seconds, env_steps_per_sec, actor_loss, critic_loss, ent_coef, reward_scaled_mean, reward_norm_mean, cost_total_real_mean_yuan, is_eval_checkpoint, checkpoint_id); dependent assertions updated.
- Adds — no_session (pause/resume), bad_command/invalid_message, seq-across-168-boundary (frames[168].seq==168, episode==1; D3), all present and correct. Frontend-advisory items folded in (session_id, step cmd→bad_state, error table).

## Non-blocking notes
- Mock frame 1 has reward_norm_mean=null with is_eval_checkpoint=false; per LOCKED schema null is the EVAL case (reward_norm_mean is non-null during training, null at eval). Schema-valid (number|null) so validate()==[] holds — but the comment "no eval checkpoint yet" is semantically backwards. Tidy.
- Ensure inference_stream.md documents `policy_forward(weights, obs)` as the public utility the test imports.
- Merge-order dependency: the validate()-based tests + the stream's D18 obligation require PR #23 (energy_go.telemetry.validate) merged first. PR #29 cannot go green in QA until #23 lands.
