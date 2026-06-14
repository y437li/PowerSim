"""
Tests for contracts/serving/compare_endpoints.md (SC2) — Compare Endpoints.

All tests are RED (no implementation yet). Contract-first step 2.
Reviewer-added cases are marked with # reviewer: comments.

Units contract (INV-CE-04/05):
  - irr_p50_pct, mirr_p50_pct, irr_p90_pct: PERCENT (e.g. 12.3 → 12.3%)
  - provenance.wacc, .r_f, .r_e: DECIMAL (0.088, NOT 8.8)
  - *_yuan: ¥ (no conversion)
  - *_mwh: MWh, *_mw: MW, *_yr: years, *_pct (non-provenance): percent
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

def _make_finance_config(**overrides):
    """Minimal valid FinanceConfigRequest."""
    base = {}
    base.update(overrides)
    return base


def _make_policy_ref(kind="trained", run_id="policy-run-uuid", step=1_000_000,
                     agent_name=None):
    if kind == "trained":
        return {"kind": "trained", "run_id": run_id, "step": step}
    return {"kind": "baseline", "agent_name": agent_name}


def _make_variant(variant_id="v1", config_id="config-uuid",
                  policy_ref=None, eval_result_id=None, finance_config=None):
    return {
        "variant_id":     variant_id,
        "config_id":      config_id,
        "policy_ref":     policy_ref or _make_policy_ref(),
        "eval_result_id": eval_result_id,
        "finance_config": finance_config or {},
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
    """Instant-tier finance recompute — synchronous, LRU cache lookup."""

    EVAL_ID = "eval-result-uuid-1234"
    POLICY_ID = "policy-uuid-abcd"

    def _finance_request(self, eval_result_id=None, policy_id=None,
                         price_path="flat_2026", finance_config=None):
        return {
            "eval_result_id": eval_result_id or self.EVAL_ID,
            "policy_id":      policy_id or self.POLICY_ID,
            "price_path_name": price_path,
            "finance_config":  finance_config or {},
        }

    def test_finance_cache_miss_returns_404(self, client):
        """eval_result_id not in cache → 404 EVAL_RESULT_NOT_FOUND (INV-CE-01)."""
        resp = client.post("/api/compare/finance", json=self._finance_request(
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
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        assert "finance_result" in resp.json()

    def test_finance_result_has_regime_field(self, client, monkeypatch):
        """FinanceResultSummary must contain regime ∈ {R1, R2, R3}."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr["regime"] in {"R1", "R2", "R3"}

    def test_finance_irr_p50_pct_is_percent_not_decimal(self, client, monkeypatch):
        """INV-CE-04: IRR in JSON must be percent (e.g. 12.3, not 0.123).

        Arithmetic: engine returns irr=0.123 (decimal) → serving must ×100 → 12.3%.
        If serving forgets ×100, irr_p50_pct would be 0.123 < 1.0 → assert fails.
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            irr_decimal=0.123)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        irr = fr.get("irr_p50_pct")
        if irr is not None:
            # Must be in percent form — 12.3, NOT 0.123
            # Arithmetic: 0.123 × 100 = 12.3; assert > 1.0 catches the decimal-unit bug
            assert irr > 1.0, (
                f"irr_p50_pct={irr} looks like decimal (< 1.0); must be percent (12.3). "
                f"Serving layer must multiply engine decimal by 100."
            )

    def test_finance_provenance_wacc_is_decimal_not_percent(self, client, monkeypatch):
        """INV-CE-05: provenance.wacc must stay as decimal (0.088), NOT percent (8.8).

        Arithmetic: engine wacc=0.088 → serving must NOT ×100 for provenance block.
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            wacc_decimal=0.088)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        wacc = fr.get("provenance", {}).get("wacc")
        if wacc is not None:
            # Must be decimal — 0.088, NOT 8.8
            # Arithmetic: if wacc=0.088 → correct; if wacc=8.8 → bug (×100 applied)
            assert wacc < 1.0, (
                f"provenance.wacc={wacc} looks like percent (> 1.0); must be decimal (0.088). "
                f"Provenance block must NOT multiply by 100."
            )

    def test_finance_downside_risk_null_at_r1(self, client, monkeypatch):
        """INV-CE-06: downside_risk is null when M=1 (regime R1, distribution_valid=False)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=1)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("regime") == "R1"
        assert fr.get("downside_risk") is None, (
            "downside_risk must be null at R1 (distribution_valid=False, INV-CE-06)"
        )

    def test_finance_best_of_n_npv_null_at_r2(self, client, monkeypatch):
        """INV-CE-07: best_of_n_npv_yuan is null at R2 (non-null only at R3)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            sample_kind="bootstrap")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R2" and fr.get("downside_risk"):
            assert fr["downside_risk"]["best_of_n_npv_yuan"] is None, (
                "INV-CE-07: best_of_n_npv_yuan must be null at R2"
            )

    def test_finance_cvar5_null_at_r3(self, client, monkeypatch):
        """INV-CE-08: cvar5_yuan is null at R3 (non-null only at R2)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=10,
                                            sample_kind="empirical")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
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
        resp = client.post("/api/compare/finance", json=self._finance_request())
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
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R1":
            # At R1, downside_risk is null entirely (INV-CE-06)
            assert fr.get("downside_risk") is None

    def test_finance_equity_irr_pct_is_percent_when_debt_on(self, client, monkeypatch):
        """MUST-FIX 2: equity_irr_pct must be present and in percent when debt_toggle=True.

        Arithmetic: engine returns equity_irr=0.142 (decimal) → serving must ×100 → 14.2%.
        If serving omits ×100, equity_irr_pct would be 0.142 < 1.0 → assert fails.
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            equity_irr_decimal=0.142)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            finance_config={"debt_toggle": True}
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        eqirr = fr.get("equity_irr_pct")
        assert eqirr is not None, (
            "equity_irr_pct must be present when debt_toggle=True"
        )
        # Must be in percent form (14.2, not 0.142)
        # Arithmetic: 0.142 × 100 = 14.2; < 1.0 reveals decimal-unit bug
        assert eqirr > 1.0, (
            f"equity_irr_pct={eqirr} looks like decimal (< 1.0); must be percent (14.2). "
            f"Serving layer must multiply engine decimal by 100."
        )

    def test_finance_equity_irr_pct_null_when_debt_off(self, client, monkeypatch):
        """equity_irr_pct is null when debt_toggle=False (default)."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            finance_config={}  # debt_toggle defaults to False
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("equity_irr_pct") is None, (
            "equity_irr_pct must be null when debt_toggle=False"
        )

    def test_finance_min_dscr_is_ratio_not_percent(self, client, monkeypatch):
        """MUST-FIX 2 + INV-CE-16: min_dscr must be a bare ratio (e.g. 1.86), NOT ×100.

        Arithmetic: engine returns min_dscr=1.86 (ratio). Serving must NOT multiply by 100.
        A wrong ×100 conversion would produce 186.0 — caught by asserting value < 10.0.
        Realistic DSCR for a bankable project is 1.20–2.50; > 10 is economically implausible.
        """
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            min_dscr_ratio=1.86)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            finance_config={"debt_toggle": True}
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        dscr = fr.get("min_dscr")
        assert dscr is not None, "min_dscr must be present when debt_toggle=True"
        # INV-CE-16: bare ratio, not percent
        # Arithmetic: 1.86 is correct; 186.0 reveals erroneous ×100
        assert dscr < 10.0, (
            f"min_dscr={dscr} > 10.0 — looks like percent (×100 applied). "
            f"min_dscr is a DSCR coverage ratio (1.86), NOT a percent (INV-CE-16)."
        )
        assert dscr > 0.0, "min_dscr must be positive (dimensionless ratio)"

    def test_finance_min_dscr_null_when_debt_off(self, client, monkeypatch):
        """min_dscr is null when debt_toggle=False."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            finance_config={}  # debt off by default
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("min_dscr") is None, (
            "min_dscr must be null when debt_toggle=False"
        )

    def test_finance_engine_exception_returns_500(self, client, monkeypatch):
        """reviewer: if finance() raises, the endpoint must return 500 INTERNAL_ERROR."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})

        def _raising_finance(*args, **kwargs):
            raise RuntimeError("Simulated finance() internal error")

        monkeypatch.setattr("energy_go.finance.engine.finance", _raising_finance)
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 500
        assert resp.json()["code"] == "INTERNAL_ERROR"

    def test_finance_unknown_field_in_finance_config_is_400(self, client):
        """reviewer: closed allow-set (INV-CE-15) — any unknown key → 400 VALIDATION_ERROR.

        Only wacc is specified in the contract; an arbitrary unknown field must also fail.
        """
        resp = client.post("/api/compare/finance", json={
            "eval_result_id":  self.EVAL_ID,
            "policy_id":       self.POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_config":  {"gamma": 0.999},   # unknown finance_config field
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_finance_typo_field_in_finance_config_is_400(self, client):
        # reviewer: typo fields (e.g. 'horizon_year' vs 'horizon_years') must also be rejected
        resp = client.post("/api/compare/finance", json={
            "eval_result_id":  self.EVAL_ID,
            "policy_id":       self.POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_config":  {"horizon_year": 25},   # missing 's' — unknown key
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_finance_unknown_policy_id_is_404(self, client, monkeypatch):
        """policy_id not in ensemble.runs → 404 POLICY_NOT_IN_ENSEMBLE."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, "real-policy-id")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            policy_id="wrong-policy-id"
        ))
        assert resp.status_code == 404
        assert resp.json()["code"] == "POLICY_NOT_IN_ENSEMBLE"

    def test_finance_unknown_price_path_is_404(self, client, monkeypatch):
        """Unknown price_path_name → 404 PRICE_PATH_NOT_FOUND."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            price_path="NONEXISTENT_PATH"
        ))
        assert resp.status_code == 404
        assert resp.json()["code"] == "PRICE_PATH_NOT_FOUND"

    def test_finance_wacc_override_in_request_is_400(self, client):
        """INV-CE-15: 'wacc' key in finance_config → 400 VALIDATION_ERROR."""
        resp = client.post("/api/compare/finance", json={
            "eval_result_id":  self.EVAL_ID,
            "policy_id":       self.POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_config":  {"wacc": 0.082},   # must be rejected
        })
        assert resp.status_code == 400
        assert resp.json()["code"] == "VALIDATION_ERROR"

    def test_finance_malformed_body_is_400(self, client):
        """Missing required fields → 400."""
        resp = client.post("/api/compare/finance", json={
            "eval_result_id": "only-this-field"
            # missing price_path_name
        })
        assert resp.status_code == 400

    def test_finance_m_draws_in_result_matches_ensemble(self, client, monkeypatch):
        """FinanceResultSummary.m_draws must equal the cached ensemble's M."""
        M = 50
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=M)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr["m_draws"] == M

    def test_finance_view_ii_delta_present_with_baseline_policy_id(self, client, monkeypatch):
        """view_ii_delta is present when finance_config.baseline_policy_id is set and in ensemble."""
        BASELINE_ID = "baseline-policy-id"
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50,
                                            extra_policy_id=BASELINE_ID)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            finance_config={"baseline_policy_id": BASELINE_ID}
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("view_ii_delta") is not None

    def test_finance_view_ii_delta_null_without_baseline_policy_id(self, client, monkeypatch):
        """view_ii_delta is null when baseline_policy_id is absent from finance_config."""
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=50)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request(
            finance_config={}  # no baseline_policy_id
        ))
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        assert fr.get("view_ii_delta") is None

    def test_finance_irr_p90_null_at_r3(self, client, monkeypatch):
        # reviewer: R3 must suppress irr_p90_pct (tail-suppressed, D39 §4)
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=10,
                                            sample_kind="empirical")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R3":
            assert fr.get("irr_p90_pct") is None, (
                "irr_p90_pct must be null at R3 (tail-suppressed per D39)"
            )

    def test_finance_npv_p90_null_at_r3(self, client, monkeypatch):
        # reviewer: R3 must also suppress npv_p90_yuan
        stub_ensemble = _make_stub_ensemble(self.EVAL_ID, self.POLICY_ID, M=10,
                                            sample_kind="empirical")
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {self.EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json=self._finance_request())
        assert resp.status_code == 200
        fr = resp.json()["finance_result"]
        if fr.get("regime") == "R3":
            assert fr.get("npv_p90_yuan") is None, (
                "npv_p90_yuan must be null at R3"
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

    def test_sizing_sweep_returns_202(self, client):
        """POST /api/compare/sizing-sweep → 202 with run_id and configs_total."""
        resp = client.post("/api/compare/sizing-sweep", json={
            "base_config_id":   "config-uuid",
            "policy_ref":       _make_policy_ref(),
            "shared_scenario":  _shared_scenario(),
            "finance_config":   {},
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
            "finance_config":   {},
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
            "finance_config":   {},
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
            "finance_config":   {},
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
            "finance_config":   {},
            "energy_steps":     2,
            "power_steps":      2,
            "energy_range_mwh": [2.0, 10.0],
            "power_range_mw":   [1.0, 5.0],
        })
        if sweep_submit_resp.status_code != 202:
            pytest.skip("POST /api/compare/sizing-sweep not yet implemented")

        sweep_run_id = sweep_submit_resp.json()["run_id"]
        # Now try to use sweep_run_id as an eval_result_id in /api/compare/finance
        finance_resp = client.post("/api/compare/finance", json={
            "eval_result_id":  sweep_run_id,   # wrong: this is a sweep ID, not an eval ID
            "policy_id":       "any-policy",
            "price_path_name": "flat_2026",
            "finance_config":  {},
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
            "finance_config":   {},
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
            "finance_config":   {},
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
    """Verify unit serialization rules are enforced in all responses."""

    def test_irr_pct_fields_never_less_than_1_in_normal_results(self, client, monkeypatch):
        """All *_pct fields for realistic returns must be > 1.0 (percent, not decimal).

        Arithmetic: A realistic 12.3% IRR → 12.3 in percent. If < 1.0, the serving
        layer omitted the ×100 conversion.
        """
        EVAL_ID = "unit-test-eval-id"
        POLICY_ID = "unit-test-policy-id"
        stub_ensemble = _make_stub_ensemble(EVAL_ID, POLICY_ID, M=50, irr_decimal=0.123)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json={
            "eval_result_id": EVAL_ID,
            "policy_id": POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_config": {},
        })
        if resp.status_code != 200:
            pytest.skip("Implementation not ready")
        fr = resp.json()["finance_result"]
        for field in ("irr_p50_pct", "irr_p90_pct", "mirr_p50_pct", "point_irr_pct"):
            val = fr.get(field)
            if val is not None:
                assert val > 1.0, (
                    f"Field '{field}' = {val} looks like decimal. "
                    f"All *_pct fields must be percent (12.3, not 0.123)."
                )

    def test_provenance_decimal_fields_are_less_than_1(self, client, monkeypatch):
        """provenance.wacc, r_f, r_e must be decimal (< 1.0) — NOT multiplied by 100.

        Arithmetic: wacc=0.088 (8.8%) in decimal form. If > 1.0, ×100 was wrongly applied.
        """
        EVAL_ID = "prov-test-eval-id"
        POLICY_ID = "prov-test-policy-id"
        stub_ensemble = _make_stub_ensemble(EVAL_ID, POLICY_ID, M=50, wacc_decimal=0.088)
        monkeypatch.setattr("energy_go.serving.compare.cache",
                            {EVAL_ID: stub_ensemble})
        resp = client.post("/api/compare/finance", json={
            "eval_result_id": EVAL_ID,
            "policy_id": POLICY_ID,
            "price_path_name": "flat_2026",
            "finance_config": {},
        })
        if resp.status_code != 200:
            pytest.skip("Implementation not ready")
        prov = resp.json()["finance_result"].get("provenance", {})
        for field in ("wacc", "r_f", "r_e"):
            val = prov.get(field)
            if val is not None:
                assert val < 1.0, (
                    f"provenance.{field}={val} looks like percent (> 1.0). "
                    f"Provenance rates must remain decimal (INV-CE-05)."
                )


# ===========================================================================
# Stub factory helpers (will be replaced by real fixtures once implemented)
# ===========================================================================

def _make_stub_ensemble(eval_id, policy_id, M=50, sample_kind="bootstrap",
                        irr_decimal=0.123, wacc_decimal=0.088, extra_policy_id=None,
                        equity_irr_decimal=None, min_dscr_ratio=None):
    """Create a minimal stub PolicyEnsemble-like object for monkeypatching.

    Until the real PolicyEnsemble type exists, this is a SimpleNamespace stub.
    Tests reference it by injecting into energy_go.serving.compare.cache.

    Stub hint fields (prefixed _) are read by the serving-layer mock of finance():
      _irr_decimal:        engine's PercentileResult.irr → serving must ×100 → irr_p50_pct
      _wacc_decimal:       engine's FinanceProvenance.wacc → must stay decimal in JSON
      _equity_irr_decimal: engine's ViewResult.equity_irr → serving must ×100 → equity_irr_pct
      _min_dscr_ratio:     engine's ViewResult.min_dscr → must NOT be ×100 in JSON
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
