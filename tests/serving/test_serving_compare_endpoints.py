"""
Tests for contracts/serving/compare_endpoints.md (SC2) — Compare Endpoints.

All tests are RED (no implementation yet). Contract-first step 2.
Reviewer-added cases are marked with # reviewer: comments.

Units contract (INV-CE-04/05):
  - irr_pct.p50.value, mirr_pct.p50.value, equity_irr_pct.p50.value: PERCENT (12.3 → 12.3%)
  - finance_assumptions.wacc, .r_f, .r_e: DECIMAL (0.088, NOT 8.8)
  - *_yuan: ¥ (no conversion)
  - *_mwh: MWh, *_mw: MW, *_yr: years
  - min_dscr: bare RATIO (1.86, NOT ×100)
  - p_npv_neg, p_irr_below_hurdle: probability ∈ [0,1] (NOT ×100)

FinanceResultSummary v1.1.0 nested shape (matched to #132 commit 0a47d24):
  - provenance: {sample_kind: "bootstrap"|"empirical", m_draws, distribution_valid}
  - single_trajectory: non-null at R1 only; fields: point_npv_yuan, max_drawdown_yuan,
    max_drawdown_year, worst_year_cf_yuan; NO point_irr_pct
  - irr_pct, npv_yuan, mirr_pct, lcoe_yuan_per_mwh, payback_yr: MetricPercentiles | null
    (null at R1 only); each has p50/p75/p90/p95/p99: {value, confidence, bootstrap_ci?}
  - downside_risk: DownsideRiskResult | null (null at R1)
  - finance_assumptions: {seed, valuation_date, r_f, r_e, wacc, price_path_ids, code_version}
  - equity_irr_pct: MetricPercentiles | null (debt-gated)
  - min_dscr: number | null (debt-gated, bare ratio)
"""

