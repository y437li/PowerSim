/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VITE_PROXY_CONFIG } from "./src/config/viteProxy";
import { registryBuildPlugin } from "./scripts/registryBuildPlugin";

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
  // Vitest configuration (merged from vitest.config.ts — contract: root_config_consolidation §3.1)
  // registryBuildPlugin runs at configResolved so the registry import resolves during vitest runs.
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.tsx", "tests/**/*.test.ts"],
    // Redirect @testing-library/user-event to a thin wrapper that sets
    // delay: null by default.  This prevents the direct API (userEvent.click,
    // .type, .clear, …) from creating fake setTimeout(fn,0) calls that hang
    // indefinitely when vi.useFakeTimers() is active in a test.
    // See: tests/__mocks__/userEvent.ts for rationale.
    alias: {
      "@testing-library/user-event": new URL(
        "./tests/__mocks__/userEvent.ts",
        import.meta.url
      ).pathname,
      "@testing-library/react": new URL(
        "./tests/__mocks__/reactTestingLibrary.ts",
        import.meta.url
      ).pathname,
    },
  },
});
