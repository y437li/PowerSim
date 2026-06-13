"""
Tests for the China device benchmark library.
Contract: contracts/shared/benchmark_device_library.md

Verifies:
- All expected model IDs present (T1-T2)
- ID format invariant (T3)
- Provenance fields (T4-T5, T15)
- Existing Gansu entries untouched (T6)
- Per-type physics field completeness and invariants (T7-T11)
- Electrolyzer technology monotonics (T12)
- Non-negative economics (T13)
- SST stub shape (T14)
"""
import re
from pathlib import Path

import pytest
import yaml

# ── Load fixture ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
DEVICE_MODELS_PATH = REPO_ROOT / "config" / "device_models.yaml"


@pytest.fixture(scope="module")
def dm():
    """Load device_models.yaml once for all tests."""
    with open(DEVICE_MODELS_PATH) as f:
        data = yaml.safe_load(f)
    return data


@pytest.fixture(scope="module")
def models(dm):
    return dm["models"]


# ── T1 — Schema version ───────────────────────────────────────────────────────

def test_schema_version(dm):
    """T1: schema_version must be '2.1.0' after benchmark entries land."""
    assert dm["schema_version"] == "2.1.0", (
        f"Expected '2.1.0', got {dm['schema_version']!r}. "
        "Benchmark library is a minor (additive) bump from 2.0.0."
    )


# ── T2 — All expected IDs present ────────────────────────────────────────────

EXPECTED_IDS = [
    # Existing Gansu parity set (untouched)
    "vestas-v150-4.2",
    "trina-vertex-n-670w",
    "catl-lmp-300mwh",
    "pcc-substation-945mw",
    # Wind benchmark (China 2024 onshore)
    "goldwind-gw165-6.0",
    "envision-en136-3.6",
    "windey-wd156-3.0",
    # PV benchmark (n-type TOPCon)
    "longi-hi-mo-x6-610w",
    "jasolar-deepblue4-615w",
    # BESS benchmark (LFP grid-scale)
    "byd-mc-cube-lfp",
    "sungrow-lfp-lc",
    # Grid benchmark + SST stub
    "pcc-traditional-220kv",
    "pcc-sst-stub",
    # Electrolyzer benchmark (§8.2 four types)
    "electrolyzer-alk-20mw",
    "electrolyzer-pem-10mw",
    "electrolyzer-aem-1mw",
    "electrolyzer-soec-5mw",
]


@pytest.mark.parametrize("model_id", EXPECTED_IDS)
def test_expected_id_present(models, model_id):
    """T2: All expected model IDs must be present in models dict."""
    assert model_id in models, f"Missing model: {model_id!r}"


# ── T3 — ID format ────────────────────────────────────────────────────────────

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")


def test_all_ids_format(models):
    """T3: Every model ID must match ^[a-z0-9][a-z0-9.-]*$ (D23 cross-area invariant)."""
    bad = [mid for mid in models if not ID_PATTERN.match(mid)]
    assert not bad, f"Model IDs violate format constraint: {bad}"


# ── T4 — All models have provenance ──────────────────────────────────────────

@pytest.mark.parametrize("model_id", EXPECTED_IDS)
def test_provenance_present(models, model_id):
    """T4: Every model entry must have a non-empty string provenance field."""
    entry = models[model_id]
    assert "provenance" in entry, f"{model_id!r} missing 'provenance' field"
    assert isinstance(entry["provenance"], str), (
        f"{model_id!r} provenance must be str, got {type(entry['provenance'])}"
    )
    assert entry["provenance"].strip(), f"{model_id!r} provenance must be non-empty"


# ── T5 — SST stub provenance ─────────────────────────────────────────────────

def test_sst_stub_provenance(models):
    """T5: SST stub must carry the exact USER-paused provenance marker."""
    assert models["pcc-sst-stub"]["provenance"] == "USER-provided, pending", (
        "pcc-sst-stub provenance must be exactly 'USER-provided, pending' "
        "(CLAUDE.md public-repo rule; SST paused by USER)"
    )


# ── T6 — Existing Gansu entries untouched ────────────────────────────────────

