import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { registryBuildPlugin } from "./src/config/registryBuildPlugin";

export default defineConfig({
  // registryBuildPlugin: auto-copies assets/3d/registry.json → src/config/registryData.json
  // at configResolved time so the import in gansuSiteConfig.ts resolves during vitest run.
  // Contract: contracts/frontend/registry_build_copy.md §1
  plugins: [react(), registryBuildPlugin],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.tsx", "tests/**/*.test.ts"],
  },
});