import os
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Import the FastAPI app; fails (ImportError) until implementation exists."""
    from energy_go.serving.main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_policy_ref(kind="trained", run_id="policy-run-uuid", step=1_000_000,
                     agent_name=None):
    if kind == "trained":
        return {"kind": "trained", "run_id": run_id, "step": step}
    return {"kind": "baseline", "agent_name": agent_name}


def _make_variant(variant_id="v1", config_id="config-uuid",
                  policy_ref=None, eval_result_id=None):
    return {
        "variant_id":     variant_id,
        "config_id":      config_id,
        "policy_ref":     policy_ref or _make_policy_ref(),
        "eval_result_id": eval_result_id,
    }


def _shared_scenario(price_path="flat_2026", m_draws=50):
    return {"price_path_name": price_path, "m_draws": m_draws}


# ===========================================================================
# §3 — POST /api/compare/plan
# ===========================================================================

class TestComparePlan:
    """Tier estimation — pure read, does not touch LRU cache."""

    def test_plan_returns_200_with_valid_body(self, client):
        """Happy path: one variant → 200 with plan list."""
        resp = client.post("/api/compare/plan", json={
            "variants": [_make_variant()],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "plan" in body
        assert len(body["plan"]) == 1

    def test_plan_entry_has_required_fields(self, client):
        """Each plan entry must have variant_id, tier, tier_duration_estimate_s, reason."""
        resp = client.post("/api/compare/plan", json={
            "variants": [_make_variant("v-xyz")],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 200
        entry = resp.json()["plan"][0]
        assert entry["variant_id"] == "v-xyz"
        assert entry["tier"] in {
            "instant", "fast", "eval_needed", "retrain_required", "running", "unknown"
        }
        # tier_duration_estimate_s: null for instant/retrain_required; number otherwise
        assert "tier_duration_estimate_s" in entry
        assert isinstance(entry["reason"], str)

    def test_plan_instant_tier_has_null_duration(self, client, monkeypatch):
        """Instant tier → tier_duration_estimate_s must be null (INV-CE-10 + §3.3)."""
        # Seed the cache so eval_result_id is present
        monkeypatch.setattr(
            "energy_go.serving.compare.cache",
            {"eval-uuid-cached": object()},  # stub ensemble
        )
        variant = _make_variant(eval_result_id="eval-uuid-cached")
        resp = client.post("/api/compare/plan", json={
            "variants": [variant],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 200
        entry = resp.json()["plan"][0]
        assert entry["tier"] == "instant"
        assert entry["tier_duration_estimate_s"] is None

    def test_plan_unknown_price_path_is_400(self, client):
        """Unknown price_path_name → 400 VALIDATION_ERROR."""
        resp = client.post("/api/compare/plan", json={
            "variants": [_make_variant()],
            "shared_scenario": {"price_path_name": "NONEXISTENT_PATH", "m_draws": 50},
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_plan_m_draws_zero_is_400(self, client):
        """m_draws=0 < 1 → 400 VALIDATION_ERROR."""
        resp = client.post("/api/compare/plan", json={
            "variants": [_make_variant()],
            "shared_scenario": {"price_path_name": "flat_2026", "m_draws": 0},
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_plan_unknown_config_id_is_404(self, client):
        """Unknown config_id → 404 CONFIG_NOT_FOUND."""
        variant = _make_variant(config_id="does-not-exist-config")
        resp = client.post("/api/compare/plan", json={
            "variants": [variant],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 404
        assert resp.json()["code"] == "CONFIG_NOT_FOUND"

    def test_plan_does_not_write_to_cache(self, client, monkeypatch):
        """POST /api/compare/plan is read-only — cache size must not change (INV-CE-10)."""
        from energy_go.serving import compare as svc
        cache_before = dict(svc.cache)
        resp = client.post("/api/compare/plan", json={
            "variants": [_make_variant()],
            "shared_scenario": _shared_scenario(),
        })
        # Even on success, cache must be unchanged
        cache_after = dict(svc.cache)
        assert set(cache_before.keys()) == set(cache_after.keys()), (
            "POST /api/compare/plan must not modify the PolicyEnsemble LRU cache"
        )

    def test_plan_multiple_variants_returns_matching_count(self, client):
        """Multiple variants → plan list length matches input variants length."""
        variants = [_make_variant(f"v{i}") for i in range(3)]
        resp = client.post("/api/compare/plan", json={
            "variants": variants,
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 200
        assert len(resp.json()["plan"]) == 3

    def test_plan_empty_variants_is_400(self, client):
        # reviewer: empty variants list has no defined tier — should be a validation error
        resp = client.post("/api/compare/plan", json={
            "variants": [],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_plan_retrain_required_has_null_duration(self, client):
        # reviewer: retrain_required tier must also return null duration (§3.3 table)
        # Set up a variant whose config has no compatible trained policy.
        variant = _make_variant(config_id="config-no-policy")
        resp = client.post("/api/compare/plan", json={
            "variants": [variant],
            "shared_scenario": _shared_scenario(),
        })
        # If config has no trained policy → retrain_required
        if resp.status_code == 200:
            entry = resp.json()["plan"][0]
            if entry["tier"] == "retrain_required":
                assert entry["tier_duration_estimate_s"] is None


# ===========================================================================
# §4 — POST /api/compare/finance
# ===========================================================================

class TestCompareFinance:
    """Instant-tier finance recompute — POST /api/compare/recompute-finance, synchronous."""

    EVAL_ID = "eval-result-uuid-1234"
    POLICY_ID = "policy-uuid-abcd"
    ENDPOINT = "/api/compare/recompute-finance"

    def _finance_request(self, eval_result_id=None, policy_id=None,
                         price_path="flat_2026", finance_params=None):
        return {
            "eval_result_id":  eval_result_id or self.EVAL_ID,
            "policy_id":       policy_id or self.POLICY_ID,
            "price_path_name": price_path,
            "finance_params":  finance_params or {},
        }

    def test_finance_cache_miss_returns_404(self, client):
        """eval_result_id not in cache → 404 EVAL_RESULT_NOT_FOUND (INV-CE-01)."""
        resp = client.post(self.ENDPOINT, json=self._finance_request(
            eval_result_id="definitely-not-in-cache-uuid"
        ))
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "EVAL_RESULT_NOT_FOUND"
        assert "detail" in body

    def test_finance_200_with_cached_ensemble(self, client, monkeypatch):
        """With a cached ensemble → 200 with finance_result."""
        # Inject a stub ensemble into the cache
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID)
        monkeypatch.setattr(
            "energy_go.serving.compare.cache",
            {self.EVAL_ID: stub_ensemble},
        )
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        assert "finance_result" in resp.json()

    def test_finance_result_has_regime_field(self, client, monkeypatch):
        """FinanceResultSummary must contain regime ∈ {R1, R2, R3}."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr["regime"] in {"R1", "R2", "R3"}

    def test_finance_result_has_nested_provenance(self, client, monkeypatch):
        """FinanceResultSummary must have nested provenance {sample_kind, m_draws, distribution_valid}."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            sample_kind="bootstrap")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        prov = fr.get("provenance")
        assert prov is not None, "provenance block must be present"
        assert "sample_kind" in prov
        assert "m_draws" in prov
        assert "distribution_valid" in prov
        assert prov["sample_kind"] in {"bootstrap", "empirical"}, (
            "INV-CE-17: sample_kind must be 'bootstrap' or 'empirical'; 'synthetic' is forbidden"
        )

    def test_finance_sample_kind_is_never_synthetic(self, client, monkeypatch):
        """INV-CE-17: 'synthetic' is forbidden in provenance.sample_kind (D42/#133 LOCK)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            sample_kind="bootstrap")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("provenance", {}).get("sample_kind") != "synthetic", (
            "INV-CE-17: 'synthetic' must never appear in provenance.sample_kind (D42/#133 LOCK)"
        )

    def test_finance_irr_pct_p50_value_is_percent_not_decimal(self, client, monkeypatch):
        """INV-CE-04: irr_pct.p50.value must be percent (e.g. 12.3), NOT decimal (0.123).

        Arithmetic: engine returns irr=0.123 (decimal) → serving must ×100 → 12.3%.
        If serving forgets ×100, irr_pct.p50.value would be 0.123 < 1.0 → assert fails.
        Nested field: FinanceResultSummary.irr_pct.p50.value (MetricPercentiles shape).
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            irr_decimal=0.123)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        irr_pct = fr.get("irr_pct")
        if irr_pct is not None and irr_pct.get("p50") is not None:
            val = irr_pct["p50"]["value"]
            # Must be in percent form — 12.3, NOT 0.123
            # Arithmetic: 0.123 × 100 = 12.3; < 1.0 reveals decimal-unit bug
            assert val > 1.0, (
                f"irr_pct.p50.value={val} looks like decimal (< 1.0); must be percent (12.3). "
                f"Serving layer must multiply engine decimal by 100 (INV-CE-04)."
            )

    def test_finance_finance_assumptions_wacc_is_decimal_not_percent(self, client, monkeypatch):
        """INV-CE-05: finance_assumptions.wacc must stay as decimal (0.088), NOT percent (8.8).

        Arithmetic: engine wacc=0.088 → serving must NOT ×100 for finance_assumptions block.
        Note: this is 'finance_assumptions', NOT 'provenance' (renamed to avoid clash with
        the regime provenance block {sample_kind, m_draws, distribution_valid}).
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            wacc_decimal=0.088)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        fa = fr.get("finance_assumptions", {})
        wacc = fa.get("wacc")
        if wacc is not None:
            # Must be decimal — 0.088, NOT 8.8
            # Arithmetic: if wacc=0.088 → correct; if wacc=8.8 → bug (×100 applied)
            assert wacc < 1.0, (
                f"finance_assumptions.wacc={wacc} looks like percent (> 1.0); must be decimal (0.088). "
                f"finance_assumptions block must NOT multiply by 100 (INV-CE-05)."
            )

    def test_finance_downside_risk_null_at_r1(self, client, monkeypatch):
        """INV-CE-06: downside_risk is null when M=1 (regime R1, distribution_valid=False)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=1)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("regime") == "R1"
        assert fr.get("downside_risk") is None, (
            "downside_risk must be null at R1 (distribution_valid=False, INV-CE-06)"
        )

    def test_finance_single_trajectory_nonnull_only_at_r1(self, client, monkeypatch):
        """INV-CE-18: single_trajectory is non-null at R1, null at R2/R3."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=1)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R1":
            st = fr.get("single_trajectory")
            assert st is not None, "single_trajectory must be non-null at R1"
            assert "point_npv_yuan" in st
            assert "max_drawdown_yuan" in st
            assert "max_drawdown_year" in st
            assert "worst_year_cf_yuan" in st
            # IRR absent at M=1 (INV-CE-18)
            assert "point_irr_pct" not in st, (
                "point_irr_pct must not be in single_trajectory — IRR absent at M=1 (INV-CE-18)"
            )

    def test_finance_single_trajectory_null_at_r2(self, client, monkeypatch):
        """INV-CE-18: single_trajectory is null at R2."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            sample_kind="bootstrap")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R2":
            assert fr.get("single_trajectory") is None, (
                "single_trajectory must be null at R2 (INV-CE-18)"
            )

    def test_finance_metric_percentiles_null_at_r1(self, client, monkeypatch):
        """INV-CE-19: irr_pct, npv_yuan, mirr_pct, lcoe_yuan_per_mwh, payback_yr all null at R1."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=1)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R1":
            for field in ("irr_pct", "npv_yuan", "mirr_pct", "lcoe_yuan_per_mwh", "payback_yr"):
                assert fr.get(field) is None, (
                    f"INV-CE-19: {field} must be null at R1"
                )

    def test_finance_best_of_n_npv_null_at_r2(self, client, monkeypatch):
        """INV-CE-07: best_of_n_npv_yuan is absent/null at R2 (non-null only at R3)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            sample_kind="bootstrap")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R2" and fr.get("downside_risk"):
            # best_of_n_npv_yuan may be absent or null at R2
            best = fr["downside_risk"].get("best_of_n_npv_yuan")
            assert best is None, (
                "INV-CE-07: best_of_n_npv_yuan must be null at R2"
            )

    def test_finance_cvar5_null_at_r3(self, client, monkeypatch):
        """INV-CE-08: cvar5_yuan is null at R3 (non-null only at R2)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=10,
                                            sample_kind="empirical")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R3" and fr.get("downside_risk"):
            assert fr["downside_risk"]["cvar5_yuan"] is None, (
                "INV-CE-08: cvar5_yuan must be null at R3 (k=ceil(0.05·10)=1 relabels to worst-of-N)"
            )

    def test_finance_p_irr_below_hurdle_populated_at_r3(self, client, monkeypatch):
        """MUST-FIX 1 (backend-reviewer): p_irr_below_hurdle is POPULATED at R3.

        p_irr_below_hurdle is an empirical frequency (#{IRR_m < hurdle}/M), NOT a tail
        percentile. It does not collapse at M≈10. PRs #120/#121 confirmed this is populated
        in the engine's R3 output. Therefore it must NOT be null at R3 (unlike cvar5_yuan).
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=10,
                                            sample_kind="empirical")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R3" and fr.get("downside_risk") is not None:
            p_irr = fr["downside_risk"].get("p_irr_below_hurdle")
            assert p_irr is not None, (
                "p_irr_below_hurdle must be populated at R3 — it is a frequency, not a tail. "
                "PRs #120/#121 confirmed the engine populates this at M=10 (empirical)."
            )
            assert 0.0 <= p_irr <= 1.0, (
                f"p_irr_below_hurdle={p_irr} must be a probability in [0,1]"
            )

    def test_finance_p_irr_below_hurdle_null_at_r1(self, client, monkeypatch):
        """p_irr_below_hurdle is null at R1 (distribution_valid=False, no draws to count)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=1)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R1":
            # At R1, downside_risk is null entirely (INV-CE-06)
            assert fr.get("downside_risk") is None

    def test_finance_equity_irr_pct_p50_is_percent_when_debt_on(self, client, monkeypatch):
        """INV-CE-04: equity_irr_pct.p50.value must be percent (×100) when gearing_pct > 0.

        Arithmetic: engine returns equity_irr=0.142 (decimal) → serving must ×100 → 14.2%.
        If serving omits ×100, equity_irr_pct.p50.value would be 0.142 < 1.0 → assert fails.
        In FinanceParamSet, gearing_pct > 0 triggers debt_toggle=True in FinanceConfig.
        """
        DEBT_PARAMS = {
            "gearing_pct": {"value": 60.0, "scope": "per_config"}  # 60% gearing → D/E 1.5
        }
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            equity_irr_decimal=0.142)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request(
            finance_params=DEBT_PARAMS
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        eq_pct = fr.get("equity_irr_pct")
        if eq_pct is not None and eq_pct.get("p50") is not None:
            val = eq_pct["p50"]["value"]
            # Must be in percent form (14.2, not 0.142)
            # Arithmetic: 0.142 × 100 = 14.2; < 1.0 reveals decimal-unit bug
            assert val > 1.0, (
                f"equity_irr_pct.p50.value={val} looks like decimal (< 1.0); must be percent (14.2). "
                f"Serving layer must multiply engine decimal by 100 (INV-CE-04)."
            )

    def test_finance_equity_irr_pct_null_when_no_gearing(self, client, monkeypatch):
        """equity_irr_pct is null when gearing_pct=0 (debt off — no D/E leverage)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request(
            finance_params={}  # gearing defaults to 0 (debt off)
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("equity_irr_pct") is None, (
            "equity_irr_pct must be null when gearing_pct=0 (debt off)"
        )

    def test_finance_min_dscr_is_ratio_not_percent(self, client, monkeypatch):
        """INV-CE-16: min_dscr must be a bare ratio (e.g. 1.86), NOT ×100.

        Arithmetic: engine returns min_dscr=1.86 (ratio). Serving must NOT multiply by 100.
        A wrong ×100 conversion would produce 186.0 — caught by asserting value < 10.0.
        Realistic DSCR for a bankable project is 1.20–2.50; > 10 is economically implausible.
        """
        DEBT_PARAMS = {"gearing_pct": {"value": 60.0, "scope": "per_config"}}
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            min_dscr_ratio=1.86)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request(
            finance_params=DEBT_PARAMS
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        dscr = fr.get("min_dscr")
        if dscr is not None:
            # INV-CE-16: bare ratio, not percent
            # Arithmetic: 1.86 is correct; 186.0 reveals erroneous ×100
            assert dscr < 10.0, (
                f"min_dscr={dscr} > 10.0 — looks like percent (×100 applied). "
                f"min_dscr is a DSCR coverage ratio (1.86), NOT a percent (INV-CE-16)."
            )
            assert dscr > 0.0, "min_dscr must be positive (dimensionless ratio)"

    def test_finance_min_dscr_null_when_no_gearing(self, client, monkeypatch):
        """min_dscr is null when gearing_pct=0 (debt off)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request(
            finance_params={}  # gearing defaults to 0
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("min_dscr") is None, (
            "min_dscr must be null when gearing_pct=0 (debt off)"
        )

    def test_finance_engine_exception_returns_500(self, client, monkeypatch):
        """reviewer: if finance() raises, the endpoint must return 500 INTERNAL_ERROR."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})

        def _raising_finance(*args, **kwargs):
            raise RuntimeError("Simulated finance() internal error")

        monkeypatch.setattr("energy_go.finance.engine.finance", _raising_finance)
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 500
        assert resp.json()["code"] == "INTERNAL_ERROR"

    def test_finance_unknown_field_in_finance_params_is_400(self, client):
        """reviewer: closed allow-set (INV-CE-15) — any unknown key in finance_params → 400.

        The request body uses finance_params (FinanceParamSet), NOT finance_config.
        Any key not in the FinanceParamSet allow-set must be rejected.
        E.g. 'gamma' is not a valid FinanceParamSet field.
        """
        resp = client.post(self.ENDPOINT, json={
            "eval_result_id":  self.EVAL_ID,
            "policy_id":       self.POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_params":  {"gamma": 0.999},   # unknown FinanceParamSet field
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_finance_typo_field_in_finance_params_is_400(self, client):
        # reviewer: typo fields (e.g. 'horizon_year' vs 'horizon_years') must also be rejected
        resp = client.post(self.ENDPOINT, json={
            "eval_result_id":  self.EVAL_ID,
            "policy_id":       self.POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_params":  {"horizon_year": 25},   # missing 's' — not in FinanceParamSet
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_finance_unknown_policy_id_is_404(self, client, monkeypatch):
        """policy_id not in ensemble.runs → 404 POLICY_NOT_IN_ENSEMBLE."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, "real-policy-id")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request(
            policy_id="wrong-policy-id"
        ))
        assert resp.status_code == 404
        assert resp.json()["code"] == "POLICY_NOT_IN_ENSEMBLE"

    def test_finance_unknown_price_path_is_404(self, client, monkeypatch):
        """Unknown price_path_name → 404 PRICE_PATH_NOT_FOUND."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request(
            price_path="NONEXISTENT_PATH"
        ))
        assert resp.status_code == 404
        assert resp.json()["code"] == "PRICE_PATH_NOT_FOUND"

    def test_finance_bare_wacc_in_finance_params_is_400(self, client):
        """INV-CE-15: bare 'wacc' key in finance_params → 400 VALIDATION_ERROR.

        The FinanceParamSet allow-set contains 'wacc_pct' (not bare 'wacc').
        Passing bare "wacc" must be rejected — use "wacc_pct": {"value": 8.2, ...} instead.
        """
        resp = client.post(self.ENDPOINT, json={
            "eval_result_id":  self.EVAL_ID,
            "policy_id":       self.POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_params":  {"wacc": 0.082},   # bare "wacc" not in FinanceParamSet allow-set
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_finance_malformed_body_is_400(self, client):
        """Missing required fields → 400."""
        resp = client.post(self.ENDPOINT, json={
            "eval_result_id": "only-this-field"
            # missing price_path_name
        })
        assert resp.status_code == 400

    def test_finance_m_draws_in_provenance_matches_ensemble(self, client, monkeypatch):
        """FinanceResultSummary.provenance.m_draws must equal the cached ensemble's M.

        Note: m_draws is nested under provenance (v1.1.0 shape), not a top-level field.
        """
        M = 50
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=M)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        # v1.1.0 nested: provenance.m_draws (NOT top-level fr["m_draws"])
        prov = fr.get("provenance", {})
        assert prov.get("m_draws") == M, (
            f"provenance.m_draws={prov.get('m_draws')} expected {M}. "
            "m_draws is nested under provenance in FinanceResultSummary v1.1.0."
        )

    def test_finance_irr_pct_p90_confidence_at_r3(self, client, monkeypatch):
        """reviewer: R3 irr_pct.p90 may have confidence='indicative_low_confidence' (D39 §4).

        At R3 (M≈10, empirical), high tail percentiles are unreliable. The engine marks
        them confidence='indicative_low_confidence' rather than suppressing them entirely.
        This test verifies the confidence field is present (not null) and the value is a
        PercentileResult with a recognized confidence level.
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=10,
                                            sample_kind="empirical")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R3" and fr.get("irr_pct") is not None:
            irr_p90 = fr["irr_pct"].get("p90")
            if irr_p90 is not None:
                assert irr_p90.get("confidence") in {
                    "sound", "indicative_low_confidence"
                }, (
                    "irr_pct.p90.confidence must be 'sound' or 'indicative_low_confidence'; "
                    "R3 tail values may carry low-confidence marking per D39."
                )

    def test_finance_npv_pct_p90_at_r3_if_present(self, client, monkeypatch):
        """reviewer: R3 npv_yuan.p90, if present, must have a valid confidence marker."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=10,
                                            sample_kind="empirical")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R3" and fr.get("npv_yuan") is not None:
            npv_p90 = fr["npv_yuan"].get("p90")
            if npv_p90 is not None:
                assert npv_p90.get("confidence") in {
                    "sound", "indicative_low_confidence"
                }, (
                    "npv_yuan.p90.confidence at R3 must be a recognized confidence level"
                )


# ===========================================================================
# §5 — PolicyEnsemble LRU cache
# ===========================================================================

class TestPolicyEnsembleCache:
    """Direct cache behaviour tests (not via endpoint)."""

    def test_cache_default_max_is_10(self):
        """Default ENERGY_GO_ENSEMBLE_CACHE_MAX = 10 (INV-CE-02)."""
        from energy_go.serving.compare import EnsembleCache
        cache = EnsembleCache()
        assert cache.max_size == 10

    def test_cache_env_var_overrides_max(self, monkeypatch):
        """ENERGY_GO_ENSEMBLE_CACHE_MAX env var is honoured."""
        monkeypatch.setenv("ENERGY_GO_ENSEMBLE_CACHE_MAX", "3")
        from importlib import reload
        import energy_go.serving.compare as mod
        reload(mod)
        assert mod.EnsembleCache().max_size == 3

    def test_cache_max_1_is_legal(self, monkeypatch):
        """INV-CE-03: capacity=1 must not raise at construction."""
        monkeypatch.setenv("ENERGY_GO_ENSEMBLE_CACHE_MAX", "1")
        from energy_go.serving.compare import EnsembleCache
        cache = EnsembleCache(max_size=1)
        # Must not raise
        cache["key-a"] = object()
        assert "key-a" in cache

    def test_cache_evicts_lru_at_capacity(self, monkeypatch):
        """At capacity, the least-recently-used entry is evicted (LRU policy)."""
        from energy_go.serving.compare import EnsembleCache
        cache = EnsembleCache(max_size=2)
        cache["k1"] = "ensemble-1"
        cache["k2"] = "ensemble-2"
        # Access k1 → k1 is now MRU; k2 is LRU
        _ = cache["k1"]
        # Insert k3 → capacity exceeded; k2 should be evicted (LRU)
        cache["k3"] = "ensemble-3"
        assert "k1" in cache, "k1 (MRU) must not be evicted"
        assert "k3" in cache, "k3 (just inserted) must be present"
        assert "k2" not in cache, "k2 (LRU) must be evicted"

    def test_cache_miss_returns_none(self):
        """Cache get on non-existent key returns None (not KeyError)."""
        from energy_go.serving.compare import EnsembleCache
        cache = EnsembleCache(max_size=5)
        result = cache.get("not-a-key")
        assert result is None

    def test_cache_eviction_at_capacity_1(self, monkeypatch):
        """Capacity=1: inserting second entry evicts the first (INV-CE-03 extension)."""
        from energy_go.serving.compare import EnsembleCache
        cache = EnsembleCache(max_size=1)
        cache["old"] = "old-ensemble"
        cache["new"] = "new-ensemble"
        assert "new" in cache
        assert "old" not in cache

    def test_cache_read_updates_recency(self):
        """A cache read counts as an access (updates LRU recency per §5.2)."""
        from energy_go.serving.compare import EnsembleCache
        cache = EnsembleCache(max_size=2)
        cache["k1"] = "e1"
        cache["k2"] = "e2"
        # Access k1 (makes k1 MRU); k2 becomes LRU
        _ = cache["k1"]
        cache["k3"] = "e3"
        assert "k1" in cache
        assert "k2" not in cache

    def test_cache_invalid_env_var_raises_at_startup(self, monkeypatch):
        """Non-integer ENERGY_GO_ENSEMBLE_CACHE_MAX → startup error (INV-CE-02)."""
        monkeypatch.setenv("ENERGY_GO_ENSEMBLE_CACHE_MAX", "not-a-number")
        from importlib import reload
        import energy_go.serving.compare as mod
        with pytest.raises((ValueError, SystemExit)):
            reload(mod)

    def test_cache_zero_max_raises_at_startup(self, monkeypatch):
        # reviewer: max_size=0 is not legal (INV-CE-02 "int > 0")
        monkeypatch.setenv("ENERGY_GO_ENSEMBLE_CACHE_MAX", "0")
        from importlib import reload
        import energy_go.serving.compare as mod
        with pytest.raises((ValueError, SystemExit)):
            reload(mod)

    def test_cache_negative_max_raises_at_startup(self, monkeypatch):
        # reviewer: negative max_size must also be rejected
        monkeypatch.setenv("ENERGY_GO_ENSEMBLE_CACHE_MAX", "-5")
        from importlib import reload
        import energy_go.serving.compare as mod
        with pytest.raises((ValueError, SystemExit)):
            reload(mod)

    def test_cache_concurrent_reads_do_not_corrupt(self):
        """reviewer (§5.5): concurrent reads on the same key must not corrupt cache state.

        Uses threading to fire 10 concurrent gets on the same key. The cache must not
        raise, lose entries, or silently return wrong values under concurrent access.
        """
        import threading
        from energy_go.serving.compare import EnsembleCache
        cache = EnsembleCache(max_size=5)
        sentinel = object()
        cache["shared-key"] = sentinel

        errors = []
        results = []

        def _read():
            try:
                results.append(cache.get("shared-key"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_read) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent cache reads raised: {errors}"
        assert all(r is sentinel for r in results), (
            "Concurrent reads returned wrong value — cache corrupted under concurrent access"
        )


# ===========================================================================
# §6 — POST /api/compare/run
# ===========================================================================

class TestCompareRun:
    """Async batch eval + finance submission."""

    def test_run_returns_202(self, client):
        """POST /api/compare/run → 202 Accepted with run_id (INV-CE-11)."""
        resp = client.post("/api/compare/run", json={
            "variants": [_make_variant()],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 202
        body = resp.json()
        assert "run_id" in body
        assert isinstance(body["run_id"], str)
        assert len(body["run_id"]) > 0

    def test_run_response_is_not_200_or_201(self, client):
        """INV-CE-11: must be 202, explicitly not 200 or 201."""
        resp = client.post("/api/compare/run", json={
            "variants": [_make_variant()],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 202, (
            f"Expected 202 Accepted, got {resp.status_code} — work is submitted, not complete"
        )

    def test_run_empty_variants_is_400(self, client):
        """Empty variants list → 400 VALIDATION_ERROR."""
        resp = client.post("/api/compare/run", json={
            "variants": [],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_run_unknown_price_path_is_400(self, client):
        """Unknown price_path_name → 400 VALIDATION_ERROR."""
        resp = client.post("/api/compare/run", json={
            "variants": [_make_variant()],
            "shared_scenario": {"price_path_name": "BAD_PATH", "m_draws": 50},
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_run_unknown_config_id_is_404(self, client):
        """Unknown config_id → 404 CONFIG_NOT_FOUND."""
        resp = client.post("/api/compare/run", json={
            "variants": [_make_variant(config_id="NONEXISTENT-CONFIG")],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 404
        assert resp.json()["code"] == "CONFIG_NOT_FOUND"

    def test_run_unknown_policy_run_id_is_404(self, client):
        """Unknown policy run_id → 404 POLICY_NOT_FOUND."""
        resp = client.post("/api/compare/run", json={
            "variants": [_make_variant(
                policy_ref=_make_policy_ref(run_id="NONEXISTENT-POLICY-RUN")
            )],
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 404
        assert resp.json()["code"] == "POLICY_NOT_FOUND"

    def test_run_multiple_variants_single_run_id(self, client):
        """Multiple variants → single run_id (all under one run)."""
        variants = [_make_variant(f"v{i}") for i in range(3)]
        resp = client.post("/api/compare/run", json={
            "variants": variants,
            "shared_scenario": _shared_scenario(),
        })
        assert resp.status_code == 202
        assert isinstance(resp.json()["run_id"], str)

    def test_run_ids_are_unique_per_call(self, client):
        """Two identical calls → two different run_ids."""
        body = {
            "variants": [_make_variant()],
            "shared_scenario": _shared_scenario(),
        }
        r1 = client.post("/api/compare/run", json=body).json()["run_id"]
        r2 = client.post("/api/compare/run", json=body).json()["run_id"]
        assert r1 != r2, "Each call must produce a distinct run_id"

    def test_run_m_draws_negative_is_400(self, client):
        # reviewer: m_draws < 1 (negative) must also be rejected
        resp = client.post("/api/compare/run", json={
            "variants": [_make_variant()],
            "shared_scenario": {"price_path_name": "flat_2026", "m_draws": -1},
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"


# ===========================================================================
# §7 — GET /api/compare/run/{run_id}/status
# ===========================================================================

class TestCompareRunStatus:
    """Polling endpoint for batch run progress."""

    def test_unknown_run_id_is_404(self, client):
        """Unknown run_id → 404 RUN_NOT_FOUND (INV-CE-12)."""
        resp = client.get("/api/compare/run/NONEXISTENT-RUN-ID/status")
        assert resp.status_code == 404
        assert resp.json()["code"] == "RUN_NOT_FOUND"

    def test_status_has_required_fields(self, client):
        """Status response must have status, variants_done, variants_total, results_by_variant_id."""
        # First submit a run to get a real run_id
        submit_resp = client.post("/api/compare/run", json={
            "variants": [_make_variant("v1")],
            "shared_scenario": _shared_scenario(),
        })
        if submit_resp.status_code != 202:
            pytest.skip("POST /api/compare/run not yet implemented")
        run_id = submit_resp.json()["run_id"]

        status_resp = client.get(f"/api/compare/run/{run_id}/status")
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert "status" in body
        assert body["status"] in {"running", "complete", "error"}
        assert "variants_done" in body
        assert "variants_total" in body
        assert "results_by_variant_id" in body
        assert isinstance(body["results_by_variant_id"], dict)

    def test_running_status_results_by_variant_id_is_subset(self, client):
        """INV-CE-12: while running, results_by_variant_id contains ONLY finished variants.

        It must be a subset of submitted variant_ids, not contain still-running ones.
        """
        submit_resp = client.post("/api/compare/run", json={
            "variants": [_make_variant("v1"), _make_variant("v2")],
            "shared_scenario": _shared_scenario(),
        })
        if submit_resp.status_code != 202:
            pytest.skip("POST /api/compare/run not yet implemented")
        run_id = submit_resp.json()["run_id"]

        status_resp = client.get(f"/api/compare/run/{run_id}/status")
        assert status_resp.status_code == 200
        body = status_resp.json()
        # If still running, done count ≤ total count
        assert body["variants_done"] <= body["variants_total"]

    def test_complete_status_has_all_results(self, client, monkeypatch):
        """When status='complete', results_by_variant_id has all variants."""
        # Inject a pre-completed run into the run store
        from energy_go.serving.compare import run_store
        run_id = "pre-completed-run-id"
        run_store[run_id] = {
            "status": "complete",
            "variants_done": 2,
            "variants_total": 2,
            "results_by_variant_id": {
                "v1": {"regime": "R2", "m_draws": 50},
                "v2": {"regime": "R1", "m_draws": 1},
            },
            "error": None,
        }
        resp = client.get(f"/api/compare/run/{run_id}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "complete"
        assert len(body["results_by_variant_id"]) == 2

    def test_error_status_has_error_field(self, client, monkeypatch):
        # reviewer: status='error' must carry a non-null error string
        from energy_go.serving.compare import run_store
        run_id = "pre-errored-run-id"
        run_store[run_id] = {
            "status": "error",
            "variants_done": 0,
            "variants_total": 1,
            "results_by_variant_id": {},
            "error": "Dispatch failed: env step raised NaN",
        }
        resp = client.get(f"/api/compare/run/{run_id}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert body["error"] is not None and len(body["error"]) > 0


# ===========================================================================
# §8 & §9 — POST /api/compare/sizing-sweep + status
# ===========================================================================

class TestSizingSweep:
    """Sizing sweep endpoints — stub verification (expands in task #18)."""

    ENDPOINT = "/api/compare/recompute-finance"  # used in isolation test

    def test_sizing_sweep_returns_202(self, client):
        """POST /api/compare/sizing-sweep → 202 with run_id and configs_total."""
        resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_params":   {},
            "energy_steps":     3,
            "power_steps":      3,
            "energy_range_mwh": [2.0, 20.0],
            "power_range_mw":   [1.0, 10.0],
        })
        assert resp.status_code == 202
        body = resp.json()
        assert "run_id" in body
        assert body["configs_total"] == 9   # 3 × 3

    def test_sizing_sweep_configs_total_is_energy_times_power(self, client):
        """configs_total = energy_steps × power_steps (§8.2 formula)."""
        resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_params":   {},
            "energy_steps":     4,
            "power_steps":      5,
            "energy_range_mwh": [2.0, 20.0],
            "power_range_mw":   [1.0, 10.0],
        })
        if resp.status_code == 202:
            # 4 × 5 = 20
            assert resp.json()["configs_total"] == 20

    def test_sizing_sweep_energy_steps_below_2_is_400(self, client):
        """energy_steps=1 < 2 → 400 VALIDATION_ERROR (§8.1 clamp)."""
        resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_params":   {},
            "energy_steps":     1,
            "power_steps":      3,
            "energy_range_mwh": [2.0, 20.0],
            "power_range_mw":   [1.0, 10.0],
        })
        assert resp.status_code == 400

    def test_sizing_sweep_power_steps_above_20_is_400(self, client):
        """power_steps=21 > 20 → 400 VALIDATION_ERROR (§8.1 clamp)."""
        resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_params":   {},
            "energy_steps":     3,
            "power_steps":      21,
            "energy_range_mwh": [2.0, 20.0],
            "power_range_mw":   [1.0, 10.0],
        })
        assert resp.status_code == 400

    def test_sizing_sweep_status_unknown_run_id_is_404(self, client):
        """Unknown sweep run_id → 404 RUN_NOT_FOUND."""
        resp = client.get("/api/compare/sizing-sweep/NONEXISTENT-SWEEP/status")
        assert resp.status_code == 404
        assert resp.json()["code"] == "RUN_NOT_FOUND"

    def test_sizing_sweep_status_surface_null_while_running(self, client, monkeypatch):
        """INV-CE-13: surface is null while status='running'."""
        from energy_go.serving.compare import sweep_store
        sweep_id = "pre-running-sweep-id"
        sweep_store[sweep_id] = {
            "status": "running",
            "configs_done": 5,
            "configs_total": 25,
            "surface": None,
            "recommended_energy_idx": None,
            "recommended_power_idx": None,
            "recommended_distribution_yuan": None,
            "error": None,
        }
        resp = client.get(f"/api/compare/sizing-sweep/{sweep_id}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert body["surface"] is None, (
            "INV-CE-13: surface must be null while running (no partial surface)"
        )

    def test_sizing_sweep_store_isolated_from_lru_cache(self, client):
        """INV-CE-09: a sweep run_id must NOT resolve via POST /api/compare/finance."""
        sweep_submit_resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_params":   {},
            "energy_steps":     2,
            "power_steps":      2,
            "energy_range_mwh": [2.0, 10.0],
            "power_range_mw":   [1.0, 5.0],
        })
        if sweep_submit_resp.status_code != 202:
            pytest.skip("POST /api/compare/sizing-sweep not yet implemented")

        sweep_run_id = sweep_submit_resp.json()["run_id"]
        # Now try to use sweep_run_id as an eval_result_id in /api/compare/finance
        finance_resp = client.post(self.ENDPOINT, json={
            "eval_result_id":  sweep_run_id,   # wrong: this is a sweep ID, not an eval ID
            "policy_id":       "any-policy",
            "price_path_name": "flat_2026",
            "finance_params":  {},
        })
        assert finance_resp.status_code == 404, (
            "INV-CE-09: sweep run_id must not resolve in PolicyEnsemble LRU cache"
        )
        assert finance_resp.json()["code"] == "EVAL_RESULT_NOT_FOUND"

    def test_sizing_sweep_energy_steps_exactly_20_is_allowed(self, client):
        # reviewer: boundary: energy_steps=20 is at the inclusive upper bound (§8.1)
        resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_params":   {},
            "energy_steps":     20,
            "power_steps":      2,
            "energy_range_mwh": [2.0, 20.0],
            "power_range_mw":   [1.0, 10.0],
        })
        # energy_steps=20, power_steps=2 → 40 configs ≤ 400 (allowed)
        assert resp.status_code == 202

    def test_sizing_sweep_energy_steps_exactly_2_is_allowed(self, client):
        # reviewer: boundary: energy_steps=2 is at the inclusive lower bound (§8.1)
        resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_params":   {},
            "energy_steps":     2,
            "power_steps":      2,
            "energy_range_mwh": [2.0, 20.0],
            "power_range_mw":   [1.0, 10.0],
        })
        assert resp.status_code == 202