GANSU_PHYSICS_PINS = {
    # vestas-v150-4.2 (wind_turbine) — device_model_schema.md §6
    ("vestas-v150-4.2", "v_cutin_mps"): 3.0,
    ("vestas-v150-4.2", "v_rated_mps"): 12.0,
    ("vestas-v150-4.2", "v_cutout_mps"): 25.0,
    ("vestas-v150-4.2", "rated_mw_per_unit"): 4.2,
    # trina-vertex-n-670w (pv_panel)
    ("trina-vertex-n-670w", "k_T_per_c"): -0.003,
    ("trina-vertex-n-670w", "eta_inverter"): 0.97,
    # catl-lmp-300mwh (battery) — D4 binding
    ("catl-lmp-300mwh", "eta_ch"): 0.97,
    ("catl-lmp-300mwh", "eta_dis"): 0.97,
    ("catl-lmp-300mwh", "soc_min"): 0.2,
    ("catl-lmp-300mwh", "soc_max"): 0.9,
    ("catl-lmp-300mwh", "capacity_mwh_per_unit"): 300.0,
    # pcc-substation-945mw (grid_connection) — D5/D12 binding
    ("pcc-substation-945mw", "max_export_mw"): 945.0,
    ("pcc-substation-945mw", "max_import_mw"): 400.0,
}


@pytest.mark.parametrize("model_id,field,expected", [
    (mid, fld, val) for (mid, fld), val in GANSU_PHYSICS_PINS.items()
])
def test_gansu_physics_untouched(models, model_id, field, expected):
    """T6: Existing Gansu physics constants must be bit-identical to LOCKED values."""
    actual = models[model_id]["physics"][field]
    assert actual == pytest.approx(expected, rel=1e-9), (
        f"{model_id}.physics.{field}: expected {expected}, got {actual}. "
        "Gansu physics is LOCKED (device_model_schema.md v2.0.0)."
    )


# ── T7 — Wind turbine physics ────────────────────────────────────────────────

WIND_IDS = [
    mid for mid in EXPECTED_IDS
    if mid in ("vestas-v150-4.2", "goldwind-gw165-6.0", "envision-en136-3.6", "windey-wd156-3.0")
]

WIND_REQUIRED_FIELDS = [
    "v_cutin_mps", "v_rated_mps", "v_cutout_mps", "hub_height_m", "rated_mw_per_unit"
]


@pytest.mark.parametrize("model_id", WIND_IDS)
def test_wind_required_fields(models, model_id):
    """T7a: Wind turbines must have all required physics fields."""
    p = models[model_id]["physics"]
    missing = [f for f in WIND_REQUIRED_FIELDS if f not in p]
    assert not missing, f"{model_id!r} missing wind physics fields: {missing}"


@pytest.mark.parametrize("model_id", WIND_IDS)
def test_wind_speed_invariant(models, model_id):
    """T7b: Wind speed invariant — 0 < v_cutin < v_rated < v_cutout.
    Hand-computed expected: goldwind 3.0 < 10.5 < 22.0; envision 3.0 < 11.0 < 20.0;
    windey 3.0 < 11.5 < 20.0; vestas 3.0 < 12.0 < 25.0 — all pass.
    """
    p = models[model_id]["physics"]
    assert 0 < p["v_cutin_mps"] < p["v_rated_mps"] < p["v_cutout_mps"], (
        f"{model_id}: v_cutin={p['v_cutin_mps']} must be < v_rated={p['v_rated_mps']} "
        f"must be < v_cutout={p['v_cutout_mps']}"
    )


@pytest.mark.parametrize("model_id", WIND_IDS)
def test_wind_rated_mw_positive(models, model_id):
    """T7c: Rated MW per unit must be positive."""
    assert models[model_id]["physics"]["rated_mw_per_unit"] > 0


# ── T8 — PV panel physics ────────────────────────────────────────────────────

PV_IDS = [
    mid for mid in EXPECTED_IDS
    if mid in ("trina-vertex-n-670w", "longi-hi-mo-x6-610w", "jasolar-deepblue4-615w")
]

PV_REQUIRED_FIELDS = ["k_T_per_c", "eta_inverter", "degradation_yr1"]


@pytest.mark.parametrize("model_id", PV_IDS)
def test_pv_required_fields(models, model_id):
    """T8a: PV panels must have all required physics fields."""
    p = models[model_id]["physics"]
    missing = [f for f in PV_REQUIRED_FIELDS if f not in p]
    assert not missing, f"{model_id!r} missing PV physics fields: {missing}"


@pytest.mark.parametrize("model_id", PV_IDS)
def test_pv_physics_invariants(models, model_id):
    """T8b: PV physics invariants — k_T < 0; 0 < eta_inv ≤ 1; 0 < deg ≤ 1.
    Hand-computed: trina k_T=-0.003 (neg ✓); longi k_T=-0.0029 (neg ✓);
    jasolar k_T=-0.0028 (neg ✓); all eta_inv=0.97 or 0.985 (∈(0,1] ✓);
    all degradation_yr1=0.98 (∈(0,1] ✓).
    """
    p = models[model_id]["physics"]
    assert p["k_T_per_c"] < 0, f"{model_id}: k_T_per_c must be negative (temperature penalty)"
    assert 0 < p["eta_inverter"] <= 1.0, f"{model_id}: eta_inverter must be in (0, 1]"
    assert 0 < p["degradation_yr1"] <= 1.0, f"{model_id}: degradation_yr1 must be in (0, 1]"


