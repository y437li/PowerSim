/**
 * tests/__mocks__/reactTestingLibrary.ts
 *
 * Thin wrapper around @testing-library/react that makes `render()` auto-cleanup
 * any previously mounted components before each render call.
 *
 * WHY: Tests that call `render()` more than once in the same `it()` block without
 * explicit `unmount()` in between leave multiple component trees in the DOM.
 * `screen.getByTestId(...)` then throws "Found multiple elements" because it
 * searches the entire document.body.
 *
 * Example (T-MAP-5): renders MapPicker twice — once for the success path, once
 * for the denial path — and then calls `screen.getByTestId("use-my-location")`.
 * Without auto-cleanup the two MapPicker roots coexist and the query throws.
 *
 * With auto-cleanup, each `render()` call unmounts the previous render(s) first,
 * so the DOM always contains exactly the component that was just rendered.
 *
 * Compatibility:
 * - Tests that use `rerender` never call `render()` again in the same block,
 *   so the cleanup is a no-op when rerender is in use.
 * - Tests that loop with `render` + explicit `unmount()` (e.g. T-SAVE-1) are
 *   safe: the auto-cleanup before each loop iteration is a no-op after an
 *   explicit unmount().
 *
 * This file is wired in via vite.config.ts test.alias.  We load the real package
 * via Node's createRequire to bypass the Vite alias (same technique as the
 * userEvent mock).
 */

import { createRequire } from "module";

const _require = createRequire(import.meta.url);
// Load the real @testing-library/react via Node CJS (bypasses the Vite alias)
const real = _require("@testing-library/react") as Record<string, unknown>;

// Override `render` with a version that cleans up previous renders first.
const _origRender = real["render"] as Function;
const _cleanup   = real["cleanup"] as () => void;

const patchedRender = function render(...args: unknown[]) {
  // Unmount all previously mounted components so multiple render() calls
  // in the same test don't leave stale component trees in document.body.
  _cleanup();
  return _origRender(...args);
};

// Re-export everything from the real module, overriding render.
const patched: Record<string, unknown> = {
  ...real,
  render: patchedRender,
};

// Named exports — re-export from the patched object so tree-shaking works.
export const render    = patchedRender as typeof import("@testing-library/react")["render"];
export const cleanup   = real["cleanup"]   as typeof import("@testing-library/react")["cleanup"];
export const screen    = real["screen"]    as typeof import("@testing-library/react")["screen"];
export const act       = real["act"]       as typeof import("@testing-library/react")["act"];
export const waitFor   = real["waitFor"]   as typeof import("@testing-library/react")["waitFor"];
export const fireEvent = real["fireEvent"] as typeof import("@testing-library/react")["fireEvent"];
export const within    = real["within"]    as typeof import("@testing-library/react")["within"];
export const renderHook = real["renderHook"] as typeof import("@testing-library/react")["renderHook"];
export const configure  = real["configure"]  as typeof import("@testing-library/react")["configure"];
export const getConfig  = real["getConfig"]  as typeof import("@testing-library/react")["getConfig"];
export const queries    = real["queries"]    as typeof import("@testing-library/react")["queries"];
export const prettyDOM  = real["prettyDOM"]  as typeof import("@testing-library/react")["prettyDOM"];
export const logRoles   = real["logRoles"]   as typeof import("@testing-library/react")["logRoles"];

export default patched;
