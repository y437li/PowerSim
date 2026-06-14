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
| `POST /api/compare/recompute-finance` | instant (a)0 | synchronous |
| `POST /api/compare/run` | fast (a)1 + eval_needed (b)2 | async (returns run_id) |
| `GET /api/compare/run/{run_id}/status` | — | synchronous poll |
| `POST /api/compare/sizing-sweep` | sweep | async (returns run_id) |
| `GET /api/compare/sizing-sweep/{run_id}/status` | — | synchronous poll |

> **SC5 note:** `POST /api/compare/recompute-finance` was listed as SC5 in #132 v1.1.0
> `useFinanceRecompute` hook. This contract serves as both SC2 (full endpoint surface) and
> the SC5 definition — serving-engineer owns it.

**Not in scope here:**
- `GET /api/configs`, `POST /api/configs`, `POST /api/configs/{id}/fork` → SC1
  (`contracts/serving/config_library.md`)
- `GET /api/finance/compare` → separate serving contract (§13.12 / D39)
- WebSocket / live telemetry — workbench is batch-only (D42)
- `FinanceParamSet` → defined in `contracts/frontend/comparison_workbench.md §2.3`;
  this contract references it as the request body for `POST /api/compare/recompute-finance`
  and specifies the serving-layer mapping to `FinanceConfig`

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

### 2.3 `FinanceParamSet` → `FinanceConfig` mapping (serving-layer responsibility)

`POST /api/compare/recompute-finance` accepts `FinanceParamSet` (defined in
`contracts/frontend/comparison_workbench.md §2.3`). The serving layer maps each field to
the `FinanceConfig` dataclass (`contracts/finance/finance_engine.md §2.2`).

All `_pct` fields in `FinanceParamSet` are **percent** (e.g. 7.0 = 7.0%). The mapping
converts to decimal where `FinanceConfig` expects decimal.

| `FinanceParamSet` field | → `FinanceConfig` field | Notes |
|---|---|---|
| `risk_free_rate_pct.value` | `r_f_override = value / 100` | percent → decimal |
| `equity_risk_premium_pct.value` | `equity_risk_premium = value / 100` | percent → decimal |
| `beta.value` | `beta_unlevered = value` | dimensionless |
| `wacc_pct.value` | back-solve `r_f_override` so CAPM yields target WACC | See §2.3.1 |
| `hurdle_rate_pct.value` | `hurdle_rate_override = value / 100` | percent → decimal |
| `inflation_pct.value` | not in `FinanceConfig` v1 — reserved for price-path scaling | ignore in v1 |
| `gearing_pct.value` | `debt_toggle=True`; `target_de_ratio = g/(1-g)` where `g = value/100` | 60% → D/E 1.5 |
| `cost_of_debt_pct.value` | `r_d_override = value / 100` | percent → decimal |
| `loan_term_years.value` | `loan_term_years = value` | int |
| `horizon_years.value` | `horizon_years = value` | int |
| `tax_enabled.value` | `tax_toggle = value` | bool |
| `corporate_tax_rate_pct.value` | `tax_rate = value / 100` | percent → decimal |

Absent `FinanceParamSet` fields (not sent by the client) inherit `FinanceConfig` defaults.

#### 2.3.1 `wacc_pct` direct override rule

When `finance_params.wacc_pct.value` is sent AND differs from the CAPM-computed WACC
(given `risk_free_rate_pct`, `equity_risk_premium_pct`, `beta`), the serving layer
back-solves for `r_f_override` to make CAPM yield the target WACC:

```
r_f_target = wacc_target − (beta × ERP)   # where ERP = equity_risk_premium_pct/100
```

`r_f_override` is then set to `r_f_target` (decimal). This preserves CAPM structural
consistency without adding a `wacc_override` field to `FinanceConfig` (which is LOCKED).

If `wacc_pct` is at its default (not slider-dragged), the serving layer uses the CGB
curve interpolation path normally (no `r_f_override`).

> **CGB curve:** not sent by the client. The serving layer loads the configured CGB snapshot
> from the server-side config store (or uses the finance-engine default). This is
> server-managed state, not a per-request override.