# ── T9 — Battery physics ─────────────────────────────────────────────────────

BAT_IDS = [
    mid for mid in EXPECTED_IDS
    if mid in ("catl-lmp-300mwh", "byd-mc-cube-lfp", "sungrow-lfp-lc")
]

BAT_REQUIRED_FIELDS = [
    "eta_ch", "eta_dis", "soc_min", "soc_max", "capacity_mwh_per_unit", "power_mw_per_unit"
]


@pytest.mark.parametrize("model_id", BAT_IDS)
def test_battery_required_fields(models, model_id):
    """T9a: Batteries must have all required physics fields."""
    p = models[model_id]["physics"]
    missing = [f for f in BAT_REQUIRED_FIELDS if f not in p]
    assert not missing, f"{model_id!r} missing battery physics fields: {missing}"


@pytest.mark.parametrize("model_id", BAT_IDS)
def test_battery_physics_invariants(models, model_id):
    """T9b: Battery physics invariants.
    Hand-computed: CATL eta_ch=eta_dis=0.97 (∈(0,1] ✓); BYD 0.965 ✓; Sungrow 0.97 ✓;
    CATL soc [0.2, 0.9] (0≤min<max≤1 ✓); BYD [0.10, 0.90] ✓; Sungrow [0.05, 0.95] ✓;
    CATL cap=300.0 MW ✓; BYD 2.0 MWh ✓; Sungrow 5.0 MWh ✓.
    """
    p = models[model_id]["physics"]
    assert 0 < p["eta_ch"] <= 1.0, f"{model_id}: eta_ch must be in (0, 1]"
    assert 0 < p["eta_dis"] <= 1.0, f"{model_id}: eta_dis must be in (0, 1]"
    assert 0 <= p["soc_min"] < p["soc_max"] <= 1.0, (
        f"{model_id}: soc bounds must satisfy 0 ≤ soc_min < soc_max ≤ 1; "
        f"got [{p['soc_min']}, {p['soc_max']}]"
    )
    assert p["capacity_mwh_per_unit"] > 0, f"{model_id}: capacity must be positive"
    assert p["power_mw_per_unit"] > 0, f"{model_id}: power must be positive"


# ── T10 — Grid connection physics ────────────────────────────────────────────

GRID_IDS = [
    mid for mid in EXPECTED_IDS
    if mid in ("pcc-substation-945mw", "pcc-traditional-220kv", "pcc-sst-stub")
]

GRID_REQUIRED_FIELDS = ["max_export_mw", "max_import_mw"]


@pytest.mark.parametrize("model_id", GRID_IDS)
def test_grid_required_fields(models, model_id):
    """T10a: Grid connections must have required physics fields."""
    p = models[model_id]["physics"]
    missing = [f for f in GRID_REQUIRED_FIELDS if f not in p]
    assert not missing, f"{model_id!r} missing grid physics fields: {missing}"


@pytest.mark.parametrize("model_id", GRID_IDS)
def test_grid_physics_non_negative(models, model_id):
    """T10b: Export and import limits must be non-negative.
    Hand-computed: pcc-945 (945.0, 400.0) ✓; traditional-220kv (200.0, 200.0) ✓;
    sst-stub (200.0, 200.0) placeholder ✓.
    """
    p = models[model_id]["physics"]
    assert p["max_export_mw"] >= 0, f"{model_id}: max_export_mw must be ≥ 0"
    assert p["max_import_mw"] >= 0, f"{model_id}: max_import_mw must be ≥ 0"


# ── T11 — Electrolyzer physics ───────────────────────────────────────────────

ELY_IDS = [
    "electrolyzer-alk-20mw",
    "electrolyzer-pem-10mw",
    "electrolyzer-aem-1mw",
    "electrolyzer-soec-5mw",
]

ELY_REQUIRED_FIELDS = [
    "min_load_fraction", "standby_fraction", "e_spec_kwh_per_kg",
    "degradation_yuan_per_mwh", "rated_mw_per_unit", "warmup_minutes",
]


