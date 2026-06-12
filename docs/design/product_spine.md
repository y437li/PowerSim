# Product Spine — the unified config → algorithm → train → eval → finance pipeline

**Author:** rl-architect · **Status:** plan amendment (meta authority; consolidates merged USER directives 2026-06-12). The binding-decision index entry is **LINEAGE D32** (lands with the D29-backfill once the decisions tail settles). · **Purpose:** the **fixed forward reference for the A / C / D / E contracts** — what the product is, how config threads every stage, and which extensions are gated.

This amends the master plan (PR #78 / D31). It does **not** change the env step kernel — see `env_evolution_roadmap.md` for the kernel boundary; this doc is about the *config flow across stages*.

---

## 1. The five-stage spine (USER-canonical)

> **① config → ② select algorithm → ③ train → ④ eval → ⑤ project-finance simulation**

This is THE product. Power-composite v1 ships the **whole spine end-to-end first**; scenario activation (§3) follows. The frontend's primary UX is a guided **wizard** mirroring these five stages (workstream A+E; existing TrainingPanel/dashboard become stages ③–④, not standalone pages; design-system #59 lands first so the surfaces are token-compliant).

| Stage | Owner | Input | Output |
|---|---|---|---|
| ① **config** | frontend A (UI) · jax-env resolver | geo/devices/tariff/scenario **+ fleet sizing** | a validated scenario config |
| ② **select algorithm** | training / harness | `algorithm_id` | a **policy producer** |
| ③ **train** | harness (control) · training | config + producer | an **immutable policy artifact → the policy library** (checkpoint / baseline spec + provenance) |
| ④ **eval** (select × run) | env-harness / serving | **(policy from library) × (env config)** | per-`(year,stream)` accumulators (#82) + eval-vs-baseline + cross-eval provenance |
| ⑤ **finance sim** | finance-expert (E) | a **selected** eval result | IRR/NPV/LCOE + P50/P90/P99 + sensitivity |

> **Train and eval decouple via the policy library (USER revision).** The spine is *not* a strict linear chain. Stage ③ deposits **immutable** policy artifacts into a library; stage ④ is a **selection** stage — pick `(policy from library) × (env config)`, run, and **multiple eval results coexist**; stage ⑤ consumes a *selected* eval result. A config edit therefore never "stales" a *training run* (runs are immutable, tied to **their** config) — see §2.2 and the refined DAG in §5.

## 2. The single-config invariant (binding C/D/E acceptance criterion)

**One scenario config (+ algorithm config) is the sole parameterization of all five stages. No stage may require a config field or dialect the others don't share.** The scenario-as-configuration keystone (D31/b) was built for exactly this; the USER directive makes it an *invariant*.

The mechanism that makes it hold: **one per-step stream-economics computation, three consumers.** The same code that computes a stream's per-step value (e.g. `h2_sale ¥/h = H₂ produced × year-1 H₂ price`) feeds:
1. the **reward** (per-step real-money streams + bounded shaping — §4),
2. **#82's stream-keyed accumulators** (same streams, aggregated to per-`(year,stream)`),
3. the **finance engine** (same streams, escalated + discounted).

So **reward streams ≡ eval-accumulator streams ≡ finance streams** — a single source of truth, no divergence. The **join keys** thread every stage: `device-ID · region-ID · stream-ID · checkpoint-ID · algorithm-ID`.

### 2.1 Algorithm registry — baselines and RL algos are both "policy producers"

`algorithm_id` is a stage-② config field resolved through a **code registry** → a *policy producer*:
- **SAC** (trains a checkpoint), **NoBattery / TOU / DP-oracle** (the §11 baselines — produce a policy **without** training), future **PPO/TD3**.
- Every producer's output is a **policy artifact** with a uniform interface; **stages ④⑤ consume it algorithm-agnostically** (eval already compares RL-vs-baselines; finance prices any policy). The registry adds a stage *without changing the downstream interface*.

### 2.2 The policy library — the artifact store that makes ③/④ decouple (USER revision)

Stage ③'s artifacts live in a **policy library** (RL checkpoints + baseline specs), each carrying **provenance**: `config hash · algorithm_id · train date · global_step`. This makes the policy-producer/artifact abstraction **load-bearing**: eval selects *any* compatible library policy against *any* env config, so the eval-vs-baseline comparison generalizes to an N-policy × env-config selection.

Two things this pins:

- **Policy↔env compatibility check (backend-owned, single source).** A selected policy's `(obs_dim, action_dim)` — read from its checkpoint metadata (the LOCKED `checkpoint_format`) — **must match** the selected env config's **resolver-derived** dims. The check has **one implementation** (the resolver/serving boundary, never duplicated in TS) and is **surfaced in the picker** (incompatible policies greyed out **with the reason**, e.g. *"trained action_dim 7 ≠ this scenario's 6"*). This is what keeps a power-scenario policy from being run on a hydrogen env, and vice-versa.
- **Cross-eval provenance (a feature, not a bug).** Evaluating a policy on a *different* weather year / sizing / season than it trained on is a **legitimate robustness test**. Eval results therefore record **both** `trained-on` and `evaluated-on` provenance; when they differ, the result is **machine-visibly flagged** (the `dispatch_fidelity` guard family extends here — a cross-eval result is honest about being off-train-distribution). Concretely this is why the seasonal-data step (`device_model_schema` v2.0.0 / §3) doesn't *force* a retrain to get *an* eval: a flat-trained policy can be cross-evaluated on the seasonal env (dims match, 107/6) as a flagged robustness check; the *best* seasonal policy is a fresh train, but the cross-eval is valid and labelled.

## 3. Scenario activation — scheduled, sequenced, gated

D31/b's "design-proven config-only, NOT built" is now a **scheduled deliverable** (USER directive). The **gate is unchanged** per group (action_dim growth, new state, §3.6 extension, per-**enabled-set** `(obs_dim,action_dim)` → own checkpoint, both-reviewer re-review + rl-architect re-LOCK); only the **schedule** changes. (Groups *compose* — see §3.1.)

**UI:** unactivated groups are **HIDDEN** in the config stage (not greyed "coming soon") — distinct from the *eval picker*, where an activated-but-incompatible **policy** is greyed **with reason** (§2.2). Hiding = "this product doesn't exist yet"; greying = "this policy can't run on this env."

**Sequence (by increasing kernel-internal novelty — each builds the machinery the next needs):**

| # | Scenario | New env-core | §3.6 extension | Gate beyond the standard activation gate |
|---|---|---|---|---|
| v1 | **power-composite** | (the baseline) | — | ships the full spine end-to-end FIRST |
| 1 | **H₂ / electrolyzer** | +1 action (setpoint) · +1 state (H₂ storage) | **per-step DEVICE-ENVELOPE clip** (turndown/ramp/cold-start) — tractable | — |
| 2 | **aluminum / smelter** | modulation-band load | **multi-step/TEMPORAL** (max-outage ~3-4h pot-freeze; outage-duration state) | **REBUILD_SPEC §3 amendment → USER sign-off** |
| 3 | **datacenter** | deferrable IT load | **FLEXIBLE-LOAD ACTION extension** (job deferral) + SLA | **action-space change → USER sign-off** |

The two **future USER sign-offs** (aluminum temporal §3.6; datacenter flexible-load action) are flagged now; each escalates **at its scenario's design time**, not now. The overall scope is USER-authorized by the integration directive.

### 3.1 Scenarios COMPOSE — a scenario is a SET, not a choice (USER ruling)

A site may run **multiple product groups at once** (e.g. electrolyzer **and** datacenter, on the always-present power/battery base). So:

- **Scenario = a SET of enabled device/stream groups on top of the power base — NOT an enum.** The config schema is a **set/flags** structure (`enabled_groups: [electrolyzer, datacenter]`), never a single-choice field. **No contract may bake in mutual exclusivity.** This is the keystone's natural form — devices and revenue streams were always composable; this states it as a binding requirement. *(It also retroactively validates the #82 decision to pre-declare all six streams with zero-placeholders: enabling a group simply flips its stream from dormant to active — composition is free.)*
- **obs/action compose ADDITIVELY per enabled group**, at **fixed canonical offsets**: `(obs_dim, action_dim) = base + Σ(enabled groups)`. A **deterministic canonical group ordering** (fixed registry order — base, electrolyzer, smelter, datacenter — each at a fixed slot) is **required** so `{electrolyzer, datacenter}` always yields the *same* layout regardless of enable order — otherwise checkpoints aren't comparable.
- **The compat check (§2.2) keys on the enabled-SET, not scalar dims.** Two different enabled-sets can share a dim count but mean different things, so a policy's reusability is gated on its **trained-on enabled-set** matching the env's (read from the checkpoint's `run_config_json` — already in the LOCKED `checkpoint_format`, so **no checkpoint re-LOCK**; scalar dims are the fast necessary check, the enabled-set signature is the sufficient one).
- **Activation schedule unchanged.** Each group still activates through its own kernel-internal gate (H₂ first, …); **composition becomes available as soon as ≥2 groups are individually activated** — no separate "composition" milestone.
- **Dispatch competition is the RL policy's job — no extra mechanism.** When H₂ + datacenter + grid-export all compete for the same renewable/battery energy, the **unified reward** (Σ active streams, §4) is exactly what drives the policy to the highest-value allocation. The single stream-economics primitive (§2) makes composed dispatch competition fall out for free — that competition is *why* there's a learned policy at all.

## 4. Reward alignment — "train on the economics you'll be judged on"

D13 **extends**, doesn't break: `reward_basis = Σ(active real-money streams, cash-flow-signed) + bounded shaping`, with the **real-money / shaping separation preserved**. For a non-power scenario the active set gains the product revenue (`h2_sale`, etc.) so the policy **maximizes project value**. **F1-consistent:** streams are valued at **year-1 real prices**; finance escalates post-hoc. The reward extension is **kernel-internal → part of each scenario's activation gate** (it computes streams from the *same* code #82 accumulates — §2).

## 5. Fleet sizing — configurable, and the stage-invalidation DAG

**Sizing is a stage-① config field**, not a schema change (`device_model_schema` already carries `fleet_*` / `unit_count`, v1.0.0). The UI exposes capacities per device category alongside model selection; the resolver derives the rest. Scenario devices inherit the **same shape** (model-ID + fleet-size + optional unit_count) — the dialect stays uniform. Finance **CAPEX = units × unit-price** from the benchmark library (#63), so a sizing edit **reprices the project automatically** (E-contract linkage).

**The stage-invalidation DAG.** Each stage's output is a pure function of its inputs; an edit invalidates that stage + all downstream. **Two classes of edit** — and the distinction is the F1 dividend realized as UX:
**Training runs are immutable** (USER revision) — a config edit **never stales a run**; runs are tied to *their* config and live in the library (§2.2). Invalidation applies to the **eval→finance** edge and the **config→(new evals)** edge, not to `config→training-runs`:

- **Physical config** (sizing · device · tariff-shape) edit → existing **eval *results*** (computed against the old config) go stale → a **new eval** is needed = select a **compatible** policy from the library × the new config. A fresh **train** is required only if no suitable compatible policy exists for the new config (the `algorithm_id` picks the producer). The old run is untouched and still valid for *its* config.
- **Finance-only config** (discount rate · escalation · currency) → **re-run ⑤ only**, *no re-dispatch* (re-arithmetic on the cached per-`(year,stream)` accumulators). Rate/sensitivity controls are **interactive sliders**. **Residency split (USER-confirmed):** the simple re-discount (rate/escalation on the cached cash flows) runs **client-side** for instant interactivity; **tax/debt layering** runs **server-side** (heavier, the finance engine's domain).

A stale edge is **machine-visible** (same provenance-guard family as `dispatch_fidelity`): the wizard refuses to present a stage-⑤ number whose underlying eval's `evaluated-on` provenance ≠ the current config — and *flags* (does not block) a deliberate **cross-eval** (a library policy run against a config it wasn't trained on, §2.2).

## 6. Config validation — two-tier, single source (sibling `config_validation` contract)

Obviously-unreasonable configs **error**; suspicious-but-legal configs **warn** (USER directive). Rules span device + tariff + econ → a **sibling shared contract `config_validation`** (NOT folded into `device_model_schema`), task #66. **All rules live in the resolver layer (jax-env), exactly once**; serving exposes a `validate` endpoint; the UI renders field-level — **no duplicate TypeScript rule set** (precedent: D26 two-tier, D18 single-validator).

- **Hard errors (reject):** non-positive capacities; battery C-rate beyond the device per-unit ratio; `unit_count` inconsistent with fleet size; load unservable at max import + full generation; tariff table wrong shape; econ params out of domain (WACC outside ~(0, 30 %), senseless negative prices).
- **Warnings (proceed-with-ack):** C-rate > 2C (LFP); storage > ~10 h; electrolyzer fleet > total generation; PCC export ≪ installed (structural curtailment); sizing so small training is meaningless.

API: `validate(config) → { errors: [Issue], warnings: [Issue] }`, `Issue = { rule_id (stable) · field · message · constraint-with-numbers }` (e.g. *"fleet_power 98.16MW / fleet_capacity 294.5MWh = 0.33C — OK"*, *"800MW/200MWh = 4C exceeds model max 1C — ERROR"*). `resolve_site()` **raises** on errors (extends `DeviceModelError`); `validate()` is **non-raising** for the UI pre-check. **Ownership split:** jax-env owns physics-plausibility; finance-expert owns econ-plausibility; one resolver source of truth.

## 7. Ownership map (no new gates beyond those already defined)

- **frontend (A+E):** the five-stage wizard; stage-① config incl. sizing + validate-endpoint rendering; stage-⑤ finance simulation surface (P50/P90/P99). Design-system #59 first.
- **harness:** stage-③ train control (existing). **training:** the algorithm registry. **serving:** stage-to-stage data flow + the `validate` endpoint.
- **jax-env (resolver):** config resolution + the v2.0.0/tariff/economics/constraints schemas + the validation rules (physics half).
- **finance-expert (D/E):** stage-⑤ finance simulation, CAPEX↔sizing linkage, econ validation rules, the stream economic definitions (the shared per-stream primitive §2/§4 consumes).
- **rl-architect:** this spine, the activation gates + §3.6 extensions, the shared-contract LOCKs.

---

### One-line summary

> One config threads the stages through one stream-economics primitive; train and eval decouple via an immutable policy library (select policy × env config, with an enabled-set compatibility check and cross-eval provenance); sizing and algorithm are first-class config; scenarios are a **composable set** of device/stream groups (not an enum) that activate on a gated schedule and compete for energy through the unified reward; physical edits need a new eval, finance edits re-slice instantly; nothing reaches the step kernel except through a named gate.
