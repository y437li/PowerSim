## 7. Language recommendation: JAX (core) — not Go
> **Owner:** rl-architect

### TL;DR
**Rebuild the environment + training in JAX. Keep/rewrite the serving layer separately (FastAPI is fine; Go only if you want a single static binary for the dashboard backend).** Go is the wrong tool for the RL core.

### Why not Go for the RL core
- No real RL/autodiff ecosystem (no SB3/torch equivalent; Gorgonia is not production-grade). You'd hand-write SAC, GPU kernels, and replay buffers.
- Your bottleneck is **not** request concurrency (Go's strength); it's **simulation + gradient throughput** (JAX's strength).
- You already tried the "fast core in a systems language" route (`rust_core`) — it speeds up the env but the Python↔env boundary and GPU sync still cap you at ~350 FPS training.

### Why JAX fits this project unusually well
Your env is pure array math: power balance, clips, proportional scaling, a scalar SOC update, sinusoidal generators, AR(1) noise. No branching on external I/O. That's exactly what `jit`/`vmap` eat:

- **Vectorized envs:** `vmap` the step function over 2,000–10,000 parallel envs on one GPU. Realistic throughput: **10⁶–10⁷ env-steps/sec** vs your current ~9,000 (CPU env) and 350 FPS end-to-end training. Training runs go from hours to **minutes**.
- **End-to-end on device:** env, replay buffer, and SAC update all live on GPU — zero host↔device copies per step (this is what kills SB3+Gym setups).
- **Existing building blocks:** SAC/PPO in JAX already exist — **purejaxrl**, **sbx (SB3-in-JAX)**, **Brax-style training loops**, `flashbax` (replay buffers), `gymnax` (env API pattern to copy).
- **Domain randomization for free:** `vmap` over battery/price/weather params → train one robust policy across the whole asset library simultaneously.
- Deletes `rust_core` entirely — one language for the whole research stack.

### What the JAX rewrite looks like

```python
class EnvState(NamedTuple):       # pure, immutable
    soc: jnp.ndarray; month_peak: jnp.ndarray; t: jnp.ndarray; rng: jax.Array

def step(state, action, params, data) -> tuple[EnvState, Obs, Reward]:
    # §3 formulas, written with jnp.where instead of if/else
    ...

batched_step = jax.jit(jax.vmap(step, in_axes=(0, 0, None, None)))
```

Gotchas to plan for:
1. **No data-dependent Python branching** — every `if` in §3 becomes `jnp.where`/`clip` (your env is 90% there already).
2. Pre-generate the synthetic year as a device array; index with `lax.dynamic_slice`.
3. AR(1)/cloud noise via `jax.random` with explicit key threading (you get reproducibility for free).
4. Calendar month boundaries: precompute a `month_of_step` array, detect change with array compare — no datetime logic in the jitted step.
5. Keep `VecNormalize` logic as explicit running-stat arrays saved with the checkpoint.

### Where Go *would* make sense
Only the **production serving layer**: a small Go service that loads the trained policy via **ONNX Runtime** (export: JAX → `jax2tf`/ONNX, or just export the actor MLP weights — it's a plain MLP, trivially reimplemented in ~50 lines of Go), serves the dashboard websocket, and talks to real site hardware. You get a single static binary, easy deploys, great concurrency. But that's optional polish, not the rebuild's core.

### Suggested rebuild order
1. **Port the env to JAX as pure functions** (§3 formulas + §4 generators), unit-test against the current Python env step-for-step on fixed seeds.
2. Fix the §6 inconsistencies while porting (decide Δt = 15 min or 1 h once).
3. Training loop: start from **sbx** or **purejaxrl** SAC; vmap 4096 envs.
4. Re-run baselines (rule-based TOU) in the same JAX env for fair comparison.
5. Export policy (ONNX or raw weights) → serving layer (keep FastAPI, or Go if you want).
6. Point the React dashboard at the new serving API (unchanged contract: `live_metrics.json` shape).
7. Extend to the composable asset library (§8) once the §3 plant reproduces baseline results.

---

