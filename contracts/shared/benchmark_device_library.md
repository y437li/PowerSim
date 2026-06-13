# Benchmark Device Library — shared contract

**Area:** shared  
**Contract path:** `contracts/shared/benchmark_device_library.md`  
**Schema file:** `config/device_models.yaml` (additive entries; schema_version "2.0.0" → "2.1.0")  
**Test file:** `tests/shared/test_shared_benchmark_device_library.py`  
**Spec sections:** §8.2 (electrolyzer asset model), §8.3 (composable assets), D32(h) (fleet sizing; CAPEX = units × unit-price)  
**Decisions:** D2 (§8 composable assets), D23 (asset IDs = registry keys), D31 (B foundational, D keystone), D32 (product spine)  
**Plan:** `docs/design/master_plan_geo_finance.md` §5.6 (CAPEX/OPEX/lifetime benchmarks, Workstream D)  
**Owner:** finance-engineer  
**Version:** v1.0.0  
**Acceptance gate:** finance-expert review  
**Related contracts:**  
- `contracts/shared/device_model_schema.md` v2.0.0 (LOCKED — this PR adds entries; minor version bump; no re-LOCK)  
- `contracts/shared/config_validation.md` v1.0.0 (LOCKED — electrolyzer rules are gated pending electrolyzer env contract)  
- `assets/3d/registry.json` v1.0.0 (LOCKED — IDs must match `^[a-z0-9][a-z0-9.-]*$`; new benchmark IDs do NOT have registry entries yet; 3d-assets-engineer adds them when GLB models land)

---

## Overview

This contract extends `config/device_models.yaml` with a **multi-brand China benchmark device
library** covering:

- **Wind turbines** — 3 models spanning the 3.0–6.0 MW onshore class (Goldwind, Envision, Windey)  
- **PV panels** — 2 models, n-type TOPCon technology (LONGi, JA Solar)  
- **BESS** — 2 models, LFP grid-scale (BYD, Sungrow)  
- **Grid connections** — 1 public benchmark (generic 220kV AC) + 1 SST stub (PAUSED)  
- **Electrolyzers** — 4 models covering ALK / PEM / AEM / SOEC (new device type; §8.2)

**Public-repo rule (CLAUDE.md, D32):** All committed values use public sources only.
A `provenance:` field is added to every model entry (including the 4 existing Gansu entries
at their next write), citing the data source. The SST stub carries
`provenance: "USER-provided, pending"` — no proprietary values committed.

**Versioning:** Adding new model entries and a new device type is an additive (minor) change.
`config/device_models.yaml` schema_version bumps from `"2.0.0"` to `"2.1.0"`. No re-LOCK
of `device_model_schema.md` is required; the physics field contract for the Gansu 4 entries
is unchanged. The existing 4 Gansu models are NOT modified; their entries are stable.

---

## 1. Provenance standard

Each model entry MUST carry a top-level `provenance:` string field documenting the source(s)
of the values. Format: `"<access>; <source1>; [<source2>; …]"`.

| Access keyword | Meaning |
|---|---|
| `public` | Publicly available data (manufacturer sheets, IRENA, IEA, NEA, CNREC, etc.) |
| `USER-provided, pending` | Data awaiting USER input; all values are placeholder stubs |

Resolver: ignores `provenance:` (treated like `economics:` — consumed by the finance layer only).  
Tests: assert every model entry has a non-empty `provenance:` string.

---

## 2. Electrolyzer device type extension (§8.2)

`device_model_schema.md` v2.0.0 defines types: `wind_turbine`, `pv_panel`, `battery`,
`grid_connection`. This contract adds type `electrolyzer` — an additive extension matching the
§8.2 hydrogen electrolyzer asset model.

### 2.1 Physics field catalogue — `electrolyzer`

All fields listed are **required** for type `electrolyzer`. All are **non-overridable** by a
site (intrinsic device physics, parallel to `eta_ch`/`eta_dis`/`soc_min`/`soc_max` for battery).

| Field | Type | Unit | Description |
|---|---|---|---|
| `min_load_fraction` | float | — | Minimum operating load as fraction of P_max; ∈ (0, 1] |
| `standby_fraction` | float | — | Standby power draw as fraction of P_max; ∈ [0, 1) |
| `e_spec_kwh_per_kg` | float | kWh/kg | System-level specific energy (kWh per kg H₂ produced) |
| `degradation_yuan_per_mwh` | float | ¥/MWh | Degradation cost per MWh of electrical throughput (§8.2 reference) |
| `rated_mw_per_unit` | float | MW | Nameplate electrical power per unit (P_max_ely; §8.2 reference 20 MW) |
| `warmup_minutes` | float | min | Cold-start warm-up duration (informational; env currently ignores at Δt=1 h; §8.2 note) |

