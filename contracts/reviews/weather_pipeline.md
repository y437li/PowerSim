# Review Record — `weather_pipeline` (§12 real-weather pipeline)

**Contract:** `contracts/harness/weather_pipeline.md` v1.0.0
**Tests:** `tests/harness/test_harness_weather_pipeline.py`
**PR:** #92 · **Branch:** `feat/harness-weather-pipeline`
**Reviewer:** backend-reviewer (required — harness area)
**Gate:** contract + tests (step 3 of contract-first-dev)

---

## Stage 1 — Contract + Tests Gate

### backend-reviewer — REQUEST_CHANGES @ `35c3300`  (2026-06-12)
**Blocking:** §3.2 leap-year normalisation gave the wrong Feb-29 hour range — "1392–1415"
(= day 58 = **Feb 28**); the correct Feb-29 drop is **1416–1439** (day 59). The test
(`test_leap_year_drops_24_hours`) was already correct (`result[1416]==arr[1440]`) and its
docstring self-corrected, but the contract prose + the docstring's opening line were wrong and
would mislead an implementer coding to §3.2. Required: fix §3.2 → 1416–1439 + clean the docstring.

### backend-reviewer — APPROVE @ `9bb9a20`  (2026-06-12)
§3.2 fixed at `3ccfb91` (now "hours 1416–1439: Jan 744h + Feb 1–28 672h = offset 1416");
test docstring cleaned. Contract and test are consistent.

**Physics verified by hand (all correct):**
- Fitted shear `α = clip(ln(v100/v10)/ln(10), 0, 0.6)`: nominal 0.30103, clip-to-0.6, 0.14 calm fallback.
- Hub extrapolation `v_hub = v100·(hub/100)^α`: 7.883 (90m/0.14), 6.693 (120m/0.6), 0 at v100=0, =v100 at hub=100.
- Season boundaries: Mar1/day59→MAM, Jun1/day151→JJA, Sep1/day243→SON, Dec1/day334→DJF; counts 90/92/92/91 = 365.
- D11 synthetic-mode bit-parity with `generate_year`; bootstrap determinism; 8760×4 episode schema; optional `location`/`weather` blocks (backward-compat).

**Reviewer-added test cases (@ `9bb9a20`, `TestComputeFittedShear` / `TestExtrapolateToHub`):**

| Test function | Class | Rationale |
|---|---|---|
| `test_no_shear_ratio_one_alpha_zero` | `TestComputeFittedShear` | v100==v10 → ln(1)/ln(10)=0 → α=0 (boundary; must NOT take 0.14 calm fallback) |
| `test_nan_inf_input_uses_neutral_default` | `TestComputeFittedShear` | NaN/±Inf v10/v100 → α=0.14 (§3.1 stability flag; calm-v≤0 path was tested, NaN path was not) |
| `test_alpha_zero_hub_independent` | `TestExtrapolateToHub` | α=0 → v_hub=v100 for any hub (no shear ⇒ no height adjustment), checked at 90m & 120m |

**Approved test-file version:** `tests/harness/test_harness_weather_pipeline.py` @ `9bb9a20`
(developer cases + 3 reviewer cases above). Implementation may proceed.

### Implementation-stage notes (carried forward)
- Open-Meteo attribution confirmation is an implementation-stage blocker (contract §1 flag).
- Live-fetch tests (`TestLiveFetch`) require network — must be slow-marked / network-gated at impl time.
