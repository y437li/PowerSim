"""Tests for contracts/shared/tariff_model_schema.md v1.0.0.

All tests are RED until implementation lands.  Import-guarded so the suite
skips cleanly when the module doesn't exist yet.

Hand-computed expected values are shown with the arithmetic in comments
(project rule: "no exception is not a test").
"""

import math
import pathlib
import pytest

# ---------------------------------------------------------------------------
# Import guard — module does not exist until implementation; tests skip on
# ImportError.
# ---------------------------------------------------------------------------
try:
    from energy_go.env.tariff_model_schema import (
        load_tariff_schema,
        TariffRegion,
        SellClamp,
        validate_tariff_region,
        ValidationIssue,
    )
    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False

pytestmark = pytest.mark.skipif(
    not HAS_MODULE,
    reason="energy_go.env.tariff_model_schema not implemented yet",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SCHEMA_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "config"
    / "tariff_model_schema.yaml"
)

# Gansu 24-vector at Δt=1h (minute=0 for every step, D8).
# Arithmetic per §3.7 + D8:
#   h=0–6:  valley 250  (23:00–07:00, 0 < 7)
#   h=7:    mid 450     (07:00–08:00)
#   h=8–9:  peak 620    (08:00–10:00, 8 ≤ h < 10)
#   h=10:   peak 620    (10:00, minute=0 < 30 → NOT critical-peak yet)
#   h=11:   crit 780    (11:00, minute=0 < 30 → still in 10:30–11:30 window)
#   h=12–17: mid 450    (11:30–18:00; at :00 h=12 > 11:30)
#   h=18:   peak 620    (18:00–19:00)
#   h=19–20: crit 780   (19:00–21:00)
#   h=21–22: peak 620   (21:00–23:00)
#   h=23:   valley 250
GANSU_ROW = [
    250, 250, 250, 250, 250, 250, 250,  # h=0–6   Valley
    450,                                  # h=7     Mid
    620, 620, 620,                        # h=8–10  Peak
    780,                                  # h=11    Critical peak
    450, 450, 450, 450, 450, 450,         # h=12–17 Mid
    620,                                  # h=18    Peak
    780, 780,                             # h=19–20 Critical peak
    620, 620,                             # h=21–22 Peak
    250,                                  # h=23    Valley
]

assert len(GANSU_ROW) == 24, "test-data bug: GANSU_ROW must have 24 entries"

GANSU_DEMAND_RATE = 32_000.0   # ¥/MW·month (§3.7: "32 000 ¥/MW·month")
GANSU_SPREAD      = 30.0       # ¥/MWh (D7 mean spread)
GANSU_SPREAD_STD  = 10.0       # ¥/MWh (D7 σ)
GANSU_CURRENCY    = "CNY"


@pytest.fixture(scope="module")
def schema():
    return load_tariff_schema(_SCHEMA_PATH)


@pytest.fixture(scope="module")
def gansu(schema):
    return schema["regions"]["cn-gansu"]


# ---------------------------------------------------------------------------
# 1. Schema-level tests
# ---------------------------------------------------------------------------

class TestSchemaVersion:
    def test_schema_version_present(self, schema):
        """Schema version field must exist (presence-only — version strings evolve)."""
        assert schema.get("schema_version") is not None

    def test_schema_version_value(self, schema):
        """v1.0.0 is the initial version for this contract."""
        assert schema["schema_version"] == "1.0.0"

    def test_regions_key_present(self, schema):
        """Top-level 'regions' dict must be present."""
        assert "regions" in schema
        assert isinstance(schema["regions"], dict)


class TestCnGansuEntry:
    def test_cn_gansu_exists(self, schema):
        """cn-gansu is the required bootstrap entry for Gansu site."""
        assert "cn-gansu" in schema["regions"]

    def test_gansu_is_tariff_region(self, gansu):
        """Loaded entry must be a TariffRegion (NamedTuple or dataclass)."""
        assert isinstance(gansu, TariffRegion)

    def test_gansu_has_sell_clamp(self, gansu):
        """sell_clamp sub-struct must be present."""
        assert gansu.sell_clamp is not None
        assert isinstance(gansu.sell_clamp, SellClamp)

    def test_gansu_currency(self, gansu):
        """cn-gansu currency must be CNY (display-layer metadata)."""
        # CNY is the ISO-4217 code for Chinese Yuan
        assert gansu.currency == GANSU_CURRENCY