**Physics invariants (tested):**
- `0 < min_load_fraction ≤ 1.0`
- `0 ≤ standby_fraction < min_load_fraction` (standby < minimum operating, always)
- `e_spec_kwh_per_kg > 0`
- `degradation_yuan_per_mwh ≥ 0`
- `rated_mw_per_unit > 0`
- `warmup_minutes ≥ 0`

**Derived quantity (informational, not stored):**
`rated_production_kg_per_mw_h = 1000.0 / e_spec_kwh_per_kg`  
(at full power: 1 MW × 1 h = 1 MWh → 1000/e_spec kg H₂)

### 2.2 Economics field catalogue — `electrolyzer`

Additional economics fields beyond the base catalogue in `device_model_schema.md` §1.3:

| Field | Type | Unit | Description |
|---|---|---|---|
| `capex_per_kw_yuan` | float | ¥/kW | Overnight CAPEX per kW of rated electrical power |
| `opex_fixed_per_kw_year_yuan` | float | ¥/kW·yr | Fixed O&M per rated kW per year |
| `opex_var_per_mwh_yuan` | float | ¥/MWh | Variable O&M per MWh electrical throughput |
| `stack_life_years` | float | yr | Stack operating life before replacement |
| `replacement_cost_fraction` | float | — | Stack replacement cost / original CAPEX; ∈ (0, 1] |
| `lifetime_years` | float | yr | System design lifetime |
| `residual_value_fraction` | float | — | Salvage / original CAPEX at EOL; ∈ [0, 1) |
| `construction_months` | float | months | Procurement + installation duration |

---

## 3. Model entries catalogue

### 3.1 Wind turbines

| Model ID | Type | Rated MW | v_cutin | v_rated | v_cutout | Hub height | Source |
|---|---|---|---|---|---|---|---|
| `goldwind-gw165-6.0` | wind_turbine | 6.0 | 3.0 | 10.5 | 22.0 | 120 m | Goldwind 2024 product datasheet; CNREC 2024; IRENA 2023 |
| `envision-en136-3.6` | wind_turbine | 3.6 | 3.0 | 11.0 | 20.0 | 90 m | Envision Energy 2024 product brochure; IRENA 2023 |
| `windey-wd156-3.0` | wind_turbine | 3.0 | 3.0 | 11.5 | 20.0 | 80 m | Windey (Sichuan Tianyi) public specs; IRENA 2023 |

### 3.2 PV panels

| Model ID | Type | k_T_per_c | eta_inv | deg_yr1 | Source |
|---|---|---|---|---|---|
| `longi-hi-mo-x6-610w` | pv_panel | −0.0029 | 0.985 | 0.98 | LONGi LR5-72HIH-610M datasheet (public); IRENA 2023 China utility PV |
| `jasolar-deepblue4-615w` | pv_panel | −0.0028 | 0.985 | 0.98 | JA Solar JAM72D42-615/MB datasheet (public); IRENA 2023 |

### 3.3 BESS

| Model ID | Type | eta_ch | eta_dis | soc_min | soc_max | cap_mwh/unit | pwr_mw/unit | Source |
|---|---|---|---|---|---|---|---|---|
| `byd-mc-cube-lfp` | battery | 0.965 | 0.965 | 0.10 | 0.90 | 2.0 | 1.0 | BYD MC Cube product data (public); CNESA 2024 energy storage market report |
| `sungrow-lfp-lc` | battery | 0.970 | 0.970 | 0.05 | 0.95 | 5.0 | 2.5 | Sungrow ST2752UX PowerTitan datasheet (public) |

### 3.4 Grid connections

| Model ID | Type | max_export_mw | max_import_mw | Source |
|---|---|---|---|---|
| `pcc-traditional-220kv` | grid_connection | 200.0 | 200.0 | NEA China grid construction cost guidelines (public); industry benchmark |
| `pcc-sst-stub` | grid_connection | 200.0 | 200.0 | USER-provided, pending (SST — PAUSED; stub only) |

