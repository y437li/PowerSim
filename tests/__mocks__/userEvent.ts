/**
 * tests/__mocks__/userEvent.ts
 *
 * Thin wrapper around @testing-library/user-event that configures delay: null
 * on the direct API (userEvent.click, .type, .clear, …).
 *
 * WHY: user-event v14 defaults to delay: 0 for the direct API.  Its internal
 * wait() helper then creates setTimeout(fn, 0) after every interaction.  When
 * vi.useFakeTimers() is active in a test that calls userEvent directly (not via
 * userEvent.setup({ advanceTimers })), that fake setTimeout never fires and the
 * call hangs forever (5 s timeout).
 *
 * delay: null makes wait() return undefined immediately (the guard
 *   `if (typeof delay !== 'number') return;`), so every interaction completes
 * synchronously — exactly the right behaviour for unit tests.
 *
 * This file is wired in via vite.config.ts test.alias so the redirect happens
 * at Vite transform time, before any module loading.
 */

// We need the REAL package.  A plain `import … from '@testing-library/user-event'`
// would recurse into this file (Vite alias catches all sub-paths too).
// Bypass Vite's alias resolution by using Node's createRequire — it uses the
// native CJS module cache, not Vite's transform pipeline.
// Diagnostic: verify this mock is being loaded
// eslint-disable-next-line no-console
console.error("[userEvent mock] LOADED from tests/__mocks__/userEvent.ts");

import { createRequire } from "module";
const _require = createRequire(import.meta.url);
const _real = _require("@testing-library/user-event");  // loads real package via Node CJS

const orig = (_real as any).default ?? (_real as any).userEvent ?? _real;

// All direct API methods (click, type, clear, hover, …) share this instance.
const noDelayApi = orig.setup({ delay: null });

// Re-expose setup() so any test that calls userEvent.setup(opts) still works;
// inherit delay: null as the default.
const patched = {
  ...noDelayApi,
  setup: (opts: Record<string, unknown> = {}) =>
    orig.setup({ delay: null, ...opts }),
};

export default patched;
export { patched as userEvent };
