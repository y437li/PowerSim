// src/types/stageConfig.ts
// Types for Wizard Stage ① Site Configuration
// Contract: contracts/frontend/stage_config.md §3.1

export type StageOneState =
  | 'FIRST_VISIT'
  | 'IN_PROGRESS'
  | 'VALIDATING'
  | 'COMPLETE'
  | 'STALE';

export type WeatherMode = 'synthetic' | 'historical' | 'bootstrap';

export interface LatLon {
  lat: number;   // decimal degrees N; positive = north
  lon: number;   // decimal degrees E; positive = east
}

/** Per-unit physics stored in DeviceRow after resolution (§4.1, T-FLEET-6).
 *  Populated from GET /api/devices/models/{model_id} — device_model_schema §1.2.
 *  DISPLAY-ONLY per D37: NOT used in body construction (server-side assembly via §5.1).
 *  pv_panel has no per-unit MW field (device_model_schema v2.0); PV sizing uses
 *  DeviceRow.fleetCapacityMw (direct site-capacity input).
 */
export interface DeviceRowPhysics {
  rated_mw_per_unit?:     number;   // MW  — wind_turbine (display: "100 × 4.2 MW = 420 MW")
  capacity_mwh_per_unit?: number;   // MWh — battery (display: "1 × 300 MWh")
  power_mw_per_unit?:     number;   // MW  — battery (display: "1 × 100 MW")
  // grid_connection: limits resolved server-side; not displayed per-unit
  // pv_panel: NO per-unit MW in device_model_schema v2.0; use DeviceRow.fleetCapacityMw
}

export interface DeviceRow {
  id:               string;   // model_id from device_models.yaml
  count?:           number;   // ≥ 1; wind_turbine / battery / grid_connection only (not pv_panel)
  fleetCapacityMw?: number;   // MWp; pv_panel only — direct site-capacity input (D37 §5.1)
  // Read-only fields resolved from GET /api/devices/models/{id}
  type?:    'wind_turbine' | 'pv_panel' | 'battery' | 'grid_connection';
  label?:   string;   // human label from search response
  valid?:   boolean;  // true = id resolved in library; false = not found; undefined = resolving
  physics?: DeviceRowPhysics;  // display-only; wind/battery; absent for pv_panel/grid (D37)
}
// v1 limitation: one device model per category (wind/solar/battery/grid). A second distinct
// model of the same type would lose its model_id when the fleet list is built (the assemble
// endpoint receives one entry per device). DeviceFleetTable prevents adding a second model
// of an already-present type in v1. FLEET_MIXED_MODEL handled server-side (#105).

export interface ValidationIssue {
  rule_id:    string;
  field:      string;
  message:    string;
  constraint: string;
}

export interface ValidationResult {
  errors:   ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface WeatherCoverage {
  historical_available: boolean;
  available_year_count: number;
  year_range:           [number, number] | null;
  bootstrap_available:  boolean;
}

/** Mirrors one entry from GET /api/tariff/regions (geo_site_api §3.2).
 *  Used in useSiteMetaForm.availableTariffs and the tariff dropdown.
 *  (M1 fix: type was referenced but not defined.)
 */
export interface TariffRegion {
  region_id:                      string;
  currency:                       string;
  price_min_yuan_per_mwh:        number;   // ¥/MWh
  price_max_yuan_per_mwh:        number;   // ¥/MWh
  demand_rate_yuan_per_mw_month?: number;  // ¥/MW·month (optional field)
  provenance:                     string;
}

// ── Fleet entry types for POST /api/site/assemble body (§5.1) ──
export type WindEntry    = { model_id: string; count: number };
export type PVEntry      = { model_id: string; fleet_capacity_mw: number };
export type BatteryEntry = { model_id: string; count: number };
export type GridEntry    = { model_id: string };
export type FleetEntry   = WindEntry | PVEntry | BatteryEntry | GridEntry;
