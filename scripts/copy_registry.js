#!/usr/bin/env node
// scripts/copy_registry.js
// Standalone script: copy assets/3d/registry.json → src/config/registryData.json
// Contract: contracts/frontend/registry_build_copy.md §2
//
// Run directly: node scripts/copy_registry.js
// Also wired as prebuild / predev / pretest npm hooks so the copy is always fresh.
//
// ESM syntax required — package.json has "type": "module" so .js files are treated
// as ESM by Node; require() is not available.
//
// Partial-checkout behaviour (e.g. serving fixture, CI sandbox without assets/):
//   - Source exists     → copy (fresh)
//   - Source absent + dest exists → log note, proceed (committed copy is the fallback)
//   - Neither exists    → hard-fail (build cannot proceed)

import { copyFileSync, mkdirSync, existsSync } from "fs";
import { dirname } from "path";

const SRC = "assets/3d/registry.json";
const DEST = "src/config/registryData.json";

if (existsSync(SRC)) {
  mkdirSync(dirname(DEST), { recursive: true });
  copyFileSync(SRC, DEST);
  console.log("registry copied: assets/3d/registry.json → src/config/registryData.json");
} else if (existsSync(DEST)) {
  console.log(
    "registry copy skipped: assets/3d/registry.json absent, " +
    "using committed src/config/registryData.json as fallback"
  );
} else {
  throw new Error(
    "registry copy failed: neither assets/3d/registry.json nor " +
    "src/config/registryData.json exists — cannot proceed"
  );
}
