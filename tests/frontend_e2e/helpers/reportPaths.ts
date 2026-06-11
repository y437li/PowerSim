/**
 * reportPaths — canonical output paths for E2E test artifacts.
 * Contract: contracts/frontend/playwright_harness.md §2 (task #16 amendment)
 *
 * Single source of truth for the error-report.ndjson path so both
 * errorCapture.ts (writer) and playwright_harness.test.ts (verifier)
 * reference the same constant — drift is caught immediately.
 *
 * STUB (gate stage): path is intentionally wrong (playwright-report/) so the
 * playwright_harness test is RED. Implementation changes this to test-results/.
 */

/** Directory for E2E artifact files (traces, error reports).
 *  Must NOT be playwright-report/ — that directory is cleared by the HTML
 *  reporter at the start of every run (task #16).
 */
export const ERROR_REPORT_DIR = "playwright-report"; // STUB — implementation changes to "test-results"

/** Full relative path to the error-report NDJSON file. */
export const ERROR_REPORT_PATH = `${ERROR_REPORT_DIR}/error-report.ndjson`; // will become "test-results/error-report.ndjson"