# ---------------------------------------------------------------------------
# 2. Price table shape and content
# ---------------------------------------------------------------------------

class TestGansuPriceTable:
    def test_price_table_shape(self, gansu):
        """price_table must be (12, 24) — months × hours (§2.1 hard requirement)."""
        tbl = gansu.price_table_yuan_per_mwh
        # 12 months, 24 hours
        assert tbl.shape == (12, 24), f"expected (12,24), got {tbl.shape}"

    def test_price_table_dtype_float(self, gansu):
        """price_table must be float (float32 or float64 both acceptable)."""
        import numpy as np
        assert gansu.price_table_yuan_per_mwh.dtype in (np.float32, np.float64)

    def test_gansu_row_0_matches_reference(self, gansu):
        """Month 0 (Jan) must equal the Gansu 24-vector exactly (initial = replicated×12).

        GANSU_ROW computed above from §3.7 + D8:
          h=10 → peak(620) because minute=0 < 30 (critical peak starts at 10:30)
          h=11 → crit(780) because minute=0 < 30 (10:30–11:30 window still active)
        """
        row = list(gansu.price_table_yuan_per_mwh[0].tolist())
        assert row == GANSU_ROW, f"Row 0 mismatch:\n  got {row}\n  want {GANSU_ROW}"

    def test_all_12_rows_identical_initially(self, gansu):
        """All 12 rows must be identical (initial cn-gansu = replicated×12, no seasonal data yet).

        Hand-computed: cn-gansu initial entry is the flat 24-vector replicated for all months.
        This is the bit-parity guarantee with the merged device_model_schema v2.0.0 baseline.
        """
        tbl = gansu.price_table_yuan_per_mwh
        for m in range(12):
            row_m = list(tbl[m].tolist())
            assert row_m == GANSU_ROW, (
                f"Row {m} (month {m}) != row 0; initial entry must be replicated×12\n"
                f"  got  {row_m}\n  want {GANSU_ROW}"
            )

    def test_specific_cells(self, gansu):
        """Spot-check specific hour cells for all months.

        Arithmetic:
          h=7  → 450  (mid,  all months initially)
          h=11 → 780  (crit, all months initially — 11:00 is in 10:30–11:30 window)
          h=18 → 620  (peak, all months initially)
          h=19 → 780  (crit, all months initially — 19:00–21:00)
        """
        tbl = gansu.price_table_yuan_per_mwh
        for m in range(12):
            assert tbl[m][7]  == 450, f"m={m} h=7 should be 450 (mid)"
            assert tbl[m][11] == 780, f"m={m} h=11 should be 780 (critical peak)"
            assert tbl[m][18] == 620, f"m={m} h=18 should be 620 (peak)"
            assert tbl[m][19] == 780, f"m={m} h=19 should be 780 (critical peak)"

    def test_h10_is_peak_not_critical_peak(self, gansu):
        """h=10 at minute=0 is PEAK (620), NOT critical peak (780).

        D8: at Δt=1h steps land on :00. Critical peak starts at 10:30; 10:00 < 10:30 → peak.
        This is the boundary case that distinguishes correct from off-by-one implementations.
        """
        for m in range(12):
            assert gansu.price_table_yuan_per_mwh[m][10] == 620, (
                f"m={m} h=10 should be peak(620) not crit(780): 10:00 < 10:30 per D8"
            )

    def test_all_prices_non_negative(self, gansu):
        """All price entries must be ≥ 0 for the initial cn-gansu entry."""
        tbl = gansu.price_table_yuan_per_mwh
        assert float(tbl.min()) >= 0.0, f"negative price found: min={float(tbl.min())}"


# ---------------------------------------------------------------------------
# 3. Demand rate and sell-clamp
# ---------------------------------------------------------------------------

