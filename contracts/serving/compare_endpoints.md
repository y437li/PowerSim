# Contract: Compare Endpoints — SC2

**Area:** serving (shared — frontend + backend)
**Feature:** compare_endpoints
**Contract version:** v1.0.0
**Status:** DRAFT — awaiting backend-reviewer + frontend-reviewer gate
**Branch:** `feat/serving-compare-endpoints`
**Owner:** serving-engineer
**Realizes:** LINEAGE D42 (comparison workbench two-mode discipline), D41 (battery
  config-level compare), D39 (regime display + distribution_valid honesty); resolves
  SC2 in `contracts/frontend/comparison_workbench.md §10 Q2`
**Reviewers:** backend-reviewer + frontend-reviewer (shared contract — both required;
  locked by rl-architect)
**REBUILD_SPEC refs:** §3 (env), §5 (training), §13 (finance)
**Depends on:**
- `contracts/finance/finance_engine.md` v1.0.0-draft (`FinanceResult`, `FinanceConfig`,
  `PolicyEnsemble`, `FinanceProvenance`)
- `contracts/frontend/comparison_workbench.md` v1.0.0-draft (consuming type definitions;
  JSON field names must match `FinanceResultSummary` exactly)
- Task #55 (`eval_result_extended.md`) — `ExtendedPolicyEvalResult` in `PolicyEnsemble`

> **D44 note (pending):** rl-architect flagged a future shared-action-API where re-sim-tier
> actions will hit serving endpoints. Until D44 is formally recorded in LINEAGE.md, the
> `POST /api/compare/run` response shape carries a `run_id` (not inline results) so the
> D44 action-routing layer can be grafted on without a schema change. Revisit once D44
> lands.

