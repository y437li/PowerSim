/**
 * Asset registry resolution.
 * Contract: contracts/frontend3d/site_scene.md §1
 *
 * Scene code NEVER hardcodes asset paths — use resolveAsset() exclusively.
 * Registry conforms to LOCKED assets/3d/registry.json v1.0.0 (PR #24):
 *   resolveAsset(registry, id) = registry.assets[id] ?? null   — O(1)
 */

import type { AssetRegistry, AssetRegistryEntry } from "./types";

/**
 * Look up a registry entry by its asset ID. O(1) keyed lookup.
 *
 * - Case-sensitive: IDs from site YAML are matched verbatim.
 * - Exact match only: "vestas" does NOT match "vestas-v150-4.2".
 * - Returns null if not found (caller renders placeholder mesh).
 *
 * The returned object is `entry & { id: assetId }` — the map key is injected
 * as `id` for caller convenience. The JSON file stores no inner `id`; this is
 * purely a runtime addition consistent with the LOCKED schema.
 */
export function resolveAsset(
  registry: AssetRegistry,
  assetId: string
): (AssetRegistryEntry & { id: string }) | null {
  const entry = registry.assets[assetId];
  return entry != null ? { id: assetId, ...entry } : null;
}
