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

import { copyFileSync, mkdirSync } from "fs";
import { dirname } from "path";

const SRC = "assets/3d/registry.json";
const DEST = "src/config/registryData.json";

mkdirSync(dirname(DEST), { recursive: true });
copyFileSync(SRC, DEST);
console.log("registry copied: assets/3d/registry.json → src/config/registryData.json");
