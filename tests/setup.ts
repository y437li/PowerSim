import { afterEach, vi } from "vitest";
import { expect } from "vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";
import { configure } from "@testing-library/react";

expect.extend(matchers);

// ── Vitest + @testing-library/react fake-timer fix ───────────────────────────
//
// @testing-library/react's asyncWrapper drains the microtask queue after every
// userEvent action by creating a setTimeout(resolve, 0).  It then checks for
// JEST fake timers (via setTimeout._isMockFunction) and advances them.  But it
// has NO code path for VITEST fake timers.
//
// Result: any test that calls vi.useFakeTimers() and then `await userEvent.*`
// hangs indefinitely (5 s timeout) because the drain Promise never resolves.
//
// Fix: replace asyncWrapper with one that also handles Vitest fake timers via
// vi.isFakeTimers() / vi.advanceTimersByTime(0).  We preserve the React-specific
// IS_REACT_ACT_ENVIRONMENT management that RTL's default asyncWrapper does.
//
// Reference: @testing-library/react/dist/pure.js asyncWrapper implementation.
configure({
  asyncWrapper: async (cb) => {
    // React act environment: same bookkeeping RTL's default does.
    const prevActEnv = (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT;
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
      false;
    try {
      const result = await cb();
      // Drain microtask queue so React state updates flush before we return.
      // RTL's default uses setTimeout(0) + Jest advance; we also handle Vitest.
      await new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
        // Advance Vitest fake timers if active (isFakeTimers() returns false
        // when real timers are installed, so this is a no-op in normal tests).
        if (vi.isFakeTimers()) {
          vi.advanceTimersByTime(0);
        }
      });
      return result;
    } finally {
      (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
        prevActEnv;
    }
  },
});

// Ensure the DOM is cleaned up between tests (required with globals: false)
afterEach(() => {
  cleanup();
});
