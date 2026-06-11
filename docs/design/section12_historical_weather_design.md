# §12 Design Study — Historical-Data-Driven Weather/Generation Simulation

> **Status:** DESIGN ONLY — no implementation, no contract. **Review gate:** team-lead (Fable) must post explicit design approval before any contract/implementation work proceeds (task #52).
> **Owners:** rl-architect (lead) · jax-env-engineer (domain).
> **Relationship to §12:** the merged §12 spec (`docs/spec/section_12_weather_pipeline.md`) already specifies *direct replay of one historical year* (Open-Meteo → §4 device-array, offline). This study sits **above** that: how to turn the **finite** historical record into **unlimited** realistic years. §12's data pipeline becomes the **data foundation + validation oracle** for whatever generator we choose.

---

## 1. Problem framing

The §4 synthetic generators produce **unlimited** years but are **hand-tuned** (μ_w=6, A_d=2, ρ=0.95, …) and **per-variable independent** — they are not calibrated to any real site and do not reproduce the *joint* statistics a real plant sees. §12 direct-replay produces **realistic** years but only the **finite** historical record (≈ decades). Task #52 asks for the intersection: **unlimited AND realistic**, calibrated to history.

The central tension: **a finite sample (history) must seed an infinite generator without (a) merely memorizing the sample, (b) destroying the joint/temporal structure that makes it realistic, or (c) leaving the device-side §7 generation path.**

### 1.1 Realism is multi-dimensional (the requirement set)

A generator is "realistic" only if it reproduces *all* of these — getting marginals right while breaking correlations is a common and dangerous failure (a policy over-fits to a structure the real world doesn't have):

| Dimension | Why it matters for the RL policy |
|---|---|
| **Marginals** (per-variable distributions) | Capacity-factor and load magnitude must be right or costs/revenues are biased. |
| **Diurnal + seasonal structure** | The TOU-arbitrage and solar-routing policy is fundamentally time-of-day/season aware. |
| **Temporal autocorrelation / ramp rates** | Battery dispatch is a sequential problem; ramp distributions drive SOC headroom decisions. AR(1)-Gaussian ramps are thin-tailed; real fronts produce fat-tailed ramps. |
| **Cross-variable correlation** | Wind, solar, temperature, and load **co-move** (a stagnant high → calm + clear + hot + high CDD load). Independent sampling manufactures hedging opportunities (e.g., "wind covers the evening peak") that do not exist, and the policy learns to exploit a phantom. **This is the hardest and most important dimension.** |
| **Tail / persistence events** | A two-week wind calm or a multi-day heat wave is where the battery either saves the day or the policy fails expensively. Generators that mean-revert too fast never produce these. |

### 1.2 Hard constraint — §7 device-side generation

Per §7, training `vmap`s 2k–10k envs and pre-generates each env's year as a **device array** indexed by `lax.dynamic_slice`; the goal is 10⁶–10⁷ env-steps/sec with **zero host↔device copies**. Any generator that wants to feed *unlimited* years to *vmapped* training must therefore be one of:
- **(i) materialize-then-index:** produce a (possibly large) device array offline and let each env sample slices on-device (no per-step generation), or
- **(ii) on-device generative:** a jittable/vmappable sampling function that synthesizes a fresh year per (env, seed) inside the device program.
A generator that requires host-side Python/NumPy per episode (or, worse, network I/O) is **disqualified** from the hot training path — it can only run as an offline pre-build. This single constraint reshapes the ranking below.

---

## 2. Candidate approaches

Each is assessed mechanism-first, then against the §1.1 dimensions and the §1.2 device constraint.

### (a) Parametric fit of the §4 generators (+ unlimited sampling)
**Mechanism:** keep the §4 functional forms but **fit** their parameters to historical data: seasonal-Weibull for wind speed, AR-coefficients from the empirical ACF, cloud-regime probability/depth from the irradiance record, CDD/HDD α/β by regression of load on temperature. Sample unlimited years by drawing new noise.
- **Marginals:** good (Weibull/EVT-fit per variable). ✓
- **Diurnal/seasonal:** native (the sinusoids). ✓
- **Ramps:** mediocre — AR(1)-Gaussian innovations give thin-tailed, fast-mean-reverting ramps. ✗
- **Cross-variable:** **poor by default** — §4 draws wind/solar/temp/load from *independent* processes. Fixable only by upgrading to a **VAR** (vector autoregression: one correlated multivariate innovation vector instead of N independent AR(1)s) and conditioning solar/load on temperature. That upgrade is real work and pushes the model toward (d). ✗→◐
- **Tails/persistence:** **poor** — Gaussian AR(1) mean-reverts in hours; it cannot hold a two-week calm. EVT marginals fix the *magnitude* of single-hour extremes but not their *clustering*. ✗
- **Device/unlimited:** **excellent** — pure sinusoid + recursive AR(1) array math, fully jittable/vmappable; generate unlimited years **on-device** (vmap over seeds), zero host I/O. This is the §7-native path and is essentially what §4 already is. ✓✓
- **Validatability:** standard (KS on marginals, ACF match) — but cross-corr/extreme tests will *fail* unless the VAR+regime upgrade is added.
- **Net:** the cheapest, most device-friendly, genuinely-unlimited option, but its independence/Gaussian assumptions miss the two dimensions we care about most (cross-correlation, persistent extremes). Useful as a **fast device-native fallback / domain-randomization source**, not as the realism answer — unless extended into (d).

### (b) Block bootstrap / resampling of historical segments
**Mechanism:** cut the multi-year historical record into contiguous **blocks** (whole days or weeks), then stitch randomly-drawn, **seasonally-stratified** blocks into new years. Each block is *real multivariate data*, so all within-block structure is correct by construction.
- **Marginals / diurnal / seasonal:** preserved by construction (with seasonal strata: sample summer blocks into summer). ✓✓
- **Ramps:** real *within* blocks ✓; artificial discontinuities at block boundaries — mitigated by **day-aligned (midnight) blocks** (the natural diurnal low, where ramps are smallest) and optional short overlap-blend. ◐→✓
- **Cross-variable:** **excellent** — it is real joint data; wind/solar/temp/load co-move exactly as observed, for free. ✓✓ (Directly solves the hardest dimension.)
- **Tails/persistence:** preserves events **shorter than the block** (a real heat-wave day reappears). **Cannot synthesize a persistent event longer than the longest observed one**, and cannot extrapolate beyond the historical extremes (no new record). Longer blocks capture longer extremes but reduce recombination variety. ◐
- **Device/unlimited:** **excellent and underappreciated** — the entire multi-year array is *tiny* (30 yr × 8760 h × ~4 vars × 4 B ≈ **4.2 MB**) and lives on-device permanently; each env samples a random sequence of block start-indices and gathers them via vmapped `lax.dynamic_slice`. Pure index math, jittable, zero host I/O, and **combinatorially unlimited** (the number of distinct stitched years vastly exceeds any training run). It reuses §12's data pipeline almost verbatim (just multi-year). ✓✓
  - *Device mechanics (domain-reviewed, jax-env-engineer):* the JAX rule is **slice sizes static, start indices dynamic**. Fix block length `B` and blocks-per-episode `K = episode_len / B` (both compile-time constants); each env holds a static-shaped `(K,)` array of random start-indices and gathers via `lax.scan` of `lax.dynamic_slice` — static-shaped throughout, independent per env under `vmap` (each env's own RNG key → own index array). Start indices are sampled **with replacement** (standard bootstrap — repeated blocks are intentional, not a bug).
  - *Block-length / divisibility:* `B = 24` (day-aligned) divides the 8760-h year **exactly** (365 blocks) and preserves the within-day diurnal structure (temperature cycle, solar ramp) — the physically dominant correlation. `B = 168` (week, for weekday/weekend load structure) does **not** divide evenly (52×168 = 8736, 24 h short) and needs an explicit fixed-schema remainder (e.g. always 52 week-blocks + 1 day-block, separate RNG draws, still static-shaped). → **default day-aligned `B=24`; week-aligned a named config option with the 52+1 schema documented in the contract.**
- **Validatability:** trivial — marginals/ACF/cross-corr match by construction; the *only* thing to test is stitching artifacts (a boundary-ACF dip), which is directly measurable and tunable via block length/blend.
- **Net:** preserves the two hardest dimensions (cross-correlation, real ramps) *for free*, is fully §7-device-native and unlimited, reuses §12, and is the easiest to validate. Its one genuine gap is **extreme extrapolation** (can't exceed observed persistence/magnitude).

### (c) Direct historical replay through the §3.1 power-curve models
**Mechanism:** §12 as specified — replay actual historical years (one per (lat, lon, year)) through the §3.1 wind/PV curves.
- **All realism dimensions:** perfect (it *is* the real world). ✓✓
- **Unlimited:** **no** — bounded by the historical record. Fails the core task-#52 requirement.
- **Device/unlimited:** §12 already materializes the device array; device-fine but finite.
- **Net:** **not a candidate for unlimited generation — it is the data foundation and the validation oracle.** Every other approach is judged by how well its synthetic years match held-out historical replay years. §12 stays as-is and is a *prerequisite* (it supplies the calibrated multi-year array the others sample/fit).

### (d) Regime-switching Markov models
**Mechanism:** identify a small set of weather **regimes** (e.g., stagnant-high, frontal-passage, calm-cold, storm) by clustering/HMM on historical features; a Markov chain governs regime transitions and **dwell times**; within each regime, sample from that regime's *joint* (correlated) distribution.
- **Marginals / diurnal / seasonal:** good — regimes are seasonally conditioned, diurnal modeled within-regime. ✓
- **Ramps:** **good→excellent** — regime *transitions* generate the fat-tailed ramps (a frontal passage = a real wind ramp) that AR(1) misses. ✓✓
- **Cross-variable:** **good** — within-regime joint distributions encode the co-movement; regimes are physically the *cause* of co-movement (a stagnant high *is* calm+clear+hot). ✓
- **Tails/persistence:** **best of the parametric family** — fitted **dwell-time distributions** can synthesize persistent calms/heat-waves, *including durations not exactly in the record* (sample a longer dwell). This is the one thing (b) cannot do. ✓✓
- **Device/unlimited:** **moderate** — a sequential categorical regime draw (`lax.scan` with a per-step `jax.random.categorical`) plus parametric within-regime sampling; jittable and vmappable, heavier than (a)/(b) but feasible; genuinely unlimited. ◐→✓
  - *Device mechanics (domain-reviewed, jax-env-engineer):* the `lax.scan` carry is **`(x_t, regime_t, rng_key)`**; regime `t+1` is drawn from `row[regime_t]` of a fixed Markov transition matrix; per-regime parameters are selected with `jnp.where` over all regimes (**not** a Python `if` — the §7 no-data-dependent-branching rule). Cost is dominated by per-step RNG key splitting; negligible arithmetic for ≤5 regimes × ~4 vars.
- **Validatability:** standard but richer — must match regime frequencies, the transition matrix, dwell-time distributions, *and* within-regime marginals/cross-corr.
- **Net:** the strongest *parametric* realism (extremes via dwell times, ramps via transitions, cross-corr via regime joints) and it can extrapolate beyond observed extremes. Cost: real modeling effort (regime identification + fitting) and a more complex device generator.

### (e) Copula / VAE / GAN / diffusion (learned joint generative models)
**Mechanism — copula:** fit marginals (EVT-aware) separately, then a copula (Gaussian / t / vine) for the cross-variable dependence; sample correlated uniforms → invert through marginals. **Mechanism — VAE/GAN/diffusion:** learn a generative model of weather segments/years.
- **Cross-variable:** copula is *purpose-built* for this and uniquely captures **tail dependence** (t/vine copula → joint extremes: calm-and-clear together). ✓✓ VAE/GAN learn it implicitly. ✓
- **Temporal/ramps:** copula is fundamentally **cross-sectional** — it needs a *separate* temporal layer (copula on AR residuals, or a temporal/vine copula) to get ACF/ramps; that's an extra model. ✗→◐ Sequence VAE/diffusion can model temporal but only with care and data.
- **Diurnal/seasonal:** requires time-conditioned copulas / conditioning inputs — added complexity.
- **Tails:** copula with EVT marginals + t-copula → strong joint tails ✓; **VAE/GAN are notoriously weak at tails** (mode-covering smooths exactly the extreme events we care about). ✗ (for NN variants)
- **Device/unlimited:** Gaussian-copula sampling (correlated normal → inverse-CDF) is device-feasible; vine copulas and especially **embedding a trained NN decoder in the env's data path** are heavier and add a model-artifact dependency + training/maintenance burden to a codebase whose env is otherwise pure array math. Unlimited ✓ but at real complexity cost.
- **Validatability:** copula goodness-of-fit is principled (cross-corr, tail-dependence coefficients λ); **VAE/GAN are hard to validate** (no clean likelihood for GANs; mode-collapse/coverage concerns) — a poor fit for a project whose whole ethos is "assert hand-computed expected numbers."
- **Net:** the **copula** is a principled *complement* for cross-variable + joint-tail dependence, but it is not natively temporal and is largely *subsumed* by (b)/(d) for our purposes (both already deliver real or regime-joint cross-correlation). **VAE/GAN/diffusion are over-powered, data-hungry, weak-tailed, hard-to-validate, and introduce a trained model into the data pipeline** — disproportionate for a research rebuild. Park the NN variants; keep copula in reserve only if joint-tail-dependence stress testing later proves inadequate.

---

## 3. Comparison matrix

Scoring: ✓✓ strong · ✓ good · ◐ partial/with-work · ✗ weak. (c) is the oracle, not a generator.

| Dimension | (a) Param-fit/VAR | (b) Block bootstrap | (d) Regime-switch | (e) Copula | (e) VAE/GAN |
|---|---|---|---|---|---|
| Marginals | ✓ | ✓✓ | ✓ | ✓ | ◐ |
| Diurnal/seasonal | ✓✓ | ✓✓ | ✓ | ◐ | ◐ |
| Ramp rates | ✗ | ✓ | ✓✓ | ◐ | ◐ |
| **Cross-variable corr** | ✗→◐ | ✓✓ | ✓ | ✓✓ | ✓ |
| **Tails / persistence** | ✗ | ◐ | ✓✓ | ✓ (copula tail) | ✗ |
| Extrapolate beyond record | ✓ | ✗ | ✓ | ✓ | ✓ |
| **§7 device-side / unlimited** | ✓✓ | ✓✓ | ◐→✓ | ◐ | ✗→◐ |
| Validatability | ✓ | ✓✓ | ✓ | ✓ | ✗ |
| Implementation effort | low | low–med | med–high | med–high | high |
| Reuses §12 pipeline | partial (fit) | **yes (directly)** | partial (fit) | partial (fit) | partial |

---

## 4. Cross-cutting concerns

### 4.1 Data sources & licensing (extends §12.1)
Block-bootstrap and any fitting need a **multi-decade, multi-variable, hourly** record (§12 currently pulls a single year). Candidates:

| Source | Coverage | Access | License (confirm before impl) | Role |
|---|---|---|---|---|
| **Open-Meteo historical** (ERA5-backed) | hourly, global, ~1940→present | free, **no key** | Open-Meteo CC-BY-4.0; underlying ERA5 is Copernicus (attribution) | **Primary** — multi-year pull, same API §12 already uses |
| **ERA5 (CDS API)** | hourly, global, 1940→ | free, **registration + CDS license accept** | Copernicus Licence (attribution; redistribution terms) | Cross-check / authoritative reanalysis if Open-Meteo coverage gaps |
| **NASA POWER** | hourly/daily, global | free, no key | **public domain** (US Gov) | Solar-irradiance cross-validation |
| **Plant SCADA** | site-exact, real generation | proprietary, NDA | site-owner proprietary | **Validation gold-standard if obtainable** — never the public pipeline |

Licensing note: exact redistribution terms (can we cache and ship a derived array?) **must be confirmed before implementation** — caching for local research use is clearly fine; bundling a derived multi-year array into the repo needs the attribution/redistribution check. This is a gate item for the contract stage, flagged here.

### 4.2 Validation methodology (the doc's most important deliverable)
"Synthetic ≈ historical" must be *proven*, not asserted. The battery, run on held-out historical years (train/fit on years 1…N−k, validate against the held-out k):

1. **Marginals:** per-variable KS / Anderson–Darling; **EVT tail fit** (Generalized Pareto over a high threshold) → compare tail quantiles (e.g., P99 wind, P99 temperature), not just the body.
2. **Temporal:** ACF/PACF overlay per variable; **ramp-rate distribution** (Δ over 1 h and 3 h) KS test — explicitly test the fat-tailed ramps.
3. **Cross-variable:** full correlation matrix (Pearson **and** Spearman) synthetic vs historical; **tail-dependence coefficients** λ_upper/λ_lower for the safety-critical pairs (wind↔solar, temp↔load) — does the generator reproduce *joint* extremes?
4. **Persistence / extremes:** peaks-over-threshold and run-length distributions — e.g., distribution of "consecutive hours of sub-3 m/s wind" (calm spells) and "consecutive CDD-heavy days" (heat waves); compare return-level curves.
5. **Energy-relevant (the decisive test):** push synthetic and historical through the §3.1 power curves → compare **generation duration curves**, **capacity-factor distributions**, and finally the **train-on-synthetic / evaluate-on-held-out-historical** generalization gap of an actual SAC policy. *If the policy's cost on held-out real years ≈ its cost on synthetic years, the generator is validated for its actual purpose.* This last test is the one that matters most and the one all others are proxies for.

Acceptance threshold and the exact statistics are a **contract-stage** decision; this study fixes the *methodology*, not the pass/fail numbers.

---

## 5. Recommendation (phased)

**A single approach is the wrong answer; the right answer is a small layered stack with a clear primary.** Rationale: the dimensions trade off against each other, and the §7 device constraint plus the "validatable / low-risk" ethos of this rebuild strongly reward real-data reuse over learned models.

1. **Foundation (prerequisite): (c)/§12 multi-year.** Extend §12's pull from one year to a multi-decade Open-Meteo/ERA5 record for the site, producing the same §4-format device array (now multi-year). This is the data substrate *and* the validation oracle. No new modeling.

2. **v1 primary generator: (b) seasonally-stratified block bootstrap.** It uniquely delivers the two hardest dimensions — **cross-variable correlation and real ramps — for free** (it is real joint data), is **fully §7-device-native and combinatorially unlimited** (random `dynamic_slice` over a ~4 MB on-device multi-year array, vmapped), reuses §12 almost verbatim, and is the **easiest to validate** (most statistics match by construction; only stitching artifacts need testing). It is the best realism-per-unit-risk by a wide margin.

3. **v2 upgrade for extreme-event coverage: (d) regime-switching.** Block-bootstrap's one real gap is it cannot synthesize persistence *longer or more severe than observed*. When stress-testing the policy against tail events (record calms/heat-waves) becomes a priority, add the regime-switching generator (fitted dwell-time distributions extrapolate persistence). Phase it after v1 because it carries real fitting/identification effort.

4. **Always-available device-native fallback: (a)-as-VAR.** Keep a parametric, fully-on-device generator (the §4 lineage, upgraded to a correlated VAR with data-fit parameters) for (i) the **Gansu parity baseline** (D11 stays synthetic, and parity must never depend on a data download), (ii) **domain randomization beyond observed data**, and (iii) environments without network/data access. It is the cheap, robust, infinitely-available path; it is just not the realism *target*.

5. **Parked: (e) VAE/GAN/diffusion.** Over-powered, data-hungry, weak-tailed, hard-to-validate, and they embed a trained model into an otherwise-pure data pipeline — disproportionate. Keep **copula** in reserve *only* as a targeted add-on if (b)+(d) later prove insufficient at **joint-tail dependence**.

**One-line recommendation:** *Multi-year §12 as the oracle → block-bootstrap (b) as the unlimited v1 (device-native, real cross-correlation, easiest to validate) → regime-switching (d) as the v2 for extreme extrapolation → VAR-parametric (a) as the always-on device fallback; NN-generative parked.*

### 5.1 Why not just (a) (least effort)?
Because (a)'s independence + Gaussian-AR(1) assumptions break the **cross-variable correlation** and **persistent-extreme** dimensions — precisely the two that make a weather model *useful* for a dispatch policy (phantom hedges, no calm weeks). Fixing (a) to address them converges on a VAR + regime structure, i.e. (d). (a) earns its place as the device fallback, not the primary.

### 5.2 Why not lead with (d) (most realistic parametric)?
(d) is strictly more realistic for extremes, but it costs real regime-identification effort and a heavier device generator, and **(b) already captures cross-correlation and real ramps more faithfully** (real data vs. a fitted regime joint) at a fraction of the effort and risk. Lead with the high-confidence, low-risk (b); add (d) only for the specific gap (b) cannot close.

---

## 6. Decisions requested from the reviewer (team-lead / Fable gate)

Before this becomes a contract, please confirm/redirect:
1. **Endorse the phased stack** (b primary → d for extremes → a-VAR fallback → e parked), or prefer a different primary?
2. **Multi-year data source:** Open-Meteo multi-decade (free/no-key, §12-consistent) as primary, with the redistribution-terms check as a contract gate?
3. **Block granularity prior:** day-aligned `B=24` (seasonally stratified) as the v1 default — it divides the 8760-h year exactly (365 blocks), preserves the dominant diurnal correlation, and is the cleanest under `lax.scan` (domain-reviewed). Week-aligned `B=168` as a named config option (captures weekday/weekend load structure + longer extremes, at the cost of the 52+1 remainder schema and less recombination variety). Endorse day-default, or prefer week-default?
4. **Validation bar:** is the **train-on-synthetic / eval-on-held-out-historical generalization gap** accepted as the *decisive* acceptance test (with the statistical battery as supporting evidence)?
5. **Scope of v1:** ship (b) + multi-year §12 only, and defer (d)/(a-VAR) to follow-on tasks — or bundle?

---

## 7. Explicitly out of scope here
- No implementation, no `contracts/` entry, no API/format changes. The §4 device-array format and the pure jitted `step` are **unchanged** by anything proposed (every approach emits that same array).
- The Gansu parity case (D11) **remains synthetic-only**; nothing here touches it.
- Pass/fail thresholds, exact statistic choices, and the contract for the chosen generator are **downstream of team-lead design approval** (the review gate for task #52).
