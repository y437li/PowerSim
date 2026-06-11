# Review Record: Scene Graph — 3D Site Render (contract + tests gate)

- **Contract:** `contracts/frontend3d/scene_graph.md`
- **Tests:** `tests/frontend3d/scene_graph.test.tsx`
- **PR:** #52 (`feat/frontend3d-scene-graph`, draft) · task #28
- **Reviewer:** frontend-reviewer · **Stage:** 1 (contract + test-cases gate)
- **Date:** 2026-06-11
- **Verdict:** **APPROVE** (1 reviewer test pushed)

## What is good (verified)

- **Asset resolution is registry-only (LOCKED invariant preserved).** `glbUrl` =
  `resolveAsset(registry, id)` → `/assets/3d/${entry.path}`; no hardcoded paths. Tests pin all 4
  Gansu URLs, null for unknown/empty, "every URL starts with `/assets/3d/`", suffix == registry
  `entry.path` verbatim, and resolves runtime-added entries.
- **Animation drivers correctly bound to telemetry, golden values verified against the real PR #7
  utilities.** Cross-checked `calcRotorOmega` (line 35: `windSpeed >= cutOut → 0`) — so the golden
  table is correct: cut-in `3→0`, mid-ramp `7.5→0.1` (`0.2*4.5/9`), rated `12→0.2`, **cut-out
  `25→0`** (inclusive, the 3/25 boundary). `calcEmissive` `500→0.5`, `1500→1.0` (clamp);
  `calcSocFill` D4 `0.2→0`, `0.55→0.5`, `0.9→1.0`. All tested via the data-bridge attributes
  (`data-omega`/`data-soc-fill`/`data-emissive`).
- **Graceful freeze on bad/absent telemetry.** `isPayloadFinite` last-valid-step guard: null
  telemetry → all drivers 0; NaN/Inf → **freeze at last valid value** (not 0/NaN), tested. The
  `isPayloadFinite` utility is tested (golden pass, NaN top-level, Inf nested-flow).
- **The actual bug fix is pinned:** `r3fRoot.render(<SceneContent/>)` is called after
  `createRoot` (not just `createRoot(canvas)`), with correct props, re-render on config change
  (Effect 2), unmount preserved. Lights (ambient 0.5, directional 1.0 @ [100,200,100], castShadow
  false) and `useGLTF`-once-per-unique-assetId all tested.

## Reviewer test pushed (this commit)

- **Recovery after a NaN gap → animation resumes at the new valid value** (freeze is transient,
  not sticky). Complements the existing valid→NaN freeze test; a latched freeze would leave the
  scene stuck on the pre-gap value forever. (valid 12→0.2 → NaN gap → valid 7.5→0.1 resumes.)

## Notes (non-blocking)

- **Vite serving (§4):** the `public/assets → ../assets` symlink works in dev; for the production
  build (and cross-platform/Windows checkout portability), the `vite-plugin-static-copy` alternative
  the contract already permits is the safer choice. Either is conformant for v1 (the demo runs via
  `vite dev`); worth confirming the prod-build path when it matters.
- Out-of-scope list (flow lines, LOD, InstancedMesh, shadows, camera, terrain, §8 asset types) is
  clearly bounded and consistent with the data-bridge draw-call accounting (counts unique assetIds).

## Approved suite
Developer cases (§1–§6 + the developer `reviewer:`-marked cases) + my recovery-after-gap test.
Cleared for implementation; mark ready for the stage-2 audit (registry-only resolution, render()
wiring, animation freeze/recovery on real telemetry, the Vite serving change).

**Verdict: APPROVE** (stage-1 gate).
