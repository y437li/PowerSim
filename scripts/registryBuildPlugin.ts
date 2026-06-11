/**
 * registryBuildPlugin — Vite plugin that auto-copies assets/3d/registry.json
 * → src/config/registryData.json before any transform runs.
 *
 * Fires at configResolved time (before any import resolution), so the copy is
 * always fresh for `vite dev`, `vite build`, and `vitest run` (both configs
 * register this plugin — see vite.config.ts and vitest.config.ts).
 *
 * This file lives in scripts/ (NOT src/) so that the browser-targeted tsconfig
 * (which has no @types/node) never typechecks it. Vite and Vitest load it via
 * their own esbuild transpiler, which handles Node built-in imports correctly.
 *
 * Contract: contracts/frontend/registry_build_copy.md §1
 */

import { copyFileSync, mkdirSync, existsSync } from "fs";
import { dirname } from "path";

const SRC = "assets/3d/registry.json";
const DEST = "src/config/registryData.json";

/**
 * Core conditional copy logic — extracted for testability.
 *
 * Three branches (partial-checkout safe):
 *  1. source exists              → copy (fresh, overwrite committed fallback) → "copied"
 *  2. source absent + dest exists → no-op (use committed fallback)            → "skipped"
 *  3. neither exists             → throw (Vite cannot resolve the import)
 *
 * @param src  Path to the canonical source (default: assets/3d/registry.json)
 * @param dest Path to the generated destination (default: src/config/registryData.json)
 */
export function copyRegistryIfNeeded(
  src: string = SRC,
  dest: string = DEST,
): "copied" | "skipped" {
  if (existsSync(src)) {
    mkdirSync(dirname(dest), { recursive: true });
    copyFileSync(src, dest);
    return "copied";
  } else if (existsSync(dest)) {
    return "skipped";
  } else {
    throw new Error(
      `[copy-registry] neither ${src} nor ${dest} exists — cannot proceed`
    );
  }
}

export const registryBuildPlugin = {
  name: "copy-registry",
  configResolved() {
    copyRegistryIfNeeded();
  },
};