class TestGansuDemandAndClamp:
    def test_demand_rate_value(self, gansu):
        """demand_rate must be 32 000 ¥/MW·month (§3.7).

        Arithmetic: spec says "32 000 ¥/MW·month" = 32.0 ¥/kW·month × 1000.
        EnvParams.demand_rate_yuan_per_mw_month = 32_000.0 — must match exactly.
        """
        assert gansu.demand_rate_yuan_per_mw_month == GANSU_DEMAND_RATE, (
            f"expected {GANSU_DEMAND_RATE}, got {gansu.demand_rate_yuan_per_mw_month}"
        )

    def test_spread_value(self, gansu):
        """spread must be 30.0 ¥/MWh (D7 mean buy-sell spread)."""
        assert gansu.sell_clamp.spread_yuan_per_mwh == GANSU_SPREAD, (
            f"expected {GANSU_SPREAD}, got {gansu.sell_clamp.spread_yuan_per_mwh}"
        )

    def test_spread_noise_std_value(self, gansu):
        """spread_noise_std must be 10.0 ¥/MWh (D7 σ)."""
        assert gansu.sell_clamp.spread_noise_std_yuan_per_mwh == GANSU_SPREAD_STD, (
            f"expected {GANSU_SPREAD_STD}, got {gansu.sell_clamp.spread_noise_std_yuan_per_mwh}"
        )

    def test_spread_non_negative(self, gansu):
        """Spread must be ≥ 0 (negative spread → sell > buy → risk-free arbitrage, D7)."""
        assert gansu.sell_clamp.spread_yuan_per_mwh >= 0.0

    def test_spread_std_non_negative(self, gansu):
        """Spread σ must be ≥ 0 (negative σ is mathematically incoherent)."""
        assert gansu.sell_clamp.spread_noise_std_yuan_per_mwh >= 0.0


# ---------------------------------------------------------------------------
# 4. Parity with EnvParams default
# ---------------------------------------------------------------------------

class TestParityWithEnvDefault:
    """cn-gansu price_table must be bit-identical to the EnvParams default PRICE_TABLE
    when available (requires JAX env on the path; skips on ImportError).
    """

    def test_parity_with_env_params_default(self, gansu):
        """cn-gansu row 0 == EnvParams().price_table (all months, initial replicated-×12).

        Hand-computed: EnvParams defaults are PRICE_TABLE = jnp.array(GANSU_ROW, dtype=float32).
        After device_model_schema v2.0.0, EnvParams.price_table shape is (12,24) with all rows
        equal to GANSU_ROW.  This test asserts bit-exact parity so no drift can enter silently.
        """
        jax = pytest.importorskip("jax")
        import numpy as np
        try:
            from energy_go.env.jax_env import EnvParams
        except ImportError:
            pytest.skip("jax_env not available on this host")

        default_table = np.array(EnvParams().price_table)
        schema_table = gansu.price_table_yuan_per_mwh
        assert default_table.shape == (12, 24), (
            f"EnvParams().price_table shape is {default_table.shape}; "
            "device_model_schema v2.0.0 must be merged first"
        )
        assert schema_table.shape == (12, 24)
        assert np.array_equal(schema_table.astype(np.float32), default_table.astype(np.float32)), (
            "cn-gansu price_table not bit-identical to EnvParams default; "
            "initial entry must be the Gansu 24-vector replicated ×12"
        )


# ---------------------------------------------------------------------------
# 5. Validation — E-TARIFF-SHAPE (HARD ERROR)
# ---------------------------------------------------------------------------

