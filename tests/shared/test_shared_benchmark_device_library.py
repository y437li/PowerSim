"""
Tests for the China device benchmark library.
Contract: contracts/shared/benchmark_device_library.md

Verifies:
- All expected model IDs present (T1-T2)
- ID format invariant (T3)
- Provenance fields (T4-T5, T15)
- Existing Gansu entries untouched (T6)
- Per-type physics field completeness and invariants (T7-T11)
- Electrolyzer technology comparison monotonics (T12)
- Non-negative economics (T13)
- SST stub shape (T14)

Electrolyzer entries (T11/T12): cleared by rl-architect (LINEAGE D35).
4 entries (ALK/PEM/AEM/SOEC) land as INERT reference data while the H₂
scenario stays gated (analog of D23).  Resolver ignores type=electrolyzer
until contracts/env/electrolyzer.md activates the scenario.

NOTE — Backend-reviewer: your tests test_every_model_has_valid_type and
test_per_type_coverage_exhaustive need updating for this PR:
  1. Add 'electrolyzer' to VALID_TYPES (D35 cleared it)
  2. Add | set(ELY_IDS) to the covered set in test_per_type_coverage_exhaustive
Please update those tests as part of your review and re-post APPROVE.
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
    """T1: schema_version must be '2.2.0' after electrolyzer entries land (D35).
    Version history: 2.0.0 (PR #87 price_table reshape) → 2.1.0 (PR #103 benchmark library)
    → 2.2.0 (this PR: electrolyzer device type + 4 INERT entries; D35).
    """
    assert dm["schema_version"] == "2.2.0", (
        f"Expected '2.2.0', got {dm['schema_version']!r}. "
        "Electrolyzer entries (D35) are a minor additive bump from 2.1.0 (no re-LOCK)."
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
    # Electrolyzer benchmark (INERT reference data — LINEAGE D35)
    # AEM: electrolyzer-aem-2.4mw (nameplate 2.4 MW per Enapter EL 4.0 public spec)
    "electrolyzer-alk-20mw",
    "electrolyzer-pem-10mw",
    "electrolyzer-aem-2.4mw",
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


# ── T11 — Electrolyzer physics (D35: INERT reference data) ──────────────────
# rl-architect cleared electrolyzer entries (LINEAGE D35): minor additive to
# device_model_schema; INERT reference data; H₂ scenario stays gated.
# AEM (electrolyzer-aem-2.4mw) + SOEC are NOT in §8.2 — benchmark-sourced
# with explicit public-source provenance (D35 condition 2).

ELY_IDS = [
    "electrolyzer-alk-20mw",
    "electrolyzer-pem-10mw",
    "electrolyzer-aem-2.4mw",
    "electrolyzer-soec-5mw",
]

ELY_REQUIRED_FIELDS = [
    "min_load_fraction",        # §8.2-verbatim for ALK/PEM; benchmark for AEM/SOEC
    "standby_fraction",         # same
    "e_spec_kwh_per_kg",        # same
    "degradation_yuan_per_mwh", # same
    "rated_mw_per_unit",        # same
    "warmup_minutes",           # provisional — §8.2 prose; env ignores at Δt=1h (D35 cond. 1)
]


@pytest.mark.parametrize("model_id", ELY_IDS)
def test_electrolyzer_required_fields(models, model_id):
    """T11a: Electrolyzers must have all required physics fields.
    §8.2-verbatim for ALK + PEM; benchmark-sourced with public provenance for AEM + SOEC.
    warmup_minutes is provisional (§8.2 prose; env ignores at Δt=1h; D35 condition 1).
    """
    p = models[model_id]["physics"]
    missing = [f for f in ELY_REQUIRED_FIELDS if f not in p]
    assert not missing, f"{model_id!r} missing electrolyzer physics fields: {missing}"


@pytest.mark.parametrize("model_id", ELY_IDS)
def test_electrolyzer_physics_invariants(models, model_id):
    """T11b: Electrolyzer physics invariants (contract §2.1).
    Hand-computed:
      ALK  (§8.2-verbatim): min_load=0.20, standby=0.02; 0<0.20≤1 ✓; 0≤0.02<0.20 ✓; e_spec=52.0>0 ✓; degrad=4.0≥0 ✓; rated=20.0>0 ✓; warmup=30.0≥0 ✓
      PEM  (§8.2-verbatim): min_load=0.05, standby=0.01; 0<0.05≤1 ✓; 0≤0.01<0.05 ✓; e_spec=55.0>0 ✓; degrad=8.0≥0 ✓; rated=10.0>0 ✓; warmup=5.0≥0 ✓
      AEM  (benchmark):     min_load=0.05, standby=0.01; 0<0.05≤1 ✓; 0≤0.01<0.05 ✓; e_spec=53.0>0 ✓; degrad=10.0≥0 ✓; rated=2.4>0 ✓; warmup=5.0≥0 ✓
      SOEC (benchmark):     min_load=0.20, standby=0.05; 0<0.20≤1 ✓; 0≤0.05<0.20 ✓; e_spec=40.0>0 ✓; degrad=15.0≥0 ✓; rated=5.0>0 ✓; warmup=240.0≥0 ✓
    """
    p = models[model_id]["physics"]
    assert 0 < p["min_load_fraction"] <= 1.0, (
        f"{model_id}: min_load_fraction={p['min_load_fraction']} must be in (0, 1]"
    )
    assert 0 <= p["standby_fraction"] < p["min_load_fraction"], (
        f"{model_id}: standby_fraction={p['standby_fraction']} must satisfy "
        f"0 ≤ standby < min_load={p['min_load_fraction']} (standby < minimum operating)"
    )
    assert p["e_spec_kwh_per_kg"] > 0, (
        f"{model_id}: e_spec_kwh_per_kg={p['e_spec_kwh_per_kg']} must be positive"
    )
    assert p["degradation_yuan_per_mwh"] >= 0, (
        f"{model_id}: degradation_yuan_per_mwh must be ≥ 0"
    )
    assert p["rated_mw_per_unit"] > 0, (
        f"{model_id}: rated_mw_per_unit must be positive"
    )
    assert p["warmup_minutes"] >= 0, (
        f"{model_id}: warmup_minutes must be ≥ 0 (provisional field; informational only)"
    )


# ── T12 — Electrolyzer technology comparison monotonics ──────────────────────


def test_electrolyzer_technology_monotonics(models):
    """T12a: Technology monotonics hold across all 4 electrolyzer entries (§8.2 + public domain).
    ALK  (§8.2-verbatim): min_load=0.20, e_spec=52.0, degrad=4.0
    PEM  (§8.2-verbatim): min_load=0.05, e_spec=55.0, degrad=8.0
    AEM  (benchmark):     e_spec=53.0, degrad=10.0
    SOEC (benchmark):     min_load=0.20, e_spec=40.0, degrad=15.0

    Assertions:
      - ALK min_load > PEM min_load: 0.20 > 0.05 ✓  (alkaline limited turndown; §8.2 defining characteristic)
      - SOEC e_spec < ALK e_spec:    40.0 < 52.0 ✓  (SOEC uses heat input → lower net electrical e_spec; IEA 2023)
      - ALK e_spec < PEM e_spec:     52.0 < 55.0 ✓  (IEA 2023: PEM system-level e_spec slightly higher than ALK)
      - degrad strictly increasing:  4.0 < 8.0 < 10.0 < 15.0 ✓  (ALK < PEM < AEM < SOEC; increasing immaturity)
    """
    alk  = models["electrolyzer-alk-20mw"]["physics"]
    pem  = models["electrolyzer-pem-10mw"]["physics"]
    aem  = models["electrolyzer-aem-2.4mw"]["physics"]
    soec = models["electrolyzer-soec-5mw"]["physics"]

    assert alk["min_load_fraction"] > pem["min_load_fraction"], (
        f"ALK min_load={alk['min_load_fraction']} must be > PEM min_load={pem['min_load_fraction']} "
        "(alkaline limited turndown is a defining technology characteristic; §8.2)"
    )
    assert soec["e_spec_kwh_per_kg"] < alk["e_spec_kwh_per_kg"], (
        f"SOEC e_spec={soec['e_spec_kwh_per_kg']} must be < ALK e_spec={alk['e_spec_kwh_per_kg']} "
        "(SOEC uses heat input; lower net electrical specific energy; IEA 2023)"
    )
    assert alk["e_spec_kwh_per_kg"] < pem["e_spec_kwh_per_kg"], (
        f"ALK e_spec={alk['e_spec_kwh_per_kg']} must be < PEM e_spec={pem['e_spec_kwh_per_kg']} "
        "(IEA 2023: PEM system-level e_spec slightly higher than ALK)"
    )
    assert (alk["degradation_yuan_per_mwh"]
            < pem["degradation_yuan_per_mwh"]
            < aem["degradation_yuan_per_mwh"]
            < soec["degradation_yuan_per_mwh"]), (
        f"Degradation must increase with technology immaturity: "
        f"ALK={alk['degradation_yuan_per_mwh']} < PEM={pem['degradation_yuan_per_mwh']} "
        f"< AEM={aem['degradation_yuan_per_mwh']} < SOEC={soec['degradation_yuan_per_mwh']}"
    )


def test_electrolyzer_capex_monotonic(models):
    """T12b: CAPEX increases with technology immaturity (public 2024 pricing).
    Hand-computed: ALK=3500 < PEM=6500 < AEM=8500 < SOEC=14000 ¥/kW ✓
    (Source: IRENA 2020 + IEA 2023 + Enapter/Sunfire public 2024 pricing)
    """
    alk_capex  = models["electrolyzer-alk-20mw"]["economics"]["capex_per_kw_yuan"]
    pem_capex  = models["electrolyzer-pem-10mw"]["economics"]["capex_per_kw_yuan"]
    aem_capex  = models["electrolyzer-aem-2.4mw"]["economics"]["capex_per_kw_yuan"]
    soec_capex = models["electrolyzer-soec-5mw"]["economics"]["capex_per_kw_yuan"]
    assert alk_capex < pem_capex < aem_capex < soec_capex, (
        f"CAPEX must increase with immaturity: "
        f"ALK={alk_capex} < PEM={pem_capex} < AEM={aem_capex} < SOEC={soec_capex} ¥/kW"
    )


def test_electrolyzer_provenance_public_sourced(models):
    """T12c: All electrolyzer entries carry public provenance (D32 + D35 condition 2).
    AEM + SOEC are NOT in §8.2 — their public-source citations are the only justification
    for the values (D35 condition 2: benchmark-sourced values MUST have explicit public provenance).
    """
    for mid in ELY_IDS:
        prov = models[mid].get("provenance", "")
        assert prov.startswith("public"), (
            f"{mid!r}: provenance must start 'public' (D35 condition 2 — "
            f"AEM/SOEC values not §8.2-sanctioned; public source citation required); got {prov!r}"
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


# ── Reviewer-added cases (backend-reviewer) ──────────────────────────────────
# Gap audited: the per-type tests T7-T10 select models by HARDCODED ID lists, not by
# the `type` field. Consequences: (a) `type` (the schema discriminator) is never
# validated, and (b) a future benchmark entry added to the YAML but omitted from a
# per-type ID list silently escapes ALL physics validation — the same fixture-drift
# class flagged on PR #101. These cases pin `type`, make per-type coverage exhaustive,
# enforce the §1 provenance-format standard, and add an MW/kW unit-slip guard.

VALID_TYPES = {"wind_turbine", "pv_panel", "battery", "grid_connection"}
# electrolyzer is HELD (contract §2/§7) — no electrolyzer entries should ship until
# rl-architect rules on the new device type; excluded from the valid set on purpose.


# reviewer: backend-reviewer (type discriminator is untested by T7-T10)
def test_every_model_has_valid_type(models):
    """Every model must declare a `type` in the valid enum. electrolyzer must NOT
    appear yet (held). Hand-check: 13 entries, all in
    {wind_turbine, pv_panel, battery, grid_connection}."""
    for mid, e in models.items():
        assert "type" in e, f"{mid!r} missing 'type' field"
        assert e["type"] in VALID_TYPES, (
            f"{mid!r} type={e.get('type')!r} not in {sorted(VALID_TYPES)} "
            "(electrolyzer is HELD pending rl-architect; no electrolyzer entry should ship)"
        )


# reviewer: backend-reviewer (close the per-type coverage drift gap)
def test_per_type_coverage_exhaustive(models):
    """The per-type ID lists must EXHAUSTIVELY cover every model in the YAML, so no
    entry escapes T7-T10 physics validation. Fails if a future entry is added to the
    YAML (or EXPECTED_IDS) without being added to the matching per-type list.
    Hand-check: WIND(4)+PV(3)+BAT(3)+GRID(3) = 13 = len(models)."""
    covered = set(WIND_IDS) | set(PV_IDS) | set(BAT_IDS) | set(GRID_IDS)
    all_ids = set(models.keys())
    uncovered = all_ids - covered
    assert not uncovered, (
        f"models present in YAML but covered by NO per-type physics test: {sorted(uncovered)}. "
        "Add each to the matching WIND_IDS/PV_IDS/BAT_IDS/GRID_IDS list — otherwise it ships "
        "physics-unvalidated (the PR #101 fixture-drift class)."
    )
    dangling = covered - all_ids
    assert not dangling, f"per-type ID lists reference absent models: {sorted(dangling)}"


# reviewer: backend-reviewer (§1 provenance format, not just non-empty per T4)
def test_provenance_access_keyword(models):
    """§1: provenance MUST start with a valid access keyword. Hand-check: all public
    entries start 'public; …'; the SST stub is exactly 'USER-provided, pending'."""
    for mid, e in models.items():
        prov = e.get("provenance", "")
        assert prov.startswith("public") or prov == "USER-provided, pending", (
            f"{mid!r} provenance must start with access keyword 'public' or be exactly "
            f"'USER-provided, pending' (contract §1); got {prov!r}"
        )


# reviewer: backend-reviewer (MW/kW unit-slip guard; §6 silent-unit-mismatch class)
def test_wind_rated_mw_unit_sanity(models):
    """A single onshore turbine's rated power is O(1-15) MW; a kW value (e.g. 6000)
    would pass T7c (>0) silently. Guard 0 < rated_mw_per_unit < 50.
    Hand-check: vestas 4.2, goldwind 6.0, envision 3.6, windey 3.0 — all in (0,50)."""
    for mid in WIND_IDS:
        r = models[mid]["physics"]["rated_mw_per_unit"]
        assert 0 < r < 50, (
            f"{mid}: rated_mw_per_unit={r} outside plausible single-turbine MW range (0,50) — "
            "likely a kW/MW unit error"
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