### 3.5 Electrolyzers

| Model ID | Tech | min_load | standby | e_spec | degrad | rated_mw | warmup | Source |
|---|---|---|---|---|---|---|---|---|
| `electrolyzer-alk-20mw` | ALK | 0.20 | 0.02 | 52.0 | 4.0 | 20.0 | 30 min | PERIC HG-Alk public; IRENA Green H₂ 2020; IEA Hydrogen 2023 |
| `electrolyzer-pem-10mw` | PEM | 0.05 | 0.01 | 55.0 | 8.0 | 10.0 | 5 min | Siemens Silyzer 300 public; Nel H₂ public; IEA 2023 |
| `electrolyzer-aem-1mw` | AEM | 0.05 | 0.01 | 53.0 | 10.0 | 2.4 | 5 min | Enapter EL 4.0 public datasheet; IEA 2023 projections |
| `electrolyzer-soec-5mw` | SOEC | 0.20 | 0.05 | 40.0 | 15.0 | 5.0 | 240 min | Sunfire Refuel public; Bloom Energy public; IEA 2023 |

**Technology comparison notes (public domain):**
- ALK: lowest CAPEX, best maturity; limited turndown; dominated by Chinese manufacturers (PERIC, Longi H₂, Suzhou Jingli)
- PEM: fastest response, best turndown (5% P_max); higher CAPEX; stack replacement ~5 yr
- AEM: emerging technology; combines PEM turndown with ALK-like materials; limited commercial scale as of 2024
- SOEC: highest system efficiency (uses heat input); highest CAPEX; long cold-start; best for baseload H₂

---

## 4. Economics values

### 4.1 Wind turbine economics (public China 2024/25 benchmarks)

#### goldwind-gw165-6.0

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 4800.0 | ≈670 USD/kW; 6 MW class economy of scale; IRENA 2023 China onshore |
| `opex_fixed_per_kw_year_yuan` | 150.0 | ≈21 USD/kW·yr; CNREC 2024 O&M benchmark |
| `opex_var_per_mwh_yuan` | 0.0 | Captured in fixed O&M for this scale |
| `lifetime_years` | 25.0 | IEC Class II/III design life |
| `replacement_cost_fraction` | 0.12 | Major overhaul at EOL (blades, gearbox); lower than smaller turbines |
| `residual_value_fraction` | 0.05 | Scrap steel value |
| `construction_months` | 18.0 | Procurement + civil + commissioning |
| `decommissioning_cost_per_kw_yuan` | 90.0 | Slightly lower per-kW than 4.2 MW (better logistics per MW) |

#### envision-en136-3.6

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 5200.0 | ≈725 USD/kW; mid-tier 3.6 MW class; IRENA 2023 |
| `opex_fixed_per_kw_year_yuan` | 170.0 | ≈24 USD/kW·yr |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 25.0 | |
| `replacement_cost_fraction` | 0.15 | |
| `residual_value_fraction` | 0.05 | |
| `construction_months` | 15.0 | Smaller unit = faster installation |
| `decommissioning_cost_per_kw_yuan` | 95.0 | |

#### windey-wd156-3.0

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 5400.0 | ≈755 USD/kW; budget-tier 3 MW; IRENA 2023 lower bound |
| `opex_fixed_per_kw_year_yuan` | 160.0 | ≈22 USD/kW·yr |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 20.0 | Shorter design life for economy-class turbines |
| `replacement_cost_fraction` | 0.15 | |
| `residual_value_fraction` | 0.03 | |
| `construction_months` | 12.0 | |
| `decommissioning_cost_per_kw_yuan` | 80.0 | |

### 4.2 PV panel economics

#### longi-hi-mo-x6-610w

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 3000.0 | ≈420 USD/kW; LONGi drives market floor; IRENA 2023 China utility PV |
| `opex_fixed_per_kw_year_yuan` | 75.0 | ≈10.5 USD/kW·yr |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 30.0 | Module life (n-type TOPCon rated 30 yr at ≥80% output) |
| `replacement_cost_fraction` | 0.10 | Inverter mid-life replacement ~year 15 |
| `residual_value_fraction` | 0.02 | |
| `construction_months` | 9.0 | |
| `decommissioning_cost_per_kw_yuan` | 50.0 | |