### 2.4 `FinanceResultSummary` (response — pointer to canonical)

> **D45 SINGLE-SOURCE:** SC2 is a **PRODUCER** of `FinanceResultSummary`.  The canonical
> definition of every field, regime rule, and invariant lives in
> **`contracts/shared/finance_result_summary.md`** (locked D45 / PR #135).  SC2 MUST NOT
> redefine the schema locally.  Any SC2-specific field question → check #135 first.

Key producer obligations for this endpoint (from the canonical):

**Five distributional metrics (exactly — no others, Rule C / D45):**
- `irr_pct`, `npv_yuan`, `mirr_pct`, `lcoe_yuan_per_mwh`, `payback_discounted_yr`
- All null at R1; MetricPercentiles at R2; p50-only at R3 (INV-CE-19)

**`single_trajectory` — present at ALL M (D45 §3 rule 3):**
- Fields: `point_npv_yuan`, `max_drawdown_yuan`, `max_drawdown_year`, `worst_year_cf_yuan`
- `point_irr_pct` is ABSENT — IRR not computable from a single trajectory
- Previously SC2 incorrectly said "null at R2/R3" — superseded by D45 canonical

**`bootstrap_ci` — NPV-ONLY (Rule B / D45):**
- Present ONLY inside `npv_yuan` PercentileResult nodes
- MUST NOT appear in `irr_pct`, `mirr_pct`, `lcoe_yuan_per_mwh`, `payback_discounted_yr`

**`debt_metrics` block — both SCALAR (D45 / engine.py:679-680):**
```json
"debt_metrics": {
  "equity_irr_pct": 14.21,    // SCALAR percent (engine decimal ×100, NOT MetricPercentiles)
  "min_dscr":       1.836     // SCALAR bare ratio (NOT ×100, NOT MetricPercentiles) INV-CE-16
}
```
`debt_metrics` is `null` when debt is off OR at R1.

**Serving-layer unit mapping rules (SC2-specific):**
- Python `PercentileResult.irr` (decimal, e.g. `0.123`) → JSON `irr_pct.p50.value` (percent, `12.3`)
- Python `PercentileResult.mirr` (decimal) → JSON `mirr_pct.p50.value` (percent, ×100)
- Python `PercentileResult.payback_disc_yr` → JSON `payback_discounted_yr.p50.value` (years, unchanged)
- Python `ViewResult.equity_irr` (decimal) → JSON `debt_metrics.equity_irr_pct` (**SCALAR** percent, ×100)
- Python `ViewResult.min_dscr` (bare ratio, e.g. `1.86`) → JSON `debt_metrics.min_dscr` (**SCALAR** `1.86`, **NOT ×100**)
- Python `FinanceProvenance.wacc/r_f/r_e` (decimal) → `finance_assumptions.wacc/r_f/r_e` (decimal, unchanged)
- NPV, ¥, drawdown fields: pass through unchanged
- `p_npv_neg`, `p_irr_below_hurdle` (float ∈ [0,1]): pass through unchanged (NOT ×100)
- `PercentileResult.confidence` string passes through unchanged
- `sample_kind`: Python `"bootstrap"` → JSON `"bootstrap"`; Python `"empirical"` → JSON `"empirical"`.
  The string `"synthetic"` is NEVER emitted (forbidden by D42/#133 LOCK)

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

## 4. `POST /api/compare/recompute-finance`

Instant-tier (a)0 finance recompute: reuses a cached `PolicyEnsemble` (no dispatch),
maps `FinanceParamSet` → `FinanceConfig` (§2.3), returns `FinanceResultSummary` synchronously.
This is both SC2 and SC5 (see §1 scope note).

### 4.1 Request body

```json
{
  "eval_result_id":  "eval-uuid",    // string — key into PolicyEnsemble LRU cache
  "policy_id":       "policy-uuid",  // string — which policy in the ensemble to return results for
  "price_path_name": "flat_2026",    // string — must match a known PricePath.id
  "finance_params":  {               // FinanceParamSet (defined in comparison_workbench.md §2.3)
    "risk_free_rate_pct":      { "value": 2.6,  "scope": "common" },
    "equity_risk_premium_pct": { "value": 6.0,  "scope": "common" },
    "beta":                    { "value": 0.60, "scope": "common" },
    "wacc_pct":                { "value": 8.8,  "scope": "common" },
    "hurdle_rate_pct":         { "value": 8.0,  "scope": "common" },
    "horizon_years":           { "value": 20,   "scope": "common" },
    "tax_enabled":             { "value": false, "scope": "common" },
    "corporate_tax_rate_pct":  { "value": 25.0, "scope": "common" },
    "gearing_pct":             { "value": 0.0,  "scope": "per_config" },
    "cost_of_debt_pct":        { "value": 4.5,  "scope": "per_config" },
    "loan_term_years":         { "value": 20,   "scope": "per_config" }
  }
}
```

All `finance_params` fields are optional (absent = use server default). Unknown keys →
400 `VALIDATION_ERROR` (closed allow-set; see INV-CE-15).

`policy_id` selects which entry in `FinanceResult.per_policy` to serialize.

### 4.2 Response — 200 OK

```json
{
  "finance_result": { /* FinanceResultSummary §2.4 */ }
}
```

Processing order (serving layer):
1. Look up `eval_result_id` in PolicyEnsemble LRU cache → 404 on miss.
2. Map `finance_params` → `FinanceConfig` per §2.3 mapping table (including `wacc_pct`
   back-solve per §2.3.1 if provided).
3. Call `finance(ensemble, price_paths=[loaded_price_path], econ=loaded_econ, finance_config)`.
4. Serialize `FinanceResult.per_policy[policy_id]` → `FinanceResultSummary` (apply unit
   conversions from §2.4 rules; nested MetricPercentiles shape).
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

Shape matches `SizingSweepResult` in `contracts/frontend/comparison_workbench.md §2.7`
(#132 v1.1.0). `surface` is a scalar 2D array (metric values only); axes are explicit
separate arrays. This expands in the task #18 contract.

```json
{
  "run_id":                   "sweep-run-uuid",
  "status":                   "complete",    // "running" | "complete" | "error"
  "configs_done":             25,
  "configs_total":            25,

  // Explicit axis arrays (needed by the frontend to label surface cells)
  "energy_axis_mwh": [2.0, 6.0, 10.0, 14.0, 18.0],   // unit: MWh; length = energy_steps
  "power_axis_mw":   [1.0, 3.0, 5.0, 7.0, 9.0],       // unit: MW;  length = power_steps

  // Scalar surface — [energy_idx][power_idx]; null while running (INV-CE-13)
  "surface": [
    [800000.0, 900000.0, 1100000.0, 1200000.0, 1300000.0],
    [900000.0, 1050000.0, 1250000.0, 1350000.0, 1450000.0]
  ],
  "surface_metric": "npv_p50",               // "npv_p50" | "irr_p50" | "lcoe" (display label)
  "regime": "R2",                            // "R1" | "R2" | "R3" — from the sweep's M

  "recommended_energy_idx":   1,             // 0-indexed row in surface
  "recommended_power_idx":    2,             // 0-indexed column in surface
  "recommended_distribution_yuan": [         // R2 only (M≥50): NPV draw array for hover histogram
    1750000.0, 1820000.0, 1680000.0
  ],                                         // absent at R1/R3 or while running
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
| `MetricPercentiles.value` in `irr_pct`, `mirr_pct` | % (percent) | e.g. 12.3 means 12.3%; engine decimal ×100 (INV-CE-04) |
| `MetricPercentiles.value` in `npv_yuan` | ¥ (yuan) | no conversion; `bootstrap_ci` NPV-only (Rule B, D45) |
| `MetricPercentiles.value` in `lcoe_yuan_per_mwh` | ¥/MWh | no conversion |
| `MetricPercentiles.value` in `payback_discounted_yr` | years | discounted payback (engine `payback_disc_yr`); D45 rename |
| `debt_metrics.equity_irr_pct` | % (percent) scalar | **SCALAR** (not MetricPercentiles); engine decimal ×100 (D45) |
| `debt_metrics.min_dscr` | bare ratio (e.g. 1.86) scalar | **SCALAR NOT ×100** — DSCR coverage multiple (INV-CE-16, D45) |
| `*_yuan` (scalar fields) | ¥ (yuan) | no conversion |
| `*_mwh` | MWh | battery energy |
| `*_mw` | MW | battery power |
| `step` in PolicyRef | gradient steps | int |
| `m_draws` | count (dimensionless) | |
| `r_f`, `r_e`, `wacc` in `finance_assumptions` | decimal (0.026 = 2.6%) | NOT converted to % (INV-CE-05) |
| `risk_free_rate_pct`, `equity_risk_premium_pct`, `wacc_pct`, etc. in `FinanceParamSet` | % (percent) | serving layer /100 before passing to FinanceConfig |
| `tier_duration_estimate_s` | seconds | |
| `p_npv_neg`, `p_irr_below_hurdle` | probability ∈ [0,1] | NOT ×100; empirical frequencies |
| `bootstrap_ci.lo`, `bootstrap_ci.hi` | same unit as parent npv_yuan | NPV-only (Rule B, D45); absent from irr/mirr/lcoe/payback |

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
| INV-CE-15 | `finance_params` in `POST /api/compare/recompute-finance` uses a **closed allow-set**: the serving layer MUST reject any key not in the explicit `FinanceParamSet` field list (§2.3 mapping table) with 400 `VALIDATION_ERROR`. Examples of forbidden keys: `"wacc"` (must send `"wacc_pct"`), `"gamma"`, `"discount_rate"`, `"horizon_year"` (typo of `"horizon_years"`). |
| INV-CE-16 | `debt_metrics.min_dscr` in `FinanceResultSummary` is a **SCALAR bare ratio** (e.g. `1.86`), NOT percent, NOT MetricPercentiles (D45). A serving test MUST assert `debt_metrics.min_dscr < 10.0` for realistic projects (DSCR > 10 is economically implausible; any value > 100 reveals an erroneous ×100 conversion). |
| INV-CE-17 | `provenance.sample_kind` in `FinanceResultSummary` MUST be `"bootstrap"` or `"empirical"`. The string `"synthetic"` is FORBIDDEN (D42/#133 LOCK). A test MUST assert the emitted value is one of the two allowed strings. |
| INV-CE-18 | `single_trajectory` is NON-NULL at ALL M (D45 canonical §3 rule 3 — "present at ALL M; R1 headline, supplementary at R2/R3"). `single_trajectory` does NOT contain `point_irr_pct` — IRR not computable from a single trajectory. *(Previous SC2 rule "null at R2/R3" is superseded by D45.)* |
| INV-CE-19 | All 5 distributional metrics (`irr_pct`, `npv_yuan`, `mirr_pct`, `lcoe_yuan_per_mwh`, `payback_discounted_yr`) are ALL `null` at R1. Note: `payback_discounted_yr` replaces `payback_yr` (D45 rename — discounted value, engine `payback_disc_yr`). Emitting non-null `MetricPercentiles` at R1 is a producer bug. |
| INV-CE-20 | `cash_flow_series_yuan` is present ONLY at R2 (`m_draws ≥ 2`, `sample_kind="bootstrap"`). It MUST be absent (or `null`) at R1 and R3. |
| INV-CE-21 | `bootstrap_ci` is present ONLY in `npv_yuan` MetricPercentiles nodes (Rule B, D45). It MUST NOT appear in `irr_pct`, `mirr_pct`, `lcoe_yuan_per_mwh`, or `payback_discounted_yr` entries. |
| INV-CE-22 | `debt_metrics.equity_irr_pct` is a **SCALAR** (engine float mean ×100 → percent, D45 / engine.py:679-680), NOT a `MetricPercentiles` dict. The entire `debt_metrics` block is `null` when debt is off OR at R1. |

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