class TestValidationETariffShape:
    """E-TARIFF-SHAPE fires as HARD ERROR for wrong-shape price tables."""

    def _make_region(self, table):
        """Helper: make a minimal region dict for validate_tariff_region."""
        return {
            "currency": "CNY",
            "price_table_yuan_per_mwh": table,
            "demand_rate_yuan_per_mw_month": 32000.0,
            "sell_clamp": {
                "spread_yuan_per_mwh": 30.0,
                "spread_noise_std_yuan_per_mwh": 10.0,
            },
        }

    def test_flat_24_fires_error(self):
        """A flat (24,) list — legacy v1 shape — must fire E-TARIFF-SHAPE.

        A (24,) input was valid under device_model_schema v1.0.0 but is wrong here
        because the tariff library always expects (12, 24).
        """
        region = self._make_region([GANSU_ROW])   # shape (1, 24), not (12, 24) → also wrong
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "E-TARIFF-SHAPE" in rule_ids

    def test_wrong_month_count_fires_error(self):
        """6 rows (shape (6,24)) must fire E-TARIFF-SHAPE.

        Hand-computed: need exactly 12 rows (Jan–Dec). 6 rows is wrong → error.
        """
        region = self._make_region([GANSU_ROW] * 6)
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "E-TARIFF-SHAPE" in rule_ids

    def test_wrong_hour_count_fires_error(self):
        """24 rows of 12 entries each (shape (24,12)) must fire E-TARIFF-SHAPE.

        Transposed shape — caught by the (12,24) check.
        """
        row_12 = GANSU_ROW[:12]  # 12 entries
        region = self._make_region([row_12] * 24)
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "E-TARIFF-SHAPE" in rule_ids

    def test_correct_shape_no_error(self):
        """A valid (12,24) table must NOT fire E-TARIFF-SHAPE."""
        region = self._make_region([GANSU_ROW] * 12)
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "E-TARIFF-SHAPE" not in rule_ids

    def test_e_tariff_shape_is_error_not_warning(self):
        """E-TARIFF-SHAPE must be severity ERROR (HARD), not WARNING (§5)."""
        region = self._make_region([GANSU_ROW] * 6)
        issues = validate_tariff_region(region)
        shape_issues = [i for i in issues if i.rule_id == "E-TARIFF-SHAPE"]
        assert len(shape_issues) >= 1
        assert shape_issues[0].severity == "error", (
            f"E-TARIFF-SHAPE must be 'error', got '{shape_issues[0].severity}'"
        )


# ---------------------------------------------------------------------------
# 6. Validation — W-TARIFF-PRICE-NEG (WARNING)
# ---------------------------------------------------------------------------

class TestValidationWTariffPriceNeg:
    """W-TARIFF-PRICE-NEG warns when any price entry is negative."""

    def test_negative_price_fires_warning(self):
        """One negative entry in month 0, hour 0 must fire W-TARIFF-PRICE-NEG.

        Hand-computed: GANSU_ROW[0] = 250 (valley). Replace with -1.0 → negative.
        """
        bad_row = list(GANSU_ROW)
        bad_row[0] = -1.0  # h=0, month 0 → -1.0 < 0
        region = {
            "currency": "CNY",
            "price_table_yuan_per_mwh": [bad_row] + [GANSU_ROW] * 11,
            "demand_rate_yuan_per_mw_month": 32000.0,
            "sell_clamp": {"spread_yuan_per_mwh": 30.0, "spread_noise_std_yuan_per_mwh": 10.0},
        }
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "W-TARIFF-PRICE-NEG" in rule_ids

    def test_negative_price_is_warning_not_error(self):
        """W-TARIFF-PRICE-NEG must be severity WARNING (not error; negative prices exist in
        real markets — contract §5 explicitly defers hard enforcement)."""
        bad_row = list(GANSU_ROW)
        bad_row[0] = -1.0
        region = {
            "currency": "CNY",
            "price_table_yuan_per_mwh": [bad_row] + [GANSU_ROW] * 11,
            "demand_rate_yuan_per_mw_month": 32000.0,
            "sell_clamp": {"spread_yuan_per_mwh": 30.0, "spread_noise_std_yuan_per_mwh": 10.0},
        }
        issues = validate_tariff_region(region)
        neg_issues = [i for i in issues if i.rule_id == "W-TARIFF-PRICE-NEG"]
        assert len(neg_issues) >= 1
        assert neg_issues[0].severity == "warning", (
            f"W-TARIFF-PRICE-NEG must be 'warning', got '{neg_issues[0].severity}'"
        )

    def test_all_positive_prices_no_warning(self):
        """A table with all non-negative entries must NOT fire W-TARIFF-PRICE-NEG."""
        region = {
            "currency": "CNY",
            "price_table_yuan_per_mwh": [GANSU_ROW] * 12,
            "demand_rate_yuan_per_mw_month": 32000.0,
            "sell_clamp": {"spread_yuan_per_mwh": 30.0, "spread_noise_std_yuan_per_mwh": 10.0},
        }
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "W-TARIFF-PRICE-NEG" not in rule_ids

    def test_zero_price_no_warning(self):
        """A price of exactly 0.0 must NOT fire W-TARIFF-PRICE-NEG (rule is strictly < 0).

        Hand-computed: 0.0 is the boundary; rule is 'iff any < 0', so 0.0 is fine.
        """
        zero_row = [0.0] + list(GANSU_ROW[1:])  # h=0 set to 0.0
        region = {
            "currency": "CNY",
            "price_table_yuan_per_mwh": [zero_row] + [GANSU_ROW] * 11,
            "demand_rate_yuan_per_mw_month": 32000.0,
            "sell_clamp": {"spread_yuan_per_mwh": 30.0, "spread_noise_std_yuan_per_mwh": 10.0},
        }
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "W-TARIFF-PRICE-NEG" not in rule_ids


