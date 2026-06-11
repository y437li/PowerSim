// playwright.config.ts — root of repo (same level as package.json)
// Contract: contracts/frontend/playwright_harness.md §1
import { defineConfig, devices } from '@playwright/test';

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
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
