# Env Evolution Roadmap — does the environment need a redesign?

**Author:** rl-architect · **Status:** design note (meta authority; plan-consistent restatement, not new decisions) · **Purpose:** the **pre-gate boundary document for the Workstream-C contract** — a fixed reference for *what may touch the jitted step function and what may not*.

This formalizes the answer to the USER's question *"环境是否需要重新设计 (does the env need a redesign)?"*

---

## Verdict: **No redesign.**

The physics core is sound and **stays**: the jitted `step` function, the §3.6 constraint-enforcement order, the D13 real-money/reward-basis cost separation, battery dynamics, and power balance. What just merged — the **device-model resolver layer** (Workstream B, `device_model_schema` v1.0.0, LOCKED) — *is the anti-rewrite mechanism*: new sites, devices, tariffs, and years **compose into `EnvParams`** without touching the step kernel. The env grows by **composition**, not rewrite.

---

## The protected core — what does NOT change

- The **jitted `step` function** and its internal physics (battery SOC dynamics, power balance, per-source costs).
- The **§3.6 enforcement order**: `parse/clip actions → battery dynamics (SOC clip) → cap flows-to-load → PCC export limit → grid import limit → costs/penalties`.
- The **D13 cost separation** (real-money total vs reward-basis total) and the LOCKED **telemetry**, **checkpoint**, **registry**, and **device_model_schema** contracts.
- The **Gansu bit-parity gate** (resolver → `EnvParams` reproduces the reference exactly) and the power-supply scenario's **`obs_dim = 107` / `action_dim = 6`**.
- The **§3.6 "not modeled" boundary** stays out of scope: voltage / reactive power / frequency. (§10 enhancements are the *only* sanctioned in-step additions — see below.)
- **D27 device-residency** (training inner loop stays on-device; no host-side replay buffer).

## The organizing principle — *does it touch the jitted step kernel?*

This is the single question the C-contract review uses to classify any proposed change. It splits all env evolution into two clean classes:

### Class 1 — step-kernel-**EXTERNAL** (resolver / wrapper; the safe majority)

These **do not touch** the step function. They are the anti-rewrite mechanism in action.

- **Multi-year simulation (Workstream C).** A 10/20-year run is a **host-side outer loop** over `Y` years, each a standard 8760-step dispatch episode, with **year-parameterized `EnvParams`** (degraded capacity/efficiency; **prices are NOT escalated in the env** per D31/F1 — constant real year-1, finance escalates post-hoc) built by the resolver, plus inter-year SOH evolution applied **between** years. **The step kernel is unchanged.** It is **NOT** a single 175 000-step episode — it is `Y` independent jitted years with cheap host param updates at the year boundary. D27's "zero host↔device copies per step" governs the training *inner* loop only; the year boundary is the natural host point (D31/d; D21 precedent). **The naïve cost is `Y` dispatches; with the accelerations below it is ≈1.** See *Multi-year acceleration* below.
- **Device / tariff selection (Workstream B).** Choosing a different device fleet or a region's TOU table is **resolver composition** — different `EnvParams`, same step kernel. (The table's `(12,24)` *shape* is the separate step-internal 2b; *which* table is selected is composition.)

> **Correction to the commissioning framing:** *scenario activation is **not** the C workstream.* C (multi-year) is step-kernel-**external** and is the safe outer loop; **scenario activation is step-kernel-internal** (Class 2 below). They are categorically opposite in env-impact and must not be conflated — the whole purpose of this boundary is that **C may parameterize but never alter the kernel.**

### Class 2 — step-kernel-**INTERNAL** (deliberate, individually gated; the minority)

These **do** touch the step function. Each is sanctioned only through its own gate; none is in v1.