#### jasolar-deepblue4-615w

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 3100.0 | ≈433 USD/kW; slightly above LONGi; IRENA 2023 |
| `opex_fixed_per_kw_year_yuan` | 78.0 | ≈11 USD/kW·yr |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 30.0 | |
| `replacement_cost_fraction` | 0.10 | |
| `residual_value_fraction` | 0.02 | |
| `construction_months` | 9.0 | |
| `decommissioning_cost_per_kw_yuan` | 52.0 | |

### 4.3 BESS economics

#### byd-mc-cube-lfp

| Field | Value | Notes |
|---|---|---|
| `capex_energy_per_kwh_yuan` | 950.0 | ≈133 USD/kWh; BYD market pricing 2024; CNESA 2024 LFP benchmark |
| `capex_power_per_kw_yuan` | 0.0 | Bundled into energy CAPEX |
| `opex_fixed_per_kwh_year_yuan` | 18.0 | ≈2.5 USD/kWh·yr |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 15.0 | BYD warranty: 15 yr at ≥70% SOH |
| `cycle_life_full_equiv` | 8000.0 | BYD LFP blade battery public spec |
| `eol_soh_threshold` | 0.80 | 80% remaining capacity triggers replacement |
| `replacement_cost_fraction` | 0.65 | Cell+BMS module replacement |
| `residual_value_fraction` | 0.05 | |
| `construction_months` | 6.0 | |
| `decommissioning_cost_per_kwh_yuan` | 25.0 | |

#### sungrow-lfp-lc

| Field | Value | Notes |
|---|---|---|
| `capex_energy_per_kwh_yuan` | 920.0 | ≈129 USD/kWh; Sungrow PowerTitan pricing 2024 |
| `capex_power_per_kw_yuan` | 0.0 | Bundled |
| `opex_fixed_per_kwh_year_yuan` | 17.0 | ≈2.4 USD/kWh·yr; liquid cooling reduces cooling O&M |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `lifetime_years` | 15.0 | Sungrow warranty 15 yr |
| `cycle_life_full_equiv` | 8000.0 | Sungrow public spec; liquid cooling enables higher cycle count |
| `eol_soh_threshold` | 0.80 | |
| `replacement_cost_fraction` | 0.60 | |
| `residual_value_fraction` | 0.05 | |
| `construction_months` | 6.0 | |
| `decommissioning_cost_per_kwh_yuan` | 22.0 | |

### 4.4 Grid connection economics

#### pcc-traditional-220kv

| Field | Value | Notes |
|---|---|---|
| `capex_lump_sum_yuan` | 15000000.0 | ¥15M ≈ $2.1M; standard 220kV substation China; NEA cost guidelines |
| `opex_fixed_per_mw_year_yuan` | 5000.0 | ≈700 USD/MW·yr; transmission service fee benchmark |
| `lifetime_years` | 40.0 | |
| `residual_value_fraction` | 0.10 | |
| `decommissioning_cost_yuan` | 500000.0 | |

#### pcc-sst-stub (STUB)

All economics values are placeholder zeros. Proprietary SST data awaited from USER.
`provenance: "USER-provided, pending"`.

### 4.5 Electrolyzer economics

#### electrolyzer-alk-20mw

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 3500.0 | ≈490 USD/kW; China domestic ALK 2024 ¥2500-4000/kW; IRENA 2023 mid-case |
| `opex_fixed_per_kw_year_yuan` | 90.0 | ~2.5% of CAPEX; IEA benchmark |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `stack_life_years` | 8.0 | ALK stack: 80,000-100,000 hrs ≈ 10yr continuous; IEA 2023 |
| `replacement_cost_fraction` | 0.30 | Stack replacement ~30% CAPEX; IEA/IRENA estimate |
| `lifetime_years` | 20.0 | System design life; IEA 2023 |
| `residual_value_fraction` | 0.05 | |
| `construction_months` | 12.0 | |

#### electrolyzer-pem-10mw

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 6500.0 | ≈910 USD/kW; China domestic PEM 2024 ¥5000-8000/kW; IRENA 2023 |
| `opex_fixed_per_kw_year_yuan` | 130.0 | ~2% of CAPEX; IEA benchmark |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `stack_life_years` | 5.0 | PEM membrane: 60,000-80,000 hrs; IEA 2023 |
| `replacement_cost_fraction` | 0.40 | PEM membrane/catalyst stack ~40% CAPEX; higher than ALK |
| `lifetime_years` | 15.0 | System life (with stack replacements); IEA 2023 |
| `residual_value_fraction` | 0.05 | |
| `construction_months` | 9.0 | |