> **Batch sweeps (task #18 — pending):** `POST /api/compare/sizing-sweep` and its status
> endpoint are stubbed with minimal schemas here so the frontend contract is unblocked.
> They expand in the task #18 contract. The sizing-sweep run IDs live in a separate result
> store — they DO NOT use the PolicyEnsemble LRU cache.

---

## 1. Scope

This contract covers all six endpoints under `/api/compare/`:

| Endpoint | Tier | Sync/Async |
|----------|------|------------|
| `POST /api/compare/plan` | any (tier estimation) | synchronous |
| `POST /api/compare/finance` | instant (a)0 | synchronous |
| `POST /api/compare/run` | fast (a)1 + eval_needed (b)2 | async (returns run_id) |
| `GET /api/compare/run/{run_id}/status` | — | synchronous poll |
| `POST /api/compare/sizing-sweep` | sweep | async (returns run_id) |
| `GET /api/compare/sizing-sweep/{run_id}/status` | — | synchronous poll |

**Not in scope here:**
- `GET /api/configs`, `POST /api/configs`, `POST /api/configs/{id}/fork` → SC1
  (`contracts/serving/config_library.md`)
- `GET /api/finance/compare` → separate serving contract (§13.12 / D39)
- WebSocket / live telemetry — workbench is batch-only (D42)

---

## 2. Shared types (JSON schema)

All responses use `Content-Type: application/json`.
Units are stated on every numeric field — mixing MW/MWh/¥/% in the same payload without
annotation is a contract violation. **IRR, MIRR, equity IRR, and WACC are in percent
(e.g., `12.3` means 12.3%) in the JSON API.** The Python finance engine returns these as
decimals; the serving layer MUST multiply by 100 before serializing.

### 2.1 `PolicyRef` (request input)

```json
{
  "kind": "trained",          // "trained" | "baseline"
  "run_id": "uuid-string",   // present when kind="trained"
  "step": 1000000,            // present when kind="trained"; unit: gradient steps
  "agent_name": null          // present when kind="baseline" (e.g. "rule_based_peak")
}
```

### 2.2 `SharedScenario` (request input)

```json
{
  "price_path_name": "flat_2026",   // identifier; must match a known PricePath.id
  "m_draws": 50                      // number of weather draws; int ≥ 1
}
```

### 2.3 `FinanceConfigRequest` (user-adjustable FinanceConfig fields)

All fields are optional; absent fields inherit the server default (matching `FinanceConfig`
dataclass defaults in `contracts/finance/finance_engine.md §2.2`).

```json
{
  // CAPM inputs (§13.5b) — unit: decimal (e.g. 0.060 = 6.0% equity risk premium)
  "beta_unlevered":          0.60,
  "equity_risk_premium":     0.060,
  "country_risk_premium":    0.0,
  "r_f_override":            null,    // decimal | null — bypasses CGB curve; for testing only

  // Tax toggle (§13.9)
  "tax_toggle":              false,
  "tax_rate":                0.25,    // decimal (0.25 = 25%)
  "depreciation_years":      20,      // unit: years; int ≥ 1

  // Debt toggle (§13.9)
  "debt_toggle":             false,
  "target_de_ratio":         1.5,
  "credit_spread":           0.0125,  // decimal (0.0125 = 125 bps over 5yr LPR)
  "loan_term_years":         20,      // unit: years; int ≥ 1
  "r_d_override":            null,    // decimal | null — bypasses LPR + credit_spread; testing

  // Horizon / project
  "horizon_years":           20,      // unit: years; int ≥ 1
  "valuation_date":          "2026-01-01",   // ISO 8601 date string

  // Bootstrap CI (§13.10a)
  "bootstrap_seed":          42,
  "bootstrap_n_resamples":   2000,
  "bootstrap_ci_level":      0.90,    // decimal (0.90 = 90% CI)

  // Downside
  "hurdle_rate_override":    null,    // decimal | null — None → r_e (CAPM base)

  // View II (present = opt-in to View II delta)
  "baseline_policy_id":      null    // string | null — key in PolicyEnsemble.runs
}
```

> **CAPM vs WACC:** the frontend `FinanceSnapshot.wacc_pct` is a display-side computation;
> it is NOT an input field here. The serving layer computes WACC from CAPM inputs + CGB
> curve in `finance.discount`. Never accept a raw `wacc` override from the client.

> **CGB curve:** not sent by the client. The serving layer loads the configured CGB snapshot
> from the server-side config store (or uses the finance-engine default). This is server-managed
> state, not a per-request override. If no curve is configured, `r_f_override` can be used by
> tests to bypass curve interpolation.

### 2.4 `FinanceResultSummary` (response — canonical JSON schema for SC2)

This is the authoritative JSON schema; the frontend TypeScript type in
`contracts/frontend/comparison_workbench.md §2.3` must match it exactly.

Units: `_pct` fields = percent (e.g. 12.3 means 12.3%); `_yuan` fields = ¥;
`_yuan_per_mwh` fields = ¥/MWh; `_yr` fields = years.

```json
{
  // Regime (derived by serving layer from FinanceResult)
  "regime": "R2",                   // "R1" | "R2" | "R3"
  "sample_kind": "synthetic",       // "synthetic" | "empirical" — from PolicyEnsemble.sample_kind
  "m_draws": 50,                    // int ≥ 1 — from FinanceResult.M

  // Upside metrics — P50 always present (even at M=1, from single_trajectory); P90 null at R1/R3
  "irr_p50_pct":        12.3,       // unit: % — null when regime=R1 and no distribution
  "irr_p90_pct":        8.1,        // unit: % — null when regime=R1 or R3 (tail-suppressed)
  "npv_p50_yuan":       1500000.0,  // unit: ¥ — null only at M=1 (R1 point estimate below)
  "npv_p90_yuan":       800000.0,   // unit: ¥ — null when regime=R1 or R3
  "mirr_p50_pct":       9.5,        // unit: % — null when not computable
  "lcoe_yuan_per_mwh":  48.3,       // unit: ¥/MWh — single-scenario (P50 at M≥2; point at M=1)
  "payback_p50_yr":     7.2,        // unit: years — null when no distribution

  // R1 point estimates (present at all M; display-only at R2/R3 where P50 is preferred)
  "point_npv_yuan":     1500000.0,  // unit: ¥ — always present (single-scenario NPV)
  "point_irr_pct":      12.3,       // unit: % — always present when computable, else null

  // Downside risk — null when regime=R1 (distribution_valid=False)
  "downside_risk": {
    "worst_case_npv_yuan":    300000.0,  // unit: ¥ — min(NPV_m); labelled "worst of N years" in R3
    "best_of_n_npv_yuan":     null,      // unit: ¥ — max(NPV_m) in R3 only; null in R1/R2
    "p_npv_neg":              0.04,      // probability ∈ [0,1]; #{NPV_m < 0} / M (strict <)
    "p_irr_below_hurdle":     0.10,      // probability ∈ [0,1]; POPULATED AT R3 — this is an
                                         //   empirical frequency (#{IRR_m < hurdle}/M), not a tail
                                         //   percentile; it does not collapse at M≈10. null only at
                                         //   R1 (distribution_valid=False). PR #120/#121 confirmed.
    "cvar5_yuan":             null,      // unit: ¥ — null in R3 (k=ceil(0.05·M) relabels to worst-of-N)
    "max_drawdown_yuan":      -150000.0, // unit: ¥ ≤ 0; min(0, min_y cumCF_excl_CAPEX)
    "max_drawdown_year":      3,         // unit: years (1-indexed)
    "worst_year_cf_yuan":     -50000.0   // unit: ¥ — min annual net CF over all y and draws
  },                                     //   null when regime=R1

  // Debt-toggle-gated metrics (absent = null when debt_toggle=False in finance_config)
  // equity_irr_pct: percent (×100 of Python decimal), same ×100 rule as irr_p50_pct (INV-CE-04)
  // min_dscr: bare RATIO (e.g. 1.86) — NOT ×100. A value of 1.86 means DSCR 1.86× (INV-CE-16).
  //   An implementation that ×100-s "all finance numbers" would produce 186 and corrupt the display.
  "equity_irr_pct":  11.2,             // unit: % — null when debt_toggle=False; decimal×100
  "min_dscr":        1.86,             // unit: bare ratio — null when debt_toggle=False; NOT ×100

  // View II delta (present only when baseline_policy_id was set and baseline in ensemble)
  "view_ii_delta": {
    "npv_p50_delta_yuan": 250000.0,     // unit: ¥ — NPV(π) − NPV(baseline) at P50
    "irr_p50_delta_pct":  1.8           // unit: pp (percentage points)
  },                                     // null when View II not computed

  // Provenance (for display + cross-variant consistency checks)
  "provenance": {
    "seed":          42,
    "valuation_date": "2026-01-01",
    "r_f":           0.026,             // decimal — interpolated or overridden
    "r_e":           0.088,             // decimal — CAPM cost of equity
    "wacc":          0.088,             // decimal — WACC (= r_e when debt off)
    "price_path_ids": ["flat_2026"],
    "code_version":  "0.3.1"
  }
}
```

**Serving-layer mapping rules (IRR/MIRR to percent):**
- Python `PercentileResult.irr` (decimal, e.g. `0.123`) → JSON `irr_p50_pct` (percent, `12.3`)
- Python `PercentileResult.mirr` (decimal) → JSON `mirr_p50_pct` (percent)
- Python `ViewResult.equity_irr` (decimal) → JSON `equity_irr_pct` (percent, ×100) — null when debt off
- Python `ViewResult.min_dscr` (bare ratio, e.g. `1.86`) → JSON `min_dscr` (bare ratio, `1.86`, **NOT ×100**)
- Python `FinanceProvenance.wacc` (decimal) → JSON `provenance.wacc` (decimal, unchanged;
  not multiplied — the provenance block retains decimal form for precision)
- NPV and ¥ fields: pass through unchanged (no unit conversion)
- `p_irr_below_hurdle` (float ∈ [0,1]) → JSON `p_irr_below_hurdle` (float, unchanged; NOT ×100)

### 2.5 `ExecutionPlanVariant` (response)

```json
{
  "variant_id":                "workbench-local-uuid",
  "tier":                      "instant",    // ExecutionTier string (§2.1 of frontend contract)
  "tier_duration_estimate_s":  null,         // number | null — null for tier="instant"
  "reason":                    "finance-only diff; eval cached"  // human-readable string
}
```

### 2.6 `SizingSweepPoint` (response — stub; expands in task #18 contract)

```json
{
  "energy_mwh":     10.0,    // unit: MWh — battery energy capacity at this point
  "power_mw":       5.0,     // unit: MW — battery power rating at this point
  "npv_p50_yuan":   1200000.0,   // unit: ¥ — P50 NPV at this grid point; null if not run
  "irr_p50_pct":    11.8         // unit: % — P50 IRR; null if not run
}
```

---

## 3. `POST /api/compare/plan`

Estimates the execution tier for each variant given current server-side cache state.
**Pure read** — does not modify cache. Response is advisory: the serving layer may return
a different tier when `POST /api/compare/run` is eventually submitted (e.g. if the cache
was evicted between the plan call and the run call).

### 3.1 Request body

```json
{
  "variants": [
    {
      "variant_id":     "workbench-local-uuid",
      "config_id":      "server-config-uuid",
      "policy_ref":     { "kind": "trained", "run_id": "...", "step": 1000000 },
      "eval_result_id": "eval-uuid-or-null",
      "finance_config": {}       // FinanceConfigRequest — may be empty (all defaults)
    }
  ],
  "shared_scenario": { "price_path_name": "flat_2026", "m_draws": 50 }
}
```

### 3.2 Response — 200 OK

```json
{
  "plan": [
    {
      "variant_id":                "workbench-local-uuid",
      "tier":                      "instant",
      "tier_duration_estimate_s":  null,
      "reason":                    "eval cached; only finance assumptions differ"
    },
    {
      "variant_id":                "workbench-local-uuid-2",
      "tier":                      "eval_needed",
      "tier_duration_estimate_s":  120,
      "reason":                    "config_id changed; no compatible cached eval"
    }
  ]
}
```

### 3.3 Tier assignment logic

| Condition | Tier |
|-----------|------|
| `eval_result_id` in PolicyEnsemble LRU cache AND only `finance_config` differs | `"instant"` |
| `eval_result_id` NOT in cache but a compatible config + trained policy exists; finance re-run only needed | `"fast"` |
| `eval_result_id` NOT in cache; must run vmapped batch eval to produce ensemble | `"eval_needed"` |
| No trained policy compatible with `config_id` exists | `"retrain_required"` |
| `eval_result_id` is null AND `policy_ref.kind="baseline"` AND cache miss | `"eval_needed"` |

`tier_duration_estimate_s` is `null` for `"instant"` (< 1 s, synchronous) and `"retrain_required"`.

### 3.4 Errors

| HTTP | `code` | When |
|------|--------|------|
| 400 | `VALIDATION_ERROR` | Malformed body, unknown `price_path_name`, `m_draws < 1` |
| 404 | `CONFIG_NOT_FOUND` | `config_id` unknown |
| 500 | `INTERNAL_ERROR` | Unexpected |

---

## 4. `POST /api/compare/finance`

Instant-tier (a)0 finance recompute: reuses a cached `PolicyEnsemble` (no dispatch),
applies new `finance_config`, returns `FinanceResultSummary` synchronously.

### 4.1 Request body

```json
{
  "eval_result_id":  "eval-uuid",    // string — key into PolicyEnsemble LRU cache
  "policy_id":       "policy-uuid",  // string — which policy in the ensemble to return results for
  "price_path_name": "flat_2026",    // string — must match a known PricePath.id
  "finance_config":  {}              // FinanceConfigRequest (all fields optional)
}
```

`policy_id` selects which entry in `FinanceResult.per_policy` to serialize. If
`policy_id` is absent, the serving layer returns results for ALL policies as a dict
(field `"results_by_policy_id": { "policy_uuid": FinanceResultSummary }`). For the
comparison workbench single-variant case, `policy_id` MUST be present.

### 4.2 Response — 200 OK

```json
{
  "finance_result": { /* FinanceResultSummary §2.4 */ }
}
```

Processing order (serving layer):
1. Look up `eval_result_id` in PolicyEnsemble LRU cache → 404 on miss.
2. Merge `finance_config` overrides with server defaults to produce a `FinanceConfig`.
3. Call `finance(ensemble, price_paths=[loaded_price_path], econ=loaded_econ, finance_config)`.
4. Serialize `FinanceResult.per_policy[policy_id]` → `FinanceResultSummary` (apply %
   conversions from §2.4 rules).
5. Return 200.

Steps 3–5 are synchronous. Expected wall time < 500 ms at M=50 (pure Python; no JAX JIT).

### 4.3 Errors

| HTTP | `code` | When |
|------|--------|------|
| 404 | `EVAL_RESULT_NOT_FOUND` | `eval_result_id` not in LRU cache (never loaded or evicted) |
| 404 | `POLICY_NOT_IN_ENSEMBLE` | `policy_id` not a key in the cached ensemble's runs |
| 404 | `PRICE_PATH_NOT_FOUND` | `price_path_name` unknown |
| 400 | `VALIDATION_ERROR` | Malformed body; out-of-range finance_config field |
| 500 | `INTERNAL_ERROR` | Unexpected; `finance()` raised |

### 4.4 Error response shape

```json
{
  "code": "EVAL_RESULT_NOT_FOUND",
  "detail": "eval_result_id 'abc-123' not in cache. Re-run eval to repopulate."
}
```

---

## 5. PolicyEnsemble LRU cache (DECISION — team-lead 2026-06-14)

This section pins all cache semantics binding on the serving implementation.

### 5.1 Storage

- **Type:** in-memory Python `dict` used as a least-recently-used (LRU) cache.
- **Key:** `eval_result_id` (UUID string, opaque, assigned by the eval-run submission flow).
- **Value:** `PolicyEnsemble` object (finance engine input type, `contracts/finance/finance_engine.md §2.2`).
- **Capacity:** `ENERGY_GO_ENSEMBLE_CACHE_MAX` env var (string, parsed as int at startup);
  default `10`. Implementation MUST validate `int > 0`; invalid value → startup error with
  clear message. Capacity `1` is legal (discard-on-next-insert behavior).
- **Eviction:** strict LRU — the least-recently-accessed entry is evicted first when
  capacity is exceeded.

### 5.2 Access semantics

- **Read** (`POST /api/compare/finance`, `POST /api/compare/plan` cache-check):
  counts as an access; updates LRU recency.
- **Write** (`POST /api/compare/run` on completion): stores the newly computed ensemble;
  evicts if at capacity.
- **Eviction → 404:** a `POST /api/compare/finance` call for an evicted `eval_result_id`
  MUST return 404 `EVAL_RESULT_NOT_FOUND`. The frontend re-runs eval (`POST /api/compare/run`)
  to repopulate.

### 5.3 Persistence

**None.** Cache is in-process memory only. Server restart → empty cache → all `eval_result_id`
lookups return 404 until re-populated via `POST /api/compare/run`. The frontend MUST be
prepared to receive 404 and trigger re-run.

### 5.4 Isolation from batch sweeps

`POST /api/compare/sizing-sweep` (task #18) manages its own result store (separate from
this LRU cache). Sizing-sweep `run_id` strings MUST NOT be passed to
`POST /api/compare/finance` — if attempted, they will produce 404 (the sizing-sweep store
is not this cache). The serving layer MUST NOT write sizing-sweep results into the
PolicyEnsemble cache.

### 5.5 Thread safety

FastAPI runs under an async event loop with synchronous endpoint handlers for these
endpoints (they call synchronous `finance()`). The LRU cache MUST be protected by an
`asyncio.Lock` or a thread-safe collections wrapper if any handler is called from a thread
pool. Concurrent `POST /api/compare/finance` calls for the same `eval_result_id` are
allowed; the cache must not corrupt under concurrent access.

---

## 6. `POST /api/compare/run`

Triggers batch eval + finance for a set of variants. Each variant dispatches its policy
against `shared_scenario.m_draws` weather draws, producing a `PolicyEnsemble`, then runs
`finance()`. On completion the ensemble is stored in the LRU cache keyed by the variant's
`eval_result_id`.

### 6.1 Request body

```json
{
  "variants": [
    {
      "variant_id":   "workbench-local-uuid",
      "config_id":    "server-config-uuid",
      "policy_ref":   { "kind": "trained", "run_id": "...", "step": 1000000 },
      "finance_config": {}
    }
  ],
  "shared_scenario": { "price_path_name": "flat_2026", "m_draws": 50 },
  "run_label":       "My comparison run"    // optional string for display
}
```

### 6.2 Response — 202 Accepted

```json
{
  "run_id": "run-uuid-string"
}
```

The `run_id` is a fresh server-generated UUID unique per call. Poll
`GET /api/compare/run/{run_id}/status` for progress.

### 6.3 Errors

| HTTP | `code` | When |
|------|--------|------|
| 400 | `VALIDATION_ERROR` | Malformed body; `variants` empty; unknown `price_path_name`; `m_draws < 1` |
| 404 | `CONFIG_NOT_FOUND` | Any `config_id` unknown |
| 404 | `POLICY_NOT_FOUND` | Any `policy_ref.run_id` unknown (for `kind="trained"`) |
| 409 | `RUN_ALREADY_IN_PROGRESS` | Same logical run already running (reserved; not required in v1) |
| 500 | `INTERNAL_ERROR` | Unexpected |

---

## 7. `GET /api/compare/run/{run_id}/status`

Polling endpoint for a `POST /api/compare/run` submission.
**Frontend polls at 5000 ms intervals** (frontend contract §6 `useCompareRun`).

### 7.1 Response — 200 OK

```json
{
  "status":           "running",    // "running" | "complete" | "error"
  "variants_done":    1,            // int — how many variants have a FinanceResultSummary
  "variants_total":   3,            // int — total variants submitted
  "results_by_variant_id": {
    "variant-uuid-1": { /* FinanceResultSummary §2.4 */ }
  },                                // partial — only done variants; empty dict while running
  "error":            null          // string | null — set on status="error"
}
```

Partial results are emitted as variants complete — the frontend SHOULD display completed
variants even while others are still running.

### 7.2 Completion behavior

When `status = "complete"`:
- All variants have entries in `results_by_variant_id`.
- Each variant's `eval_result_id` is now a key in the PolicyEnsemble LRU cache.
- Subsequent `POST /api/compare/finance` calls for these `eval_result_id`s are served
  instantly until eviction.

### 7.3 Errors

| HTTP | `code` | When |
|------|--------|------|
| 404 | `RUN_NOT_FOUND` | `run_id` unknown (never submitted or server restarted) |
| 500 | `INTERNAL_ERROR` | Unexpected |

---

## 8. `POST /api/compare/sizing-sweep`

**STUB — expands in task #18 contract.** Minimal schema to unblock frontend contract.

### 8.1 Request body

```json
{
  "base_config_id":     "server-config-uuid",
  "policy_ref":         { "kind": "trained", "run_id": "...", "step": 1000000 },
  "shared_scenario":    { "price_path_name": "flat_2026", "m_draws": 50 },
  "finance_config":     {},
  "energy_steps":       5,      // int 2–20 (inclusive) — number of energy axis points
  "power_steps":        5,      // int 2–20 (inclusive) — number of power axis points
  "energy_range_mwh":   [2.0, 20.0],   // [min, max]; unit: MWh
  "power_range_mw":     [1.0, 10.0]    // [min, max]; unit: MW
}
```

`energy_steps` and `power_steps` are validated server-side: both must be in [2, 20].
Total configs = `energy_steps × power_steps` ≤ 400.

### 8.2 Response — 202 Accepted

```json
{
  "run_id":          "sweep-run-uuid",
  "configs_total":   25
}
```

---

## 9. `GET /api/compare/sizing-sweep/{run_id}/status`

**STUB — expands in task #18 contract.**

### 9.1 Response — 200 OK

```json
{
  "status":                   "complete",    // "running" | "complete" | "error"
  "configs_done":             25,
  "configs_total":            25,
  "surface": [
    [
      { "energy_mwh": 2.0,  "power_mw": 1.0, "npv_p50_yuan": 800000.0,  "irr_p50_pct": 9.1 },
      { "energy_mwh": 2.0,  "power_mw": 3.0, "npv_p50_yuan": 1100000.0, "irr_p50_pct": 10.8 }
    ],
    [
      { "energy_mwh": 10.0, "power_mw": 1.0, "npv_p50_yuan": 1400000.0, "irr_p50_pct": 11.5 },
      { "energy_mwh": 10.0, "power_mw": 3.0, "npv_p50_yuan": 1800000.0, "irr_p50_pct": 13.2 }
    ]
  ],                                          // null while running; present on complete
  // surface[i][j] = point at energy_range[i], power_range[j]
  "recommended_energy_idx":   1,              // 0-indexed row in surface
  "recommended_power_idx":    1,              // 0-indexed column in surface
  "recommended_distribution_yuan": [          // R2 only (M≥50): NPV draw array for histogram
    1750000.0, 1820000.0, 1680000.0
  ],                                          // null at R1/R3 or while running
  "error":                    null
}
```

### 9.2 Errors

| HTTP | `code` | When |
|------|--------|------|
| 404 | `RUN_NOT_FOUND` | `run_id` unknown |
| 500 | `INTERNAL_ERROR` | Unexpected |

---

## 10. Unit summary

| Field pattern | Unit | Notes |
|---|---|---|
| `*_pct` | % (percent) | e.g. `irr_p50_pct=12.3` means 12.3%; applies to IRR, MIRR, equity_irr |
| `*_yuan` | ¥ (yuan) | no conversion from engine (already in ¥) |
| `*_yuan_per_mwh` | ¥/MWh | LCOE, LCOS |
| `*_yr` | years | payback, horizon |
| `*_mwh` | MWh | battery energy |
| `*_mw` | MW | battery power |
| `step` in PolicyRef | gradient steps | int |
| `m_draws`, `M` | count (dimensionless) | |
| `r_f`, `r_e`, `wacc` in provenance | decimal (0.026 = 2.6%) | NOT converted to % |
| `equity_risk_premium`, `credit_spread` in FinanceConfigRequest | decimal | match Python dataclass |
| `tier_duration_estimate_s` | seconds | |
| `min_dscr` | bare ratio (e.g. 1.86) | **NOT ×100** — DSCR is a coverage multiple, not a percent |
| `p_npv_neg`, `p_irr_below_hurdle` | probability ∈ [0,1] | NOT ×100 — frequencies, not percentiles |

---

## 11. Invariants

| ID | Invariant |
|----|-----------|
| INV-CE-01 | `POST /api/compare/finance` MUST return 404 if `eval_result_id` is not in the LRU cache, regardless of whether that ID was ever valid. |
| INV-CE-02 | `ENERGY_GO_ENSEMBLE_CACHE_MAX` is read once at startup; changes require server restart. |
| INV-CE-03 | LRU capacity = 1 is legal and must not raise at startup or on operation. |
| INV-CE-04 | IRR, MIRR, equity IRR in JSON response are **percent** (×100 of the Python decimal). A serving test MUST assert that `irr_p50_pct == 12.3` when the engine returns `irr = 0.123`. |
| INV-CE-05 | `provenance.wacc`, `provenance.r_f`, `provenance.r_e` in JSON response are **decimal** (NOT ×100). |
| INV-CE-06 | `downside_risk` is `null` in the JSON response when `FinanceResult.distribution_valid=False` (regime R1). |
| INV-CE-07 | `best_of_n_npv_yuan` is `null` in `downside_risk` at R1 and R2; non-null only at R3. |
| INV-CE-08 | `cvar5_yuan` is `null` in `downside_risk` at R3; non-null only at R2. |
| INV-CE-09 | The sizing-sweep result store is isolated from the PolicyEnsemble LRU cache. A sizing-sweep `run_id` MUST NOT resolve in `POST /api/compare/finance`. |
| INV-CE-10 | `POST /api/compare/plan` is read-only — it MUST NOT evict or populate the LRU cache. |
| INV-CE-11 | `POST /api/compare/run` response is 202 (not 200 or 201) — work is submitted, not complete. |
| INV-CE-12 | `GET /api/compare/run/{run_id}/status` partial results include only variants that have finished; variants still running MUST NOT appear in `results_by_variant_id`. |
| INV-CE-13 | `surface` in sizing-sweep status is `null` while `status="running"` (no partial surface). |
| INV-CE-14 | `finance_config` fields `r_f_override` and `r_d_override` are test-only bypasses; the implementation MAY log a warning when they are set in non-test mode (but MUST NOT reject them). |
| INV-CE-15 | `FinanceConfigRequest` uses a **closed allow-set**: the serving layer MUST reject any request body key that is not in the explicit allow-list of §2.3 field names with 400 `VALIDATION_ERROR`. `"wacc"` is the archetypal forbidden key (must be caught); any other unknown key (e.g. `"gamma"`, `"discount_rate"`, a typo) must also be rejected. |
| INV-CE-16 | `min_dscr` in `FinanceResultSummary` is a **bare ratio** (e.g. `1.86`), NOT percent. A serving test MUST assert `min_dscr < 10.0` for realistic projects (DSCR > 10 is economically implausible; any value > 100 reveals an erroneous ×100 conversion). |

---

## 12. Deliberate deviations

| Code | What | Why |
|------|------|-----|
| DV-CE-1 | `POST /api/compare/finance` is synchronous (blocks until `finance()` completes) | `finance()` at M=50 is pure Python < 500 ms; async would add complexity for no benefit |
| DV-CE-2 | Polling-only for async runs (no WebSocket) | D42: workbench is batch-only; 5 s poll interval is sufficient; WebSocket would require separate infra |
| DV-CE-3 | `POST /api/compare/run` returns 202 (not 200) | Matches HTTP semantics for accepted-but-not-complete operations; future D44 action-routing layer can hook here |
| DV-CE-4 | WACC not accepted as input | Security and correctness: accepting raw WACC would bypass the CAPM consistency check; must derive from auditable CAPM inputs |
| DV-CE-5 | `surface` in sizing-sweep is complete-only (no partial) | D42 §7.4: partial surface is NOT shown — only complete; avoids UI flicker on an incomplete grid |

---

## 13. Out of scope (v1)

- Config library endpoints (`/api/configs/*`) — SC1
- `GET /api/finance/compare` (§13.12 bulk compare) — separate serving contract
- Websocket for real-time run progress — never (D42)
- Saved/named comparison persistence (`run_label` stored and retrievable) — v2
- Sizing-sweep full schema (energy_steps × power_steps grid API + histogram) — task #18
- Cross-variant CRN enforcement at the serving layer (ensured by workstream-C; serving
  asserts structural M-equality only)

---

*contracts/serving/compare_endpoints.md — v1.0.0 — serving-engineer — 2026-06-14*
*SC2: resolves Q2 from contracts/frontend/comparison_workbench.md §10*
*Decisions: D42, D41, D39, D34*