# ---------------------------------------------------------------------------
# 7. Validation — W-TARIFF-SPREAD-NEG (WARNING)
# ---------------------------------------------------------------------------

class TestValidationWTariffSpreadNeg:
    """W-TARIFF-SPREAD-NEG warns when spread or spread_σ is negative."""

    def _valid_region(self, spread=30.0, std=10.0):
        return {
            "currency": "CNY",
            "price_table_yuan_per_mwh": [GANSU_ROW] * 12,
            "demand_rate_yuan_per_mw_month": 32000.0,
            "sell_clamp": {"spread_yuan_per_mwh": spread, "spread_noise_std_yuan_per_mwh": std},
        }

    def test_negative_spread_fires_warning(self):
        """spread_yuan_per_mwh < 0 → sell > buy by default → risk-free arbitrage risk (D7)."""
        region = self._valid_region(spread=-5.0)
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "W-TARIFF-SPREAD-NEG" in rule_ids

    def test_negative_spread_std_fires_warning(self):
        """spread_noise_std_yuan_per_mwh < 0 → negative σ is mathematically incoherent."""
        region = self._valid_region(std=-1.0)
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "W-TARIFF-SPREAD-NEG" in rule_ids

    def test_zero_spread_no_warning(self):
        """spread=0 → deterministic zero discount, valid (sell == buy — unusual but not wrong).

        Hand-computed: rule is 'iff spread < 0'; 0.0 is not < 0, no warning.
        """
        region = self._valid_region(spread=0.0)
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "W-TARIFF-SPREAD-NEG" not in rule_ids

    def test_zero_std_no_warning(self):
        """std=0 → deterministic spread, valid (no noise).

        Hand-computed: rule is 'iff std < 0'; 0.0 is not < 0, no warning.
        """
        region = self._valid_region(std=0.0)
        issues = validate_tariff_region(region)
        rule_ids = [i.rule_id for i in issues]
        assert "W-TARIFF-SPREAD-NEG" not in rule_ids

    def test_spread_neg_is_warning_not_error(self):
        """W-TARIFF-SPREAD-NEG must be severity WARNING."""
        region = self._valid_region(spread=-5.0)
        issues = validate_tariff_region(region)
        spread_issues = [i for i in issues if i.rule_id == "W-TARIFF-SPREAD-NEG"]
        assert len(spread_issues) >= 1
        assert spread_issues[0].severity == "warning"


# ---------------------------------------------------------------------------
# 8. ValidationIssue schema check
# ---------------------------------------------------------------------------

class TestValidationIssueSchema:
    """ValidationIssue instances returned by validate_tariff_region must have the
    correct fields (compatible with config_validation.ValidationIssue shape — §6)."""

    def test_issue_has_rule_id_severity_message(self):
        """Every ValidationIssue must have rule_id, severity, and message fields."""
        region = {
            "currency": "CNY",
            "price_table_yuan_per_mwh": [GANSU_ROW] * 6,  # wrong shape → E-TARIFF-SHAPE
            "demand_rate_yuan_per_mw_month": 32000.0,
            "sell_clamp": {"spread_yuan_per_mwh": 30.0, "spread_noise_std_yuan_per_mwh": 10.0},
        }
        issues = validate_tariff_region(region)
        assert len(issues) >= 1
        for issue in issues:
            assert hasattr(issue, "rule_id"), "ValidationIssue missing 'rule_id'"
            assert hasattr(issue, "severity"), "ValidationIssue missing 'severity'"
            assert hasattr(issue, "message"), "ValidationIssue missing 'message'"
            assert issue.severity in ("error", "warning"), (
                f"severity must be 'error' or 'warning', got '{issue.severity}'"
            )
