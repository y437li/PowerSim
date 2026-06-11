/**
 * gansuSiteConfig — static SiteSceneConfig + ASSET_REGISTRY for the Gansu site.
 * Contract: contracts/frontend/app_integration.md §5
 *
 * Nameplates sourced from docs/spec/section_01_overview.md:12 (authoritative):
 *   Wind 615 MW  (400 = import limit D12 — different concept)
 *   Solar 330 MW
 *   Battery 294.5 MWh / 98.16 MW
 *
 * Layout is representative (1 turbine, 1 PV array). The full 146-turbine Gansu
 * layout is a future config concern; wiring correctness does not depend on count.
 *
 * All assetId values are valid keys in ASSET_REGISTRY.assets.
 */

import type { SiteSceneConfig, AssetRegistry } from "../scene/types";
import rawRegistry from "../../assets/3d/registry.json";

// ─── Asset registry ───────────────────────────────────────────────────────────

/**
 * Direct JSON import of the locked assets/3d/registry.json (v1.0.1, PR #24).
 * Typed as AssetRegistry — no changes to registry.json.
 */
export const ASSET_REGISTRY = rawRegistry as unknown as AssetRegistry;

// ─── Site configuration ───────────────────────────────────────────────────────

export const GANSU_SITE_CONFIG: SiteSceneConfig = {
  site_id: "gansu",

  /** §1 authoritative nameplate: Wind 615 MW. NOT the import limit (400 MW = D12). */
  wind_capacity_mw: 615,

  /** §1 authoritative nameplate: Solar 330 MW. */
  solar_capacity_mw: 330,

  turbines: [
    {
      id: "turbine-0",
      assetId: "vestas-v150-4.2",
      position_m: [0, 0, 0],
      rotation_rad: [0, 0, 0],
      capacity_mw: 4.2,
    },
  ],

  pv_arrays: [
    {
      id: "pv-0",
      assetId: "trina-vertex-n-670w",
      position_m: [1000, 0, 0],
      rotation_rad: [0, 0, 0],
      capacity_mw: 330,
    },
  ],

  battery: {
    id: "battery-0",
    assetId: "catl-lmp-300mwh",
    position_m: [0, 0, 1000],
    rotation_rad: [0, 0, 0],
    /** §1 authoritative: 294.5 MWh */
    capacity_mwh: 294.5,
    /** §1 authoritative: 98.16 MW */
    max_charge_mw: 98.16,
    /** §1 authoritative: 98.16 MW */
    max_discharge_mw: 98.16,
  },

  grid: {
    pcc: {
      assetId: "pcc-substation-945mw",
      position_m: [0, 0, -1000],
    },
    pylons: [],
  },

  terrain: {
    // No dedicated terrain asset in registry v1.0.1; using pcc-substation as placeholder.
    // A terrain-gansu.glb will be added in a future assets PR.
    assetId: "pcc-substation-945mw",
  },
};
