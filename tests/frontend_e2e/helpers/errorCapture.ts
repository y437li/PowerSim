/**
 * Error-capture fixture for Playwright smoke tests.
 * Contract: contracts/frontend/playwright_harness.md §2
 *
 * Wraps every test with page-event listeners that collect console errors,
 * page errors, and failed network requests into a structured ErrorReport.
 * After each test the report is appended (as one JSON line) to
 * playwright-report/error-report.ndjson so QA can quote it verbatim.
 *
 * All smoke tests must import { test, expect } from this module instead of
 * '@playwright/test' directly, ensuring error capture is active in every test.
 */

import * as fs from 'fs';
import * as path from 'path';
import { test as base, expect } from '@playwright/test';

// ── Types ──────────────────────────────────────────────────────────────────

export type ConsoleEntry = {
  type: 'error' | 'warning';
  text: string;
  location: string;   // "url:line:col" or empty string
};

export type FailedRequest = {
  url: string;
  method: string;
  status: number;     // HTTP status; 0 for network-level failure
};

export type ErrorReport = {
  testTitle: string;
  consoleErrors: ConsoleEntry[];     // console.error() calls only
  consoleWarnings: ConsoleEntry[];   // console.warn() calls only
  pageErrors: string[];              // pageerror events (unhandled JS exceptions)
  failedRequests: FailedRequest[];   // HTTP 4xx/5xx or network failures
};

// ── Fixture ────────────────────────────────────────────────────────────────

/**
 * Extended Playwright `test` with an `errorCapture` fixture.
 * The fixture:
 *  1. Attaches listeners BEFORE any page navigation (in setup).
 *  2. Yields the live ErrorReport to the test body for inline assertions.
 *  3. After the test body finishes, writes the report as a JSON line to
 *     playwright-report/error-report.ndjson (appended, one entry per test).
 */
export const test = base.extend<{ errorCapture: ErrorReport }>({
  errorCapture: async ({ page }, use, testInfo) => {
    const report: ErrorReport = {
      testTitle: testInfo.title,
      consoleErrors: [],
      consoleWarnings: [],
      pageErrors: [],
      failedRequests: [],
    };

    // console listener — separate errors from warnings; ignore all other types
    page.on('console', (msg) => {
      const type = msg.type();
      if (type === 'error') {
        const loc = msg.location();
        report.consoleErrors.push({
          type: 'error',
          text: msg.text(),
          location: loc ? `${loc.url}:${loc.lineNumber}:${loc.columnNumber}` : '',
        });
      } else if (type === 'warning') {
        const loc = msg.location();
        report.consoleWarnings.push({
          type: 'warning',
          text: msg.text(),
          location: loc ? `${loc.url}:${loc.lineNumber}:${loc.columnNumber}` : '',
        });
      }
      // all other console types (log, info, debug) are silently dropped
    });

    // pageerror listener — unhandled JS exceptions surface here
    page.on('pageerror', (err) => {
      report.pageErrors.push(err.message);
    });

    // response listener — record HTTP 4xx / 5xx responses
    page.on('response', (response) => {
      if (response.status() >= 400) {
        const req = response.request();
        report.failedRequests.push({
          url: response.url(),
          method: req.method(),
          status: response.status(),
        });
      }
    });

    // requestfailed listener — network-level failures (connection refused, timeout)
    page.on('requestfailed', (request) => {
      report.failedRequests.push({
        url: request.url(),
        method: request.method(),
        status: 0,
      });
    });

    // Yield the live report to the test body
    await use(report);

    // Teardown — write report entry to NDJSON file
    const reportDir = path.join(process.cwd(), 'playwright-report');
    if (!fs.existsSync(reportDir)) {
      fs.mkdirSync(reportDir, { recursive: true });
    }
    const ndjsonPath = path.join(reportDir, 'error-report.ndjson');
    fs.appendFileSync(ndjsonPath, JSON.stringify(report) + '\n', 'utf8');
  },
});

export { expect };