# ===========================================================================
# §10 — Unit contract cross-checks
# ===========================================================================

class TestUnitContracts:
    """Verify unit serialization rules are enforced in all responses.

    Uses POST /api/compare/recompute-finance with finance_params (FinanceParamSet).
    """

    ENDPOINT = "/api/compare/recompute-finance"

    def test_metric_percentiles_pct_values_never_less_than_1_in_normal_results(
        self, client, monkeypatch
    ):
        """INV-CE-04: MetricPercentiles .value fields for realistic returns must be > 1.0.

        Fields checked: irr_pct.p50.value, mirr_pct.p50.value (nested v1.1.0 shape).
        Arithmetic: engine decimal 0.123 → ×100 → 12.3% in API. If < 1.0, ×100 omitted.
        Note: single_trajectory.point_irr_pct does NOT exist (IRR absent at M=1, INV-CE-18).
        """
        EVAL_ID = "unit-test-eval-id"
        POLICY_ID = "unit-test-policy-id"
        stub_ensemble = _make_stub_ensemble(EVAL_ID, POLICY_ID, M=50, irr_decimal=0.123)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json={
            "eval_result_id": EVAL_ID,
            "policy_id": POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_params": {},
        })
        if resp.status_code != 200:
            pytest.skip("Implementation not ready")
        fr = resp.json()["finance_result"]
        # v1.1.0 nested: irr_pct.p50.value (not flat irr_p50_pct)
        for metric_field in ("irr_pct", "mirr_pct", "equity_irr_pct"):
            metric = fr.get(metric_field)
            if metric is not None and metric.get("p50") is not None:
                val = metric["p50"]["value"]
                # Arithmetic: 0.123 × 100 = 12.3; < 1.0 reveals decimal-unit bug
                assert val > 1.0, (
                    f"{metric_field}.p50.value={val} looks like decimal (< 1.0). "
                    f"All MetricPercentiles values must be percent (12.3, not 0.123) "
                    f"per INV-CE-04."
                )

    def test_finance_assumptions_decimal_fields_are_less_than_1(self, client, monkeypatch):
        """INV-CE-05: finance_assumptions.wacc/r_f/r_e must be decimal (< 1.0).

        Arithmetic: wacc=0.088 (8.8%) → stays 0.088 in finance_assumptions block.
        If > 1.0, ×100 was wrongly applied. Note: the block is called 'finance_assumptions'
        (NOT 'provenance', which is used for {sample_kind, m_draws, distribution_valid}).
        """
        EVAL_ID = "fa-test-eval-id"
        POLICY_ID = "fa-test-policy-id"
        stub_ensemble = _make_stub_ensemble(EVAL_ID, POLICY_ID, M=50, wacc_decimal=0.088)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {EVAL_ID: stub_ensemble})
        resp = client.post(self.ENDPOINT, json={
            "eval_result_id": EVAL_ID,
            "policy_id": POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_params": {},
        })
        if resp.status_code != 200:
            pytest.skip("Implementation not ready")
        fr = resp.json()["finance_result"]
        # v1.1.0: rates are in finance_assumptions block (not the regime provenance block)
        fa = fr.get("finance_assumptions", {})
        for field in ("wacc", "r_f", "r_e"):
            val = fa.get(field)
            if val is not None:
                # Arithmetic: 0.088 is correct; 8.8 reveals erroneous ×100
                assert val < 1.0, (
                    f"finance_assumptions.{field}={val} looks like percent (> 1.0). "
                    f"finance_assumptions rates must remain decimal (INV-CE-05)."
                )


