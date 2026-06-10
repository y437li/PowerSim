/**
 * 3D scene type definitions.
 * Contract: contracts/frontend3d/site_scene.md §1, §2
 *
 * AssetRegistry shape conforms to the LOCKED assets/3d/registry.json v1.0.0
 * (PR #24, rl-architect authority). Map key = asset ID; no redundant id field
 * inside AssetRegistryEntry. resolveAsset(reg, id) = reg.assets[id] ?? null.
 */

// ─── Asset registry ───────────────────────────────────────────────────────────

export type AssetType =
  | "turbine"
  | "pv_array"
  | "battery"
  | "grid_pcc"
  | "grid_connection"
  | "site_element"
  | "effect";

/** 3D vector used for dimensions and pivot offsets (metres). */
export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/** Animation hooks: Three.js node names within the GLB for driven animations. */
export interface AnimationHooks {
  /** Rotor mesh node name — spun at omega ∝ wind speed. */
  rotor_node?: string;
  /** SOC fill mesh — scale.y reflects calcSocFill result. */
  soc_fill_mesh?: string;
  /** PV surface material name — emissiveIntensity reflects calcEmissive result. */
  irradiance_material?: string;
}

/**
 * Single entry in the asset registry.
 * LOCKED v1.0.0: no `id` field — the map key in AssetRegistry.assets IS the id.
 * Consumers that need the id string receive it as the resolveAsset() argument.
 */
export interface AssetRegistryEntry {
  /** Path relative to assets/3d/ root. */
  path: string;
  type: AssetType;
  /** Real-world bounding box in metres [width(x), height(y), depth(z)]. */
  dims_m: Vec3;
  /** Pivot/anchor offset from geometry origin in metres. */
  pivot: Vec3;
  animation_hooks?: AnimationHooks;
}

/**
 * The full registry object — shape of assets/3d/registry.json LOCKED v1.0.0.
 * Keyed by asset ID (verbatim config YAML key). resolveAsset = reg.assets[id] ?? null.
 */
export interface AssetRegistry {
  schema_version: string;
  assets: Record<string, AssetRegistryEntry>;
}

// ─── Site scene configuration ─────────────────────────────────────────────────

export type Position3 = [number, number, number]; // [x, y, z] metres
export type Rotation3 = [number, number, number]; // [rx, ry, rz] radians

export interface TurbineInstance {
  id: string;
  assetId: string;
  position_m: Position3;
  rotation_rad: Rotation3;
  capacity_mw: number;
}

export interface PvArrayInstance {
  id: string;
  assetId: string;
  position_m: Position3;
  rotation_rad: Rotation3;
  capacity_mw: number;
}

export interface BatteryInstance {
  id: string;
  assetId: string;
  position_m: Position3;
  rotation_rad: Rotation3;
  capacity_mwh: number;
  max_charge_mw: number;
  max_discharge_mw: number;
}

export interface GridConfig {
  pcc: { assetId: string; position_m: Position3 };
  substation?: { assetId: string; position_m: Position3 };
  pylons: { assetId: string; position_m: Position3 }[];
}

export interface TerrainConfig {
  assetId: string;
}

/**
 * Complete scene configuration derived from a site YAML.
 * Passed as a prop to SiteScene; never read from the store directly.
 */
export interface SiteSceneConfig {
  site_id: string;
  /** Nameplate wind capacity (MW) — used as part of site_max_mw denominator. */
  wind_capacity_mw: number;
  /** Nameplate solar capacity (MW). */
  solar_capacity_mw: number;
  turbines: TurbineInstance[];
  pv_arrays: PvArrayInstance[];
  battery: BatteryInstance;
  grid: GridConfig;
  terrain: TerrainConfig;
}
