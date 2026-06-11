import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VITE_PROXY_CONFIG } from "./src/config/viteProxy";
import { registryBuildPlugin } from "./src/config/registryBuildPlugin";

export default defineConfig({
  // registryBuildPlugin: auto-copies assets/3d/registry.json → src/config/registryData.json
  // at configResolved time, before any transform runs.
  // Contract: contracts/frontend/registry_build_copy.md §1
  plugins: [react(), registryBuildPlugin],
  server: {
    // Dev server port: ENERGY_GO_FRONTEND_PORT env var (default 5173).
    // Contract: contracts/frontend/configurable_ports.md §3
    port: parseInt(process.env.ENERGY_GO_FRONTEND_PORT ?? "5173", 10),
    // Dev proxy: /api → REST backend (strips /api prefix), /ws → WS backend.
    // Backend port is read from ENERGY_GO_BACKEND_PORT at startup (default 8000).
    // Contract: contracts/frontend/app_integration.md §1, configurable_ports.md §2
    proxy: VITE_PROXY_CONFIG,
  },
  // NOTE: no test: block here — Vitest uses vitest.config.ts exclusively.
  // Contract: contracts/frontend/registry_build_copy.md §Solution
});