#### electrolyzer-aem-1mw

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 8500.0 | ≈1190 USD/kW; Enapter EL 4.0 commercial pricing 2024 (public) |
| `opex_fixed_per_kw_year_yuan` | 200.0 | Higher O&M for emerging technology |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `stack_life_years` | 3.0 | AEM membrane: ~30,000-40,000 hrs; Enapter public; IEA 2023 |
| `replacement_cost_fraction` | 0.50 | |
| `lifetime_years` | 10.0 | Shorter system life due to membrane degradation rate |
| `residual_value_fraction` | 0.03 | |
| `construction_months` | 6.0 | |

#### electrolyzer-soec-5mw

| Field | Value | Notes |
|---|---|---|
| `capex_per_kw_yuan` | 14000.0 | ≈1960 USD/kW; SOEC premium 2024; Sunfire public; IEA 2023 high-temperature materials |
| `opex_fixed_per_kw_year_yuan` | 350.0 | ~2.5% of CAPEX; complex thermal management |
| `opex_var_per_mwh_yuan` | 0.0 | |
| `stack_life_years` | 2.0 | SOEC cells: 15,000-20,000 hrs; frequent replacement; IEA 2023 |
| `replacement_cost_fraction` | 0.60 | Ceramic stack: most expensive; IEA/Sunfire |
| `lifetime_years` | 10.0 | System design life |
| `residual_value_fraction` | 0.03 | |
| `construction_months` | 18.0 | Complex heat integration; longest construction |

---

## 5. Test cases

Tests live in `tests/shared/test_shared_benchmark_device_library.py`.
The test file loads `config/device_models.yaml` via `yaml.safe_load`.

### T1 — Schema version
`device_models.yaml` carries `schema_version: "2.1.0"` after the benchmark entries land.

### T2 — All expected IDs present
The following model IDs MUST be present in `models:`:
```python
EXPECTED_IDS = [
    # Existing Gansu (untouched physics)
    "vestas-v150-4.2", "trina-vertex-n-670w", "catl-lmp-300mwh", "pcc-substation-945mw",
    # Wind benchmark
    "goldwind-gw165-6.0", "envision-en136-3.6", "windey-wd156-3.0",
    # PV benchmark
    "longi-hi-mo-x6-610w", "jasolar-deepblue4-615w",
    # BESS benchmark
    "byd-mc-cube-lfp", "sungrow-lfp-lc",
    # Grid benchmark
    "pcc-traditional-220kv", "pcc-sst-stub",
    # Electrolyzer benchmark
    "electrolyzer-alk-20mw", "electrolyzer-pem-10mw",
    "electrolyzer-aem-1mw", "electrolyzer-soec-5mw",
]
```

### T3 — ID format
Every model ID matches `^[a-z0-9][a-z0-9.-]*$` (binding cross-area invariant D23).

### T4 — All models have a provenance field
Every entry in `models:` has a non-empty string `provenance:` field.

### T5 — SST stub provenance
`models["pcc-sst-stub"]["provenance"]` equals exactly `"USER-provided, pending"`.

### T6 — Existing Gansu entries untouched
For each of the 4 Gansu entries, check specific physics values still match the locked values
(e.g. `vestas-v150-4.2.physics.v_rated_mps == 12.0`, `catl-lmp-300mwh.physics.eta_ch == 0.97`).

### T7 — Wind turbine required physics fields
For each `type == wind_turbine`, assert these physics keys exist and types are correct:
`v_cutin_mps`, `v_rated_mps`, `v_cutout_mps`, `hub_height_m`, `rated_mw_per_unit`.
Invariants: `0 < v_cutin_mps < v_rated_mps < v_cutout_mps`; `rated_mw_per_unit > 0`.

### T8 — PV panel required physics fields
For each `type == pv_panel`: `k_T_per_c`, `eta_inverter`, `degradation_yr1`.
Invariants: `k_T_per_c < 0` (negative); `0 < eta_inverter <= 1`; `0 < degradation_yr1 <= 1`.

### T9 — Battery required physics fields
For each `type == battery`: `eta_ch`, `eta_dis`, `soc_min`, `soc_max`,
`capacity_mwh_per_unit`, `power_mw_per_unit`.
Invariants: `0 < eta_ch <= 1`; `0 < eta_dis <= 1`; `0 <= soc_min < soc_max <= 1`;
`capacity_mwh_per_unit > 0`; `power_mw_per_unit > 0`.

