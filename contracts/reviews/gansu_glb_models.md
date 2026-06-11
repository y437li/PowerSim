# Review Record: Gansu GLB Models (contract + tests gate)

- **Contract:** `contracts/assets/gansu_glb_models.md`
- **Tests:** `tests/frontend3d/gansu_glb_models.test.tsx`
- **PR:** #49 (`feat/assets-gansu-glb-models`, draft) · task #26
- **Reviewer:** frontend-reviewer (gates `contracts/assets/` 3D visual domain, D23)
- **Stage:** 1 — contract + test-cases gate (pre-implementation)
- **Date:** 2026-06-11
- **Verdict:** **APPROVE** (reviewer animation-target tests pushed)

## What is good (verified)

- **Animation-hook names match the LOCKED registry verbatim** — the critical cross-check:
  registry.json v1.0.1 hooks (`rotor_node "Rotor"`, `soc_fill_mesh "SOCFillMesh"`,
  `irradiance_material "PVSurface"`) ↔ contract §3 required node/material names — exact. Paths
  and dims also match (150×166×150, 40×3×20, 20×5×60, 50×15×30). The tests assert BOTH the registry
  hook values AND the GLB node/material names, cross-validating the binding.
- **GLB-renderability is well-specified** (§2): magic, version 2, valid JSON chunk, `asset.version
  "2.0"`, a mesh+primitive with a POSITION accessor `count ≥ 8`, file `> 200 bytes` — explicitly
  rules out the 24-byte §8 stubs (the cause of the black scene).
- **Registry non-regression** (§6/§7.11) and **reproducible generation script** (§4/§7.12) covered.
- **Dev suite is strong**, incl. 4 good developer `reviewer:`-marked edge cases: header `totalLength
  == file length` (a wrong length silently fails GLTFLoader → black scene), JSON chunk 4-byte
  alignment, BIN chunk present (`0x004E4942`) + aligned, and a substation-has-a-mesh check.

## Reviewer tests added (this commit)

The dev tests verify the hook targets exist *by name*, but not that they're *renderable/animatable*.
Added 3 cases pinning §3's box-mesh design so the animations actually display:
- `'Rotor'` node references a mesh (or has children) — an empty node spins nothing.
- `'SOCFillMesh'` node references a mesh — `scale.y` on an empty node shows no SOC fill.
- `'PVSurface'` material is referenced by ≥1 mesh primitive — an unused material renders no emissive.

## Notes

- §8 browser-render check is manual (no automated 3D browser test in v1) — acceptable; QA verifies
  the GLBs load and the 4 asset types render as primitives. The format/geometry/hook-target tests
  here are the automatable backstop.

## Approved suite
Developer cases (§1–§8 + 4 dev edge cases) + my 3 animation-target cases. Locked stage-1 spec; tests
RED until the 4 GLBs + generation script land. Mark ready after implementation for the stage-2 audit.

**Verdict: APPROVE** (stage-1 gate).

---

## Stage-2 implementation audit — PR #49 @ `f2393ee` (marked ready) — **APPROVE**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

Validated the actual GLB bytes (not the test claims) with a standalone Node parser. No findings.

- **All 4 GLBs structurally valid:** glTF magic + version 2 + `header length == file size` +
  JSON chunkType (`0x4E4F534A`) + BIN chunkType (`0x004E4942`), both 4-byte aligned,
  `asset.version "2.0"`, `> 200 bytes`, ≥1 POSITION accessor `count ≥ 8`. Sizes 924–1320 B.
- **Animation-hook targets reference real meshes** (my 3 reviewer checks, verified on real bytes):
  `vestas` `Rotor` → mesh=1 (+ `Tower` mesh=0); `catl` `SOCFillMesh` → mesh=1 inset inner box
  (+ `Container` mesh=0); `trina` `PVSurface` material assigned to the panel primitive
  (`"material": 0`). So rotor-spin / SOC-fill / irradiance animations will actually display.
- **Generation script reproducible (§7.12):** `node scripts/generate_gansu_glbs.js` exits 0 and
  regenerates **byte-identical** files (clean `git status` after re-run).
- **Registry non-regression:** `assets/3d/registry.json` unchanged on the branch (additive files only).
- Reviewer tests intact; 55/55 pass.

§8 browser render stays a manual QA check (no automated 3D browser test in v1).

**Verdict: APPROVE** (stage-2). Mergeable on this APPROVE + QA_PASS.
