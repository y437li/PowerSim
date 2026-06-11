/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VITE_PROXY_CONFIG } from "./src/config/viteProxy";

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev proxy: /api → REST backend :8000 (strips /api prefix), /ws → WS backend :8000
    // Contract: contracts/frontend/app_integration.md §1
    proxy: VITE_PROXY_CONFIG,
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./tests/setup.ts"],
  },
});
