/**
 * reportPaths — canonical output paths for E2E test artifacts.
 * Contract: contracts/frontend/playwright_harness.md §2 (task #16 amendment)
 *
 * Single source of truth for the error-report.ndjson path so both
 * errorCapture.ts (writer) and playwright_harness.test.ts (verifier)
 * reference the same constant — drift is caught immediately.
 */

/** Directory for E2E artifact files (traces, error reports).
 *  Must NOT be playwright-report/ — that directory is cleared by the HTML
 *  reporter at the start of every run (task #16 fix).
 *  test-results/ is Playwright's conventional artifact directory and is not
 *  managed/cleared by any reporter plugin.
 */
export const ERROR_REPORT_DIR = "test-results";

/** Full relative path to the error-report NDJSON file.
 *  One JSON line appended per test by the errorCapture fixture.
 */
export const ERROR_REPORT_PATH = `${ERROR_REPORT_DIR}/error-report.ndjson`;
