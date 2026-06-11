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

import { copyFileSync, mkdirSync } from "fs";
import { dirname } from "path";

const SRC = "assets/3d/registry.json";
const DEST = "src/config/registryData.json";

export const registryBuildPlugin = {
  name: "copy-registry",
  configResolved() {
    mkdirSync(dirname(DEST), { recursive: true });
    copyFileSync(SRC, DEST);
  },
};
