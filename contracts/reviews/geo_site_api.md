# Review Record — `geo_site_api` (Workstream A serving surface, wizard stage ①)

**Contract:** `contracts/serving/geo_site_api.md` v1.0.0
**Tests:** `tests/serving/test_serving_geo_site_api.py`
**PR:** #94 · **Branch:** `feat/serving-geo-site-api`
**Reviewer:** backend-reviewer (required — serving area)
**Gate:** contract + tests (step 3 of contract-first-dev)

---

## Stage 1 — Contract + Tests Gate

### backend-reviewer — APPROVE @ `a363090`  (2026-06-12)

Strong contract. Verified the key invariants:
- **D32(i)/D18 single-source:** `POST /api/site/validate` calls `energy_go.env.config_validation.validate()` directly, no rule re-implementation (§23-25). Per-rule tests confirm rules surface; my added fidelity test pins exact passthrough.
- **HTTP 200 for invalid configs** (errors are domain data); **HTTP 400** only for malformed requests (missing/non-dict `site_config`).
- **`ValidationIssue` has no `severity` field** — matches LOCKED config_validation §2 (tested).
- **Units explicit:** ¥/MWh (prices), ¥/MW·month (demand rate), MW (generator power), MWh (battery energy), ¥/kW + ¥/kWh (economics).
- **Gansu values:** price_max 780 (critical_peak h=11, D8 minute=0), demand_rate 32000, band names valley/mid/peak/critical_peak. Bands use exclusive end_hour; month index 0–11.
- **Weather job:** opaque `job_id`, `queued→running→done|error` (done/error terminal), ¥-free summary (m/s, W/m², °C), synthetic `queued→done` without network; job-not-found → 404.
- **Tariff band path deviation** from tariff_model_schema §7.1 documented (§239).

**Reviewer-added test cases (@ `a363090`, `TestSiteValidate`):**

| Test function | Rationale |
|---|---|
| `test_passthrough_fidelity_matches_validate_directly` | D32(i): endpoint errors/warnings must EXACTLY equal a direct `validate()` call (same rule_id sets) — pins "never re-implements rules"; compares vs `validate()` directly so it survives rule evolution |
| `test_site_config_not_a_dict_returns_400` | the present-but-non-dict `site_config` trigger the contract specifies (only missing-key was tested); 400 must come from the endpoint guard, since `validate()` itself tolerates non-dict |

**Advisory (non-blocking):** not-found status codes are inconsistent — unknown tariff region → 400, unknown device model → 400, unknown weather job → **404**. The split is deliberate (each has a dedicated test) and defensible (fixed-catalog lookup → 400 "bad parameter" vs created-resource → 404 "gone"), but it's undocumented. **Recommend the contract state the rationale** (catalog-lookup vs created-resource) so frontend consumers know which to expect per endpoint — or unify to 404 for all path-resource-not-found. Serving-engineer's design call; does not gate.

**Approved test-file version:** `tests/serving/test_serving_geo_site_api.py` @ `a363090`
(developer cases + 2 reviewer cases above). **Implementation may proceed.**
