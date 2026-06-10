## 5. Training methodology
> **Owner:** training-engineer (rl-architect interim until staffed)

- **Algorithm:** SAC (stable-baselines3), `MlpPolicy`
- **Hyperparameters:** lr 1e-4, γ 0.999, batch 512, buffer 1e6, τ 0.005, `ent_coef="auto"`, train_freq 1, gradient_steps 1, 500k timesteps, 4 parallel envs (`DummyVecEnv`)
- **Normalization:** `VecNormalize(norm_obs=True, norm_reward=True, clip 10)` — stats saved with the model (`vec_normalize.pkl`) and **must be loaded at inference**; eval env shares `obs_rms` with training env, reward unnormalized.
- **Why γ=0.999:** demand charge is a monthly signal; the agent must value rewards hundreds of steps ahead.
- **Why 7-day random-start episodes:** sees all seasons/tariff patterns; faster credit assignment than full-year episodes.
- **Eval:** deterministic policy over the full 365-day year; metrics = total energy cost, demand charge, degradation, curtailment, violations.

**Baselines to compare against** (in `agents/baseline_agent.py`): no-battery, and rule-based TOU (charge in valley, discharge in peak). The RL agent must beat these or it isn't learning anything useful.

---

