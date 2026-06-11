/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VITE_PROXY_CONFIG } from "./src/config/viteProxy";

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev server port: ENERGY_GO_FRONTEND_PORT env var (default 5173).
    // Contract: contracts/frontend/configurable_ports.md §3
    port: parseInt(process.env.ENERGY_GO_FRONTEND_PORT ?? "5173", 10),
    // Dev proxy: /api → REST backend (strips /api prefix), /ws → WS backend.
    // Backend port is read from ENERGY_GO_BACKEND_PORT at startup (default 8000).
    // Contract: contracts/frontend/app_integration.md §1, configurable_ports.md §2
    proxy: VITE_PROXY_CONFIG,
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./tests/setup.ts"],
  },
});
