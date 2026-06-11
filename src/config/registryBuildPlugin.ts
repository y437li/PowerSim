/**
 * registryBuildPlugin — Vite plugin that auto-copies assets/3d/registry.json
 * → src/config/registryData.json before any transform runs.
 *
 * Fires at configResolved time (before any import resolution), so the copy is
 * always fresh for `vite dev`, `vite build`, and `vitest run` (both configs
 * register this plugin — see vite.config.ts and vitest.config.ts).
 *
 * Contract: contracts/frontend/registry_build_copy.md §1
 */

import { copyFileSync, mkdirSync, existsSync } from "fs";
import { dirname } from "path";

const SRC = "assets/3d/registry.json";
const DEST = "src/config/registryData.json";

export const registryBuildPlugin = {
  name: "copy-registry",
  configResolved() {
    // Partial-checkout behaviour (e.g. serving fixture, CI sandbox without assets/):
    //   - Source exists     → copy (fresh, overwrite committed fallback)
    //   - Source absent + dest exists → proceed silently (committed copy is the fallback)
    //   - Neither exists    → hard-fail (Vite cannot resolve the import)
    if (existsSync(SRC)) {
      mkdirSync(dirname(DEST), { recursive: true });
      copyFileSync(SRC, DEST);
    } else if (!existsSync(DEST)) {
      throw new Error(
        `[copy-registry] neither ${SRC} nor ${DEST} exists — cannot proceed`
      );
    }
    // else: source absent but dest exists → use committed fallback, no-op
  },
};
