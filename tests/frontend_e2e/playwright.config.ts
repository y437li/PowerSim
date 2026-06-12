// tests/frontend_e2e/playwright.config.ts — co-located with the tests it configures
// Contract: contracts/frontend/playwright_harness.md §1
//           contracts/frontend/configurable_ports.md §4 (frontend port env var)
//           contracts/frontend/root_config_consolidation.md §3.4
import { defineConfig, devices } from '@playwright/test';
import path from 'path';

// ENERGY_GO_FRONTEND_PORT: port Vite dev server binds to (default 5173).
// When unset the value is identical to the previous hardcoded constant.
// Contract: contracts/frontend/configurable_ports.md §4
const frontendPort = parseInt(process.env.ENERGY_GO_FRONTEND_PORT ?? "5173", 10);
const frontendUrl = `http://localhost:${frontendPort}`;

export default defineConfig({
  // testDir: '.' because this config now lives inside the test directory.
  testDir: '.',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,          // smoke suite is small; sequential is fine
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['html', { open: 'never', outputFolder: '../../playwright-report' }],
    ['json', { outputFile: '../../playwright-report/results.json' }],
  ],
  use: {
    baseURL: frontendUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: frontendUrl,
    // cwd MUST be set explicitly: Playwright defaults webServer.cwd to the directory
    // of the configuration file (now tests/frontend_e2e/), NOT the process CWD.
    // Without this, `npm run dev` would launch Vite from tests/frontend_e2e/ and
    // fail to find vite.config.ts / index.html (both at repo root).
    // Contract: contracts/frontend/root_config_consolidation.md §3.4
    cwd: path.resolve(__dirname, '../..'),
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
