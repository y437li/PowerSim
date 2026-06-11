# Review Record: scene_graph extend(THREE) fix (contract amendment + tests gate)

- **Contract:** `contracts/frontend3d/scene_graph.md` (amended — §3.2/§3.4/§6 req 21-22)
- **Tests:** `tests/frontend3d/scene_graph.test.tsx`
- **PR:** #57 (`fix/frontend3d-scene-extend`, draft)
- **Reviewer:** frontend-reviewer · **Stage:** 1 (contract + test-cases gate)
- **Date:** 2026-06-11 · **Verdict:** **APPROVE**

## The bug (well-diagnosed)
Real browser crash, invisible in jsdom (R3F fully mocked): the manual `createRoot(canvas)` path
does NOT auto-register the THREE namespace the way `<Canvas>` does, so R3F throws "AmbientLight is
not part of the THREE namespace! Did you forget to extend?" in Chrome/Firefox. Exactly the
jsdom blind spot the §8 manual browser-render check was meant to backstop.

## What is good (verified)
- **Amendment is precise & minimal.** §3.2: `const { createRoot, extend } = await import(...)` +
  `extend(THREE)` before `createRoot`, idempotent (safe per mount). §3.4: `import * as THREE from
  "three"`. §6 req 21 (extend with the THREE namespace before render; order extend→createRoot→render)
  + req 22 (once per mount; skipped when `containerEl=null`). `extend` stays in the dynamic fiber
  import (preserves the lazy-load pattern that keeps jsdom tests working).
- **5 regression tests pin it correctly:** extend called (1); arg is the real THREE namespace —
  `AmbientLight`/`DirectionalLight`/`Mesh` present, catching a wrong/partial object (2); **extend
  before render** via a `callOrder` array (3) — the correctness-critical ordering; exactly once per
  mount (4); not called when `containerEl=null` (5).
- **Right constraint granularity:** test 3 asserts extend-before-**render** (not before-createRoot),
  so a `createRoot→extend→render` impl (also correct) isn't falsely rejected.
- **Backward-compat:** the `vi.hoisted` change is a mock refinement only (`extend: vi.fn()` →
  `extend: mockExtend`, cleared in beforeEach) — the existing 48 scene_graph tests don't assert on
  extend and still pass.

## Notes (merge coordination — team-lead)
- This `fix/` branch amends the same files as PR #52 (scene_graph, in QA). Merge ordering vs #52
  is a team-lead concern, not a gate issue.

## Approved suite
Developer scene_graph suite + the 5 extend regression tests. Cleared for implementation (the 3-line
`extend(THREE)` addition in Effect 1). Mark ready for stage-2.

**Verdict: APPROVE** (stage-1 gate).