### T10 — Grid connection required physics fields
For each `type == grid_connection`: `max_export_mw`, `max_import_mw`.
Invariants: `max_export_mw >= 0`; `max_import_mw >= 0`.

### T11 — Electrolyzer required physics fields
For each `type == electrolyzer`: `min_load_fraction`, `standby_fraction`,
`e_spec_kwh_per_kg`, `degradation_yuan_per_mwh`, `rated_mw_per_unit`, `warmup_minutes`.
Invariants (§2.1 above):
- `0 < min_load_fraction <= 1`
- `0 <= standby_fraction < min_load_fraction`
- `e_spec_kwh_per_kg > 0`
- `degradation_yuan_per_mwh >= 0`
- `rated_mw_per_unit > 0`
- `warmup_minutes >= 0`

### T12 — Electrolyzer technology comparison monotonics
**Hand-computed invariants (tested with arithmetic shown in comments):**
- ALK specific energy < PEM specific energy (`52.0 < 55.0` ✓ — ALK system losses slightly lower but IEA data shows PEM currently higher)
- SOEC specific energy < ALK (`40.0 < 52.0` ✓ — SOEC uses heat input; net electrical e_spec lower)
- ALK degradation < PEM < AEM < SOEC (`4.0 < 8.0 < 10.0 < 15.0` ✓ — increasing immaturity)
- ALK CAPEX < PEM CAPEX < AEM CAPEX < SOEC CAPEX (public 2024 pricing order confirmed)
- ALK min_load > PEM min_load (ALK: 0.20 > PEM: 0.05 ✓ — alkaline limited turndown is defining characteristic)

### T13 — Non-negative economics values
For every entry with an `economics:` dict, all numeric values MUST be ≥ 0.0.
Fractions (`replacement_cost_fraction`, `residual_value_fraction`, `eol_soh_threshold`)
MUST be in [0, 1].

### T14 — SST stub physics are placeholder (informational)
`pcc-sst-stub.physics.max_export_mw` and `.max_import_mw` exist and are float.
SST `economics` dict is empty or absent (no stub proprietary values).

### T15 — Gansu existing entries have provenance added  # reviewer:
The 4 original Gansu entries MUST also have a `provenance:` field after this PR
(documenting their original source as "public; device_model_schema.md v2.0.0 §6 initial estimates; IRENA/NEA 2024 Chinese utility-scale benchmarks").

---

## 6. Deliberate deviations

| Item | Deviation | Rationale |
|---|---|---|
| `electrolyzer` device type | New type not in `device_model_schema.md` v2.0.0 type enum | §8.2 explicitly defines the electrolyzer model; this is an additive extension to the shared file; resolver ignores unknown types gracefully |
| `warmup_minutes` physics field | Not in §8.2 formal parameter table (mentioned in §8.2 prose) | Documents a real physical constraint; resolver and env ignore it at Δt=1h; flagged as informational in tests |
| `pcc-sst-stub` stub with placeholder physics | Export/import values are identical to `pcc-traditional-220kv` defaults | Prevents resolver errors when SST site configs reference the model before USER provides data; clearly tagged as stub |
| Gansu entries gain `provenance:` | Additive field to 4 existing entries | No physics change; provenance documenting is a requirement for all public config (CLAUDE.md public-repo rule) |

---

## 7. Out of scope

- Non-China / non-2024 market benchmarks
- Offshore wind models (significant different cost structure; deferred)
- Flow battery BESS (Narada, VRF) — deferred to a future minor bump
- Hydrogen demand/tank parameters (`tank_kg`, `H2_demand_kg(t)`, `price_h2`) — §8.2 dispatch config, not device physics; belongs in a future `contracts/env/electrolyzer.md`
- The company SST device model — PAUSED by USER directive; stub only
- Registry entries in `assets/3d/registry.json` for the new models — 3d-assets-engineer adds GLB entries when visual models land; the benchmark library is physics/economics data only
- Resolver changes — the resolver does not need to handle `electrolyzer` type at this stage (no site YAML yet uses these models); resolver extension is a future §8 env contract
- Config validation rules for electrolyzer — gated on the `contracts/env/electrolyzer.md` contract (per `config_validation.md` v1.0.0 §8 gating pattern)