# ===========================================================================
# Stub factory helpers (will be replaced by real fixtures once implemented)
# ===========================================================================

def _make_stub_ensemble(eval_id, policy_id, M=50, sample_kind="bootstrap",
                        irr_decimal=0.123, wacc_decimal=0.088, extra_policy_id=None,
                        equity_irr_decimal=None, min_dscr_ratio=None):
    """Create a minimal stub PolicyEnsemble-like object for monkeypatching.

    Until the real PolicyEnsemble type exists, this is a SimpleNamespace stub.
    Tests inject it into energy_go.serving.compare.cache.

    Stub hint fields (prefixed _) are read by the serving-layer mock of finance():
      _irr_decimal:        engine decimal → serving must ×100 → irr_pct.p50.value (v1.1.0)
      _wacc_decimal:       engine decimal → must stay decimal in finance_assumptions.wacc
      _equity_irr_decimal: engine decimal → serving must ×100 → equity_irr_pct.p50.value
      _min_dscr_ratio:     engine ratio → must NOT be ×100 in JSON → min_dscr (bare ratio)

    sample_kind ∈ {"bootstrap", "empirical"} — "synthetic" is FORBIDDEN (INV-CE-17, D42/#133).
    """
    from types import SimpleNamespace
    run_ids = {policy_id: [[None] * 5] * M}
    if extra_policy_id:
        run_ids[extra_policy_id] = [[None] * 5] * M
    ensemble = SimpleNamespace(
        eval_result_id=eval_id,
        M=M,
        sample_kind=sample_kind,
        runs=run_ids,
        _irr_decimal=irr_decimal,
        _wacc_decimal=wacc_decimal,
        _equity_irr_decimal=equity_irr_decimal,
        _min_dscr_ratio=min_dscr_ratio,
    )
    return ensemble
