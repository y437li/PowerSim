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

- **Multi-year simulation (Workstream C).** A 10/20-year run is a **host-side outer loop** over `Y` years, each a standard 8760-step dispatch episode, with **year-parameterized `EnvParams`** (degraded capacity/efficiency, escalated prices = closure constants per year) built by the resolver, plus inter-year SOH evolution applied **between** years. **The step kernel is unchanged.** It is **NOT** a single 175 000-step episode — it is `Y` independent jitted years with cheap host param updates at the year boundary. D27's "zero host↔device copies per step" governs the training *inner* loop only; the year boundary is the natural host point (D31/d; D21 precedent).
- **Device / tariff selection (Workstream B, #58 regional).** Choosing a different device fleet or a regional `(24,)` TOU table is **resolver composition** — different `EnvParams`, same step kernel.

> **Correction to the commissioning framing:** *scenario activation is **not** the C workstream.* C (multi-year) is step-kernel-**external** and is the safe outer loop; **scenario activation is step-kernel-internal** (Class 2 below). They are categorically opposite in env-impact and must not be conflated — the whole purpose of this boundary is that **C may parameterize but never alter the kernel.**

### Class 2 — step-kernel-**INTERNAL** (deliberate, individually gated; the minority)

These **do** touch the step function. Each is sanctioned only through its own gate; none is in v1.

- **(2a) Scenario activation — DEFERRED, not v1.** Building the env-logic for a non-power scenario (hydrogen / aluminum / data-center) is the one genuinely env-core-growing extension:
  - new **controllable devices grow `action_dim`** (e.g. an electrolyzer setpoint);
  - new **state variables** appear (H₂ storage level, smelter pot thermal mass, data-center deferred-job queue);
  - **safety/operational constraints** enter the step as hard limits via a **documented §3.6 extension** (see below);
  - the env becomes a **resolver-composed family** with **per-scenario `(obs_dim, action_dim)`** → each scenario gets its **own checkpoint** (the LOCKED Gansu 107/6 checkpoint is never reopened).
  Per D31/b these scenarios are **design-proven config-only and explicitly NOT built in v1**; their device `constraints:`/`economics:` blocks are **schema-present but not wired** (task #57/#61).
- **(2b) Seasonal `(12,24)` price lookup — conditional on the USER's tariff choice (option B).** If the USER needs accurate month-dependent provincial TOU, `EnvParams.price_table` reshapes `(24,) → (12,24)` and the step's price index becomes `price_table[month, hour]`. This is the **lone major** change in the near-term tariff work: a `device_model_schema` **v2.0.0 re-LOCK** + Gansu-parity re-baseline + both-reviewer re-review — **human-gated**. v1 default (option A) keeps `(24,)` and avoids it entirely (#58).

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
