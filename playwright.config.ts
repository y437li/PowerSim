// playwright.config.ts — root of repo (same level as package.json)
// Contract: contracts/frontend/playwright_harness.md §1
//           contracts/frontend/configurable_ports.md §4 (frontend port env var)
import { defineConfig, devices } from '@playwright/test';

// ENERGY_GO_FRONTEND_PORT: port Vite dev server binds to (default 5173).
// When unset the value is identical to the previous hardcoded constant.
// Contract: contracts/frontend/configurable_ports.md §4
const frontendPort = parseInt(process.env.ENERGY_GO_FRONTEND_PORT ?? "5173", 10);
const frontendUrl = `http://localhost:${frontendPort}`;

export default defineConfig({
  testDir: './tests/frontend_e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,          // smoke suite is small; sequential is fine
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['html', { open: 'never' }],
    ['json', { outputFile: 'playwright-report/results.json' }],
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
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
