## 10. Env-logic enhancements (proposal — opt-in, parity-preserving)
> **Owner:** jax-env-engineer

**Status: user-approved with Tier-1 trim (2026-06-10, PR #9 / D17).** This section enumerated candidate enhancements to the simulation env logic beyond the current §3 plant and §8 asset library. The user **greenlit Tier 1 only — E2 (SOC/temperature efficiency) + E5 (forecast regime noise)** — for build; **E1/E4 are deferred candidates** (revisit after Tier 1) and **E3/E6 are parked** with the reasons stated below. Each approved enhancement still ships as its own numbered DECISION + contract + tests + parity regression, **sequenced AFTER the §3 reference-implementation baseline (D11) lands** — they are toggles (default OFF), so building them after parity never destabilizes the parity target.

### 10.0 Governing rules (apply to every enhancement below)

1. **Each maps to a §3.6 "Not modeled" line.** §3.6 already names the fidelity boundary (no ramp-rate, no losses, no reactive/voltage, no battery calendar aging or SOC-dependent efficiency, no min-import contracts, no frequency services) and says real-site rules "slot in as extra clamps/penalties at the marked stages." Each enhancement is a **deliberate, itemized lift** of one of those lines. **Voltage, reactive power, and grid-frequency services remain OUT regardless** — they require a power-flow solver this env is not (the boundary moves by item, not wholesale).
2. **Toggleable, default OFF.** Every enhancement is gated by a site-YAML flag (e.g. `physics.battery_aging: false`). With all flags OFF the env is byte-for-byte the current §3 physics, so the **Gansu parity case (D11) validates against the unenhanced model** — parity is never at risk. The parity test asserts all enhancement flags are OFF.
3. **Sequence after baseline parity.** Build order: §3 parity → §8 asset library → these. An enhancement that adds emitted fields is a **minor** telemetry bump (§ telemetry contract Versioning); one that changes the §4 synthetic year must use a **separate seed/config** so the D11 parity year is bit-identical.
4. **Stays jittable.** Every mechanism is expressible as `jnp.where`/`clip`/lookup with explicit RNG threading (§7) — no data-dependent Python branching, no host sync.
5. **Re-verify reward scale.** Any new cost/penalty term keeps the 1e-5 scaling and must keep reward ~O(1) (§3.5).

### 10.1 Candidate enhancements

| ID | Enhancement | Mechanism (sketch) | Lifts §3.6 line | Benefit | Cost / risk |
|---|---|---|---|---|---|
| **E1** | Battery capacity fade (aging) | `E_cap = E_0·(1 − f_cal·age − f_cyc·Σthroughput)`. At 7-day episodes, within-episode fade is negligible → implement as **per-episode initial capacity** sampled from an aging schedule (domain randomization), not a per-step state. | "no battery calendar aging" | Long-horizon economics; SOC headroom shrinks with fleet age; cheap robustness via DR over capacity | Low. `capacity_mwh` is already per-step on the telemetry wire, so consumers already handle variable capacity. No new emitted field. |
| **E2** | SOC/temperature-dependent efficiency | Replace constants `η_ch=η_dis=0.97` with a clamped curve `η(SOC, T)` (low/high-SOC and cold-temp penalties), evaluated as a jnp polynomial/lookup. | "no SOC-dependent efficiency" | Agent learns an efficiency sweet-spot SOC band; more realistic losses feed `C_deg`/energy | Low. Localized to §3.2; two constants → one curve. Re-verify reward O(1). |
| **E3** | Battery & grid ramp-rate limits | `|P_t − P_{t−1}| ≤ R_max·Δt`, silent clip at the §3.6 #3/#8 stages — same style as the gas ramp already in §8.4. Adds `P_prev` state (gas already carries one). | "no ramp-rate limits" | Smoother, more deployable dispatch | **Low marginal value at Δt=1 h (D3):** a full power swing within one hour is usually physical, so the limit rarely binds. More valuable only under a future 15-min Δt. Defer. |
| **E4** | Weather/load stochastic coupling | A shared latent temperature/synoptic anomaly drives PV derate (`k_T`), load (CDD/HDD §4.2), and wind **together** (incl. hot + low-wind + high-load co-stress), replacing the current independent generators. | (tightens §4 generator realism; no new physics) | Correlated stress scenarios force the policy to hedge joint extremes — strong robustness/sim-to-real gain | Medium. **Changes the §4 synthetic year → must run on a separate seed/config; the D11 parity year stays bit-identical.** Touches generators only, not the jitted step. |
| **E5** | Forecast-error regime switching | Extend D6's linear `σ_h = σ_max·(h/H)` with a Markov **regime** (calm/stormy) modulating `σ_max`, and/or fat-tailed errors. Lives in `_get_obs` (D6), adds a regime state + key threading. | (extends D6 forecast-noise model) | Robustness to forecast blow-ups; the single biggest sim-to-real gap after "noise never applied" (already fixed by D6) | Low–medium. **Affects observations only, not physics/cost** — so per-step physics parity is unaffected; only the trajectory differs. |
| **E6** | Richer curtailment / grid-interaction | Time-varying PCC acceptance (exogenous grid-availability signal) and/or curtailment hysteresis, replacing the static `max_export_mw` (D5). | "no min-import contracts" (partial) | Realistic congestion/curtailment economics | **Higher + boundary risk.** Needs a new exogenous generator, and the realistic version drifts toward voltage/congestion modeling that §3.6 explicitly excludes. Keep strictly to a scalar time-varying export cap if taken at all. |

### 10.2 Decision (user-approved 2026-06-10, D17)

- **APPROVED for build — Tier 1:** **E2** (SOC/temperature efficiency) and **E5** (forecast regime noise). Cheap, localized to §3, parity-safe (neither changes the parity-year data); both small jittable additions. Build **after** the §3 reference baseline (D11); each as its own DECISION + contract + tests + parity regression.
- **Deferred candidates (revisit after Tier 1):** **E1** (battery aging as per-episode capacity DR) and **E4** (weather/load coupling — would need the separate-seed guard so D11 parity is untouched). Not greenlit now; no work until reconsidered.
- **Parked:** **E3** (ramp limits — weak at Δt=1 h, revisit only under a future 15-min Δt) and **E6** (dynamic grid — highest cost and the only candidate that risks the voltage/reactive boundary; if ever taken, restrict strictly to a scalar export-cap signal).

### 10.3 Per-enhancement deliverable (once approved)

Each approved enhancement ships as: a numbered LINEAGE **DECISION**; a site-YAML toggle (default OFF); its own `contracts/env/<enhancement>.md` + `tests/env/test_env_<enhancement>.py` with hand-computed expected values; application in **both** the JAX core and the NumPy reference (D11); a parity-regression test proving Gansu (all flags OFF) is unchanged; and, if it emits new telemetry, a minor schema bump with both reviewers' sign-off.

### 10.4 Open questions for the user

1. Which tier(s) to greenlight? (Recommend approving **Tier 1** now, scoping Tier 2/3 later.)
2. For E1, is per-episode capacity sampling (vs a true multi-year per-step fade) the right fidelity, given 7-day episodes?
3. For E4/E6, confirm the "separate seed, parity-year untouched" and "no voltage/reactive" guardrails are acceptable boundaries.

---