@pytest.mark.parametrize("model_id", ELY_IDS)
def test_electrolyzer_type(models, model_id):
    """T11a: Electrolyzer entries must have type 'electrolyzer'."""
    assert models[model_id]["type"] == "electrolyzer", (
        f"{model_id}: type must be 'electrolyzer'"
    )


@pytest.mark.parametrize("model_id", ELY_IDS)
def test_electrolyzer_required_fields(models, model_id):
    """T11b: Electrolyzers must have all §8.2 physics fields."""
    p = models[model_id]["physics"]
    missing = [f for f in ELY_REQUIRED_FIELDS if f not in p]
    assert not missing, f"{model_id!r} missing electrolyzer physics fields: {missing}"


@pytest.mark.parametrize("model_id", ELY_IDS)
def test_electrolyzer_physics_invariants(models, model_id):
    """T11c: Electrolyzer physics invariants (contract §2.1).
    Hand-computed per model:
      ALK: min_load=0.20 ∈(0,1] ✓; standby=0.02 ∈[0,min) ✓ (0.02<0.20);
           e_spec=52.0>0 ✓; degrad=4.0≥0 ✓; rated=20.0>0 ✓; warmup=30.0≥0 ✓.
      PEM: min_load=0.05 ∈(0,1] ✓; standby=0.01 ∈[0,min) ✓ (0.01<0.05);
           e_spec=55.0>0 ✓; degrad=8.0≥0 ✓; rated=10.0>0 ✓; warmup=5.0≥0 ✓.
      AEM: min_load=0.05; standby=0.01 (0.01<0.05 ✓); e_spec=53.0; degrad=10.0; rated=2.4; warmup=5.0.
      SOEC: min_load=0.20; standby=0.05 (0.05<0.20 ✓); e_spec=40.0; degrad=15.0; rated=5.0; warmup=240.0.
    """
    p = models[model_id]["physics"]
    assert 0 < p["min_load_fraction"] <= 1.0, (
        f"{model_id}: min_load_fraction must be in (0, 1]; got {p['min_load_fraction']}"
    )
    assert 0 <= p["standby_fraction"] < p["min_load_fraction"], (
        f"{model_id}: standby_fraction={p['standby_fraction']} must be < "
        f"min_load_fraction={p['min_load_fraction']} (standby < operating minimum)"
    )
    assert p["e_spec_kwh_per_kg"] > 0, f"{model_id}: e_spec_kwh_per_kg must be > 0"
    assert p["degradation_yuan_per_mwh"] >= 0, f"{model_id}: degradation_yuan_per_mwh must be ≥ 0"
    assert p["rated_mw_per_unit"] > 0, f"{model_id}: rated_mw_per_unit must be > 0"
    assert p["warmup_minutes"] >= 0, f"{model_id}: warmup_minutes must be ≥ 0"


# ── T12 — Electrolyzer technology monotonics ──────────────────────────────────

def test_electrolyzer_e_spec_monotonics(models):
    """T12a: SOEC < ALK specific energy (SOEC uses heat input; lower net electrical e_spec).
    Hand-computed: SOEC 40.0 < ALK 52.0 — SOEC net electrical energy lower because
    high-temp heat input supplements; ALK system losses yield 52 kWh/kg (IEA 2023).
    """
    soec = models["electrolyzer-soec-5mw"]["physics"]["e_spec_kwh_per_kg"]
    alk = models["electrolyzer-alk-20mw"]["physics"]["e_spec_kwh_per_kg"]
    # 40.0 < 52.0 ✓
    assert soec < alk, (
        f"SOEC e_spec ({soec}) should be < ALK e_spec ({alk}): "
        "SOEC uses heat input so net electrical kWh/kg is lower"
    )


def test_electrolyzer_degradation_monotonics(models):
    """T12b: ALK < PEM < AEM < SOEC degradation (increasing technology immaturity).
    Hand-computed: 4.0 < 8.0 < 10.0 < 15.0 ✓ — all are ¥/MWh throughput (§8.2).
    """
    alk = models["electrolyzer-alk-20mw"]["physics"]["degradation_yuan_per_mwh"]
    pem = models["electrolyzer-pem-10mw"]["physics"]["degradation_yuan_per_mwh"]
    aem = models["electrolyzer-aem-1mw"]["physics"]["degradation_yuan_per_mwh"]
    soec = models["electrolyzer-soec-5mw"]["physics"]["degradation_yuan_per_mwh"]
    # 4.0 < 8.0 < 10.0 < 15.0
    assert alk < pem < aem < soec, (
        f"Degradation order violated: ALK={alk}, PEM={pem}, AEM={aem}, SOEC={soec}. "
        "Expected ALK < PEM < AEM < SOEC (increasing immaturity of technology)"
    )


