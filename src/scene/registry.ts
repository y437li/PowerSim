/**
 * Asset registry resolution.
 * Contract: contracts/frontend3d/site_scene.md §1
 *
 * Scene code NEVER hardcodes asset paths — use resolveAsset() exclusively.
 * The registry.json shared contract is pending rl-architect LOCK; until locked,
 * the registry is passed as a prop from the site config loader.
 */

import type { AssetRegistry, AssetRegistryEntry } from "./types";

/**
 * Look up a registry entry by its asset ID.
 *
 * - Case-sensitive: IDs from site YAML are matched verbatim.
 * - Exact match only: "vestas" does NOT match "vestas-v150-4.2".
 * - Returns null if not found (caller renders placeholder mesh).
 */
export function resolveAsset(
  registry: AssetRegistry,
  assetId: string
): AssetRegistryEntry | null {
  for (const entry of registry.entries) {
    if (entry.id === assetId) {
      return entry;
    }
  }
  return null;
}