- **(2a) Scenario activation — DEFERRED, not v1.** Building the env-logic for a non-power scenario (hydrogen / aluminum / data-center) is the one genuinely env-core-growing extension:
  - new **controllable devices grow `action_dim`** (e.g. an electrolyzer setpoint);
  - new **state variables** appear (H₂ storage level, smelter pot thermal mass, data-center deferred-job queue);
  - **safety/operational constraints** enter the step as hard limits via a **documented §3.6 extension** (see below);
  - the env becomes a **resolver-composed family** with **per-scenario `(obs_dim, action_dim)`** → each scenario gets its **own checkpoint** (the LOCKED Gansu 107/6 checkpoint is never reopened).
  Per D31/b these scenarios are **design-proven config-only and explicitly NOT built in v1**; their device `constraints:`/`economics:` blocks are **schema-present but not wired** (task #57/#61).
- **(2b) Seasonal `(12,24)` price lookup — CONFIRMED (USER chose option B; #58).** `EnvParams.price_table` reshapes `(24,) → (12,24)`; the step's price index becomes `price_table[month, hour]` at the **three sites** that read it (the current-price obs feature, the price-forecast block, and the cost-stage buy price). The **month index already exists** in the kernel (`MONTH_OF_STEP[t]`, used for demand-charge booking), so the change is a re-index, not new state. This is a `device_model_schema` **v2.0.0 re-LOCK** — **human-gated, and the USER granted that approval.** It lands in **two separable, separately-testable steps**:
  1. **Structural reshape (parity-preserving):** reshape + re-index, with `cn-gansu`'s seasonal table = the current 24-vector **replicated ×12** (`price_table[m,h] == old price_table[h] ∀m`). The full env trajectory is then **bit-identical** to the merged baseline — the reshape is a provable no-op behaviorally, so the v2.0.0 re-LOCK rests on a parity re-baseline that *cannot* regress. Both-reviewer re-review of the reshape.
  2. **Real seasonal data (behavioral):** real month×hour provincial tables land as **data-only** changes (v2.0.x), each with hand-computed cost tests. This *is* a behavioral change (intended product feature) and means the **seasonal Gansu env is a new env → its own training run + checkpoint** (the LOCKED flat-Gansu checkpoint is not reopened; per-env checkpoints, consistent with the device_model_schema LOCK).
  - **Checkpoint `obs_dim=107` LOCK is unaffected — verified in code:** obs carries price *values* (`obs[5]=price_table[h]`, the 24-step price forecast), not the table *shape*, and the **month is already encoded** (`obs[9]/obs[10] = sin/cos(month)`), so a seasonally-trained policy already has the phase signal. The reshape adds no obs feature; `obs_dim` stays 107, `action_dim` stays 6. (Implementation note for jax-env: the forecast block's month index must follow D9's near-episode-end clamping — no cross-year wraparound — exactly as the existing forecast price logic does.)

### Already-sanctioned in-step toggles (not part of the above; default-OFF)

- **§10 Tier-1 E2 (SOC/temperature-dependent efficiency) + E5 (forecast-error regime switching)** — approved per D17, ship as **default-OFF, parity-preserving** toggles. They touch the step but are already gated and never destabilize Gansu parity.

---

## The §3.6 enforcement-order extension (a deferred, rl-architect-owned ruling)

When scenario activation (2a) lands, the §3.6 order must be extended — and the constraints are **not uniform**:

1. **Per-step device clips** (electrolyzer min-turndown/ramp/cold-start, smelter modulation band) slot cleanly near the battery-dynamics stage:
   `parse → DEVICE-ENVELOPE clip → battery SOC → flows-to-load → PCC export → grid import → costs`.
   Same family as the SOC and PCC clips already in the order.
2. **Multi-step / temporal constraints** (smelter max-outage ~3–4 h before pot-freeze; data-center SLA-over-time) are **not per-step clips** — they require **state** (e.g. consecutive-unserved-hours) and a horizon-aware penalty or hard stop. This is a materially harder enforcement design and likely a **§3.6 spec amendment → human-gated**.

This ruling is authored **when the first non-power scenario is built**, not now (task #61).

---

## Multi-year acceleration (Workstream C) — *"a smarter way to run 20 years"*

The naïve 10/20-year run is `Y` sequential 8760-step dispatches. Four accelerations collapse that to **≈1 dispatch's wall-clock**, all **step-kernel-external** (Class 1) — they change *how the resolver-composed years are batched*, never the step. **The F1 ruling is what makes them clean:** because dispatch runs at constant real prices, the *only* inter-year variable that changes dispatch is **battery/PV SOH** — a single smooth axis.

1. **Predictor–corrector year-parallelism.** Inter-year coupling is *only* SOH and it is weak. Assume a vendor SOH schedule (predictor) → resolver builds all `Y` years' `EnvParams` → **`vmap`-dispatch all years in parallel** → recompute SOH from realized throughput (corrector) → iterate. Wall-clock ≈ 1 year. The #79 resolver is the injection point.
   - **Convergence (ruling):** criterion = relative change in the SOH trajectory below tolerance (e.g. `‖SOHₖ − SOHₖ₋₁‖∞ < 0.5 % capacity`) *or* `ΔNPV < 0.1 %`; **max 3–4 iterations**, then **fall back to sequential and FLAG** — never silently return an unconverged fixed point (same honesty discipline as the `dispatch_fidelity` guard).
2. **SOH-grid interpolation (response surface).** Annual aggregates are smooth in SOH. Dispatch ~5 grid points (100/95/90/85/80 %) × the weather ensemble in **one `vmap` batch**; interpolate every year (and post-replacement second life) from the surface. 20 years → ~5 dispatches.
   - **Replacement discontinuity (ruling):** the surface is **piecewise per battery-life segment** — the grid must **straddle** the replacement knot; **interpolate within a battery life, never across the replacement year.** Second life is its own segment with its own grid.
   - **Per-policy or shared (ruling): per-policy.** Different policies dispatch differently → different aggregate-vs-SOH surfaces; a shared surface would defeat the per-policy comparison (master-plan E). The `vmap` batches policies × SOH-grid × ensemble together, so per-policy surfaces are cheap to build at once.
3. **Train-once / eval-many.** The policy is capacity-conditioned via normalized SOC in obs → train **once per scenario config**; all multi-year work is forward rollouts (`vmap` over years × ensemble × policies).
   - **Caveat (ruling):** normalized SOC absorbs *capacity* degradation cleanly; *round-trip-efficiency* decline is a mild residual distribution shift. v1 treats train-once as the default with that as a **documented limitation**; if SOH-efficiency drift is large, train a policy at a few SOH grid points (strategy 2 already provides them) — same fidelity-flag family.
4. **Zero-dispatch sensitivity — the F1 dividend.** Discount-rate / CAPM-parameter / **uniform**-escalation sweeps **re-arithmetic the cached cash flows** — pure finance-layer math, **no env runs** → the rate-sensitivity UI is *interactive, not batch*. Only **physical** changes (device swap, capacity) re-dispatch.
   - **Where the cache lives (ruling):** the cache is **#55's per-stream accumulator output, emitted per `(year, stream)`** and persisted on the **off-wire finance artifact** (D31/f). Granularity: **annual per-stream cash flow** is sufficient and *exact* for discount-rate and uniform-escalation sweeps (those are the interactive ones). **Hourly** physical quantities are needed only to *re-price at a different tariff without re-dispatch* — which changes optimal dispatch, so it is a **`dispatch_fidelity = lower_fidelity` flagged** estimate, not exact. So: annual-per-stream = the exact interactive cache; optional hourly-physical = the flagged tariff-what-if cache. This makes **#55's file/REST surface a hard requirement to be the cache**, not transient (a binding tie-in for #55/#82).

All four are Class 1: the step kernel never changes; they batch and cache resolver-composed years. **None requires reopening any LOCKED contract.**

---

## Boundary for the Workstream-C contract review

The C contract may:
- build **year-parameterized `EnvParams`** through the resolver (degradation, escalation-as-closure-constant);
- evolve **SOH between years** host-side;
- run **`Y` independent 8760-step jitted years** (BOTH the RL policy and the §11 baselines, D31/d).

The C contract may **NOT**:
- alter the jitted **step kernel**, `action_dim`, `obs_dim`, or the **§3.6 order**;
- introduce **per-step host↔device copies** (D27);
- apply **price escalation inside the env** — dispatch runs at **constant real year-1 prices**; all escalation is the finance layer's, post-hoc (**D31/F1**).

Anything that would cross those lines is **scenario activation (2a)** or **seasonal (2b)** — separate, individually gated, and out of C's scope.

---

### One-line summary

> The step kernel is the protected core; the resolver is how the system grows without touching it; only **scenario activation** and **seasonal pricing** deliberately reach into the kernel, each behind its own gate — and **multi-year simulation is not one of them.**