def test_electrolyzer_min_load_alk_gt_pem(models):
    """T12c: ALK min_load > PEM min_load — defining characteristic of alkaline technology.
    Hand-computed: ALK 0.20 > PEM 0.05 ✓ (§8.2 states "20–100%" vs "5–100%").
    """
    alk = models["electrolyzer-alk-20mw"]["physics"]["min_load_fraction"]
    pem = models["electrolyzer-pem-10mw"]["physics"]["min_load_fraction"]
    # 0.20 > 0.05
    assert alk > pem, (
        f"ALK min_load_fraction ({alk}) must be > PEM ({pem}): "
        "alkaline electrolyzer limited turndown is the defining §8.2 characteristic"
    )


def test_electrolyzer_capex_order(models):
    """T12d: ALK CAPEX < PEM CAPEX < AEM CAPEX < SOEC CAPEX (2024 market pricing order).
    Hand-computed: 3500 < 6500 < 8500 < 14000 ¥/kW ✓ (IRENA 2023 / IEA 2023 order).
    """
    alk = models["electrolyzer-alk-20mw"]["economics"]["capex_per_kw_yuan"]
    pem = models["electrolyzer-pem-10mw"]["economics"]["capex_per_kw_yuan"]
    aem = models["electrolyzer-aem-1mw"]["economics"]["capex_per_kw_yuan"]
    soec = models["electrolyzer-soec-5mw"]["economics"]["capex_per_kw_yuan"]
    # 3500 < 6500 < 8500 < 14000
    assert alk < pem < aem < soec, (
        f"CAPEX order violated: ALK={alk}, PEM={pem}, AEM={aem}, SOEC={soec}. "
        "Expected ALK < PEM < AEM < SOEC (established public market pricing hierarchy)"
    )


# ── T13 — Non-negative economics ─────────────────────────────────────────────

FRACTION_FIELDS = {"replacement_cost_fraction", "residual_value_fraction", "eol_soh_threshold"}


@pytest.mark.parametrize("model_id", EXPECTED_IDS)
def test_economics_non_negative(models, model_id):
    """T13: All economics numeric values must be ≥ 0; fraction fields must be in [0, 1]."""
    econ = models[model_id].get("economics", {})
    if not econ:
        return  # empty / stub economics is ok
    for field, value in econ.items():
        if not isinstance(value, (int, float)):
            continue
        assert value >= 0, f"{model_id}.economics.{field} = {value} must be ≥ 0"
        if field in FRACTION_FIELDS:
            assert value <= 1.0, (
                f"{model_id}.economics.{field} = {value} is a fraction field; must be ≤ 1.0"
            )


# ── T14 — SST stub shape ─────────────────────────────────────────────────────

def test_sst_stub_physics(models):
    """T14: SST stub must have float max_export_mw and max_import_mw physics fields."""
    p = models["pcc-sst-stub"]["physics"]
    assert "max_export_mw" in p, "pcc-sst-stub missing max_export_mw"
    assert "max_import_mw" in p, "pcc-sst-stub missing max_import_mw"
    assert isinstance(p["max_export_mw"], (int, float))
    assert isinstance(p["max_import_mw"], (int, float))


def test_sst_stub_economics_empty(models):
    """T14b: SST stub economics must be empty or absent — no proprietary data committed.
    (PUBLIC REPO rule: PAUSED by USER; stub only.)
    """
    econ = models["pcc-sst-stub"].get("economics", {})
    assert econ == {} or econ is None, (
        f"pcc-sst-stub economics must be empty (no proprietary SST data); got: {econ}"
    )


# ── T15 — Gansu entries have provenance (reviewer:) ───────────────────────────

GANSU_IDS = ["vestas-v150-4.2", "trina-vertex-n-670w", "catl-lmp-300mwh", "pcc-substation-945mw"]


@pytest.mark.parametrize("model_id", GANSU_IDS)  # reviewer:
def test_gansu_entries_have_provenance(models, model_id):
    """T15 (reviewer-added): Original 4 Gansu entries must also have provenance field.
    This PR adds provenance documentation to the initial Gansu entries for full
    PUBLIC REPO compliance (CLAUDE.md public-repo rule / D32).
    """
    entry = models[model_id]
    assert "provenance" in entry, (
        f"{model_id!r}: Gansu entry must have a provenance field "
        "(this PR documents original source for public-repo compliance)"
    )
    assert entry["provenance"].strip(), f"{model_id!r}: provenance must be non-empty"
