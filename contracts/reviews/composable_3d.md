# Review Record: §8 Composable 3D Assets (contract + tests gate)

- **Contract:** `contracts/assets/composable_3d.md`
- **Tests:** `tests/frontend3d/composable_3d.test.tsx`
- **PR:** #38 (`feat/assets-composable-3d`, draft) · task #15
- **Reviewer:** frontend-reviewer (gates `contracts/assets/` 3D visual domain per D23)
- **Stage:** 1 — contract + test-cases gate (pre-implementation)
- **Date:** 2026-06-10
- **Verdict:** **REQUEST_CHANGES** (2 must-fix contract clarifications; reviewer edge tests pushed)

---

## Scope & authority

Per **D23**: the §8 asset/visual side is cleared now (not gated by D2's env-side parity rule);
**frontend-reviewer gates** (no backend-reviewer gate, no rl-architect re-LOCK) because this is
purely additive — new GLB entries + new `AssetType` values + new optional `AnimationHooks` fields,
none of which change/remove a LOCKED field. Schema bump 1.0.0 → 1.0.1 (minor, no re-LOCK).

## What is good (verified, no change needed)

- **Taxonomy is spec-faithful, not invented (D23 guardrail satisfied).** All 9 IDs derive from
  REBUILD_SPEC §8's named assets — cross-checked against `docs/spec/section_08_composable_assets.md`:
  §8.2 "aeroderivative class P_max 30 MW" → `gas-turbine-30mw`; "P_max_ely 20 MW, tank 2000 kg" →
  `pem-/alkaline-electrolyzer-20mw`; §8.3's six archetype keys (`commercial`, `residential`,
  `industrial_continuous`, `industrial_two_shift`, `data_center`, `ev_fleet`) → the six `load-*`
  IDs, 1:1. §8.5 line 94 ("gas turbine hall, electrolyzer skid + H₂ tank with fill level,
  per-archetype load buildings") matches the model exactly.
- **All 9 IDs satisfy `^[a-z0-9][a-z0-9.-]*$`** (hyphenated, since the key format forbids the
  snake_case underscores of the env archetype keys).
- **Additive & non-regressive:** 4 LOCKED Gansu entries untouched; schema bump correct.
- **In-scope suite is strong:** specific dims, exact types, exact IDs, format, Gansu
  non-regression, 13-total count, GLB magic header (`67 6C 54 46`), path-traversal guard,
  resolveAsset null-cases (partial/case-variant/unknown), AnimationHooks field presence. Good
  developer-authored `// reviewer:` cases already present.

## MUST-FIX (blocking — contract clarifications before implementation)

1. **Additively update the LOCKED schema doc `registry_schema.md`, not just `src/scene/types.ts`.**
   The contract adds the 3 new `AssetType` values and 3 new `AnimationHooks` fields only to
   `src/scene/types.ts` (§2, §3, §7.1–7.2). But `contracts/assets/registry_schema.md` §1.1
   (AssetType enum table) and §1 (AnimationHooks field table) are the **authoritative LOCKED
   schema doc** reviewers/validators check against — leaving them out makes the LOCKED doc stale
   vs the 1.0.1 registry. **Fix:** the implementation PR must additively add to `registry_schema.md`
   §1.1 (`gas_turbine`→`gas/`, `electrolyzer`→`electrolyzers/`, `load_building`→`loads/`) and §1
   (`h2_fill_mesh`, `activity_material`, `flame_node` as optional). This is additive → no re-LOCK,
   within frontend-reviewer's gate per D23. State this in the contract (§6/§7).

2. **Resolve the §3 (mapping formulas) vs §9 (binding out-of-scope) scope ambiguity.** §3.1–3.3
   specify precise driver math (`h2_fill`/`activity`/`flame` with clamps), but §9 defers
   per-instance telemetry binding and this PR ships no driver function or test for them (v1 scene
   is lumped; the §8 telemetry fields `h2_level_kg`/`current_load_mw`/`p_dispatch_mw` are not on the
   LOCKED telemetry schema). **Fix:** state explicitly that §3.1–3.3 are forward-spec for the
   future telemetry-binding PR — this PR ships only the registry node-name fields — and record the
   deferred obligation that the eventual driver functions (analogues of `calcSocFill`/`calcEmissive`)
   MUST be gated with tests for: NaN/Infinity → defined output; `[0,1]` clamp; `base_mw == 0`
   division-by-zero → 0; and a sub-tolerance **flame epsilon** (`p_dispatch_mw > ε`, mirroring
   deriveAlerts `ALERT_EPSILON`) so float noise doesn't flicker the flame. So these edge cases
   aren't lost between gates.

## Reviewer edge-case tests pushed (commit 6948310)

Added to the suite (in-scope completeness; RED until implementation, same as the rest):
- `'${id}'` has a finite, base-centre pivot `{0,0,0}` (schema requires pivot.x/y/z) — 9 cases.
- `'${id}'` dims_m are **finite** — the existing `> 0` check passes `Infinity` (`Infinity > 0`
  is `true`); this closes the extreme-value gap — 9 cases.
- New §8 IDs are **disjoint** from the 4 LOCKED Gansu IDs (§8 edge case 3 — explicit no-collision).
- Each new entry uses one of the 3 new §8 `AssetType` values (no stray legacy type).

## Approved suite (on re-request)

Developer cases + reviewer cases above. Re-request when the two must-fix contract clarifications
land; I expect a fast turnaround (contract-text only).

---

## Round 2 @ commit `c79a4bb` — **APPROVE**

Both must-fix contract clarifications resolved (verified against the diff):

1. **registry_schema.md additive sync — resolved.** §6 (retitled "Schema version and authoritative
   schema doc update") now commits the impl PR to additively update
   `contracts/assets/registry_schema.md` §1.1 (the three `AssetType` rows with correct subdirs:
   `gas_turbine`→`gas/`, `electrolyzer`→`electrolyzers/`, `load_building`→`loads/`), §1 (the three
   optional `AnimationHooks` fields with their mapping descriptions), and §4 (the 9 IDs); §7 rules
   1–2 amended to require recording there, not just `src/scene/types.ts`. **Bonus:** §7 rules 7–8
   codify my reviewer edge tests into the contract validation rules — `dims_m` and `pivot` must be
   `Number.isFinite` ("`> 0` alone admits `Infinity > 0 === true`").
2. **§3/§9 scope ambiguity — resolved.** §3 opens with a forward-spec scope note (this PR ships
   only node-name registry fields; `calcH2Fill`/`calcActivity`/`calcFlameVisible` driver functions
   + telemetry bindings deferred to the first PR adding per-asset H₂/load/dispatch fields to the
   LOCKED telemetry schema). A "Deferred obligation" block records the future PR's required tests
   (NaN/Infinity→defined, [0,1] clamp, `base_mw==0` and `h2_tank_capacity_kg==0` div-by-zero→0,
   flame epsilon). §3.1–3.3 retitled "(forward-spec)"; §3.3 now `p_dispatch_mw > ALERT_EPSILON`
   (shared `deriveAlerts` constant). The deferred edge cases are now contract-recorded so they
   carry into the future telemetry-binding gate.

Reviewer edge tests (commit `6948310`) confirmed untouched (no test modification). 0 unresolved
review threads.

### Approved suite
Developer cases + my 4 reviewer edge-test groups (finite base-centre pivot; finite dims_m;
new-vs-Gansu ID disjointness; new-entry AssetType membership). This is the locked stage-1 spec;
tests are RED by design (no registry.json/GLB/`src/scene/types.ts` impl yet) and go green under QA
after implementation.

**Verdict: APPROVE** (stage-1 contract+tests gate). Cleared for implementation. Mark the PR ready
when the registry.json entries, GLB stubs, `src/scene/types.ts` additions, and the registry_schema.md
additive update land, and I run the stage-2 audit.

---

## Stage-2 implementation audit — PR #38 @ `7d9d7d0` (marked ready) — **APPROVE**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

Verified all four deliverables against the actual files (not the summary):

1. **`registry.json` — correct.** `schema_version` `1.0.1`; the 4 Gansu entries are **byte-identical**
   to LOCKED v1.0.0 (untouched); 9 new entries match contract §4 exactly (type / dims_m / pivot
   {0,0,0} / animation_hooks). 13 total. All IDs format-valid; all dims & pivots finite.
2. **`registry_schema.md` additive sync (must-fix #1) — correct.** §1 +3 AnimationHooks rows
   (`h2_fill_mesh`/`activity_material`/`flame_node`, forward-spec mappings); §1.1 +3 AssetType rows
   (`gas_turbine`→`gas/`, `electrolyzer`→`electrolyzers/`, `load_building`→`loads/`) with an
   "additive — no re-LOCK" note; §4 replaced with the 9-entry §8 table. The §4 dims match
   `registry.json` and contract §4 verbatim — single source of truth preserved. Additive (no field
   removal/rename/retype) → no re-LOCK, within frontend-reviewer gate per D23.
3. **9 GLB stubs — valid.** Magic `67 6C 54 46` ("glTF") + version `02 00 00 00` + length
   `18 00 00 00` (24 bytes) — minimal valid GLB v2 under `gas/`, `electrolyzers/`, `loads/`.
4. **`src/scene/types.ts` — correct.** `AssetType` += the 3 new values; `AnimationHooks` += the 3
   new optional fields (with mapping doc-comments); existing 7 types / 3 hooks unchanged.

- **Reviewer edge tests (commit 6948310) intact** — pivot finite, dims finite, ID disjointness,
  type membership — no test modification. **92/92 pass** (developer + reviewer suite).
- No scene-consumption / hardcoded-path / LOD concerns this PR — it ships the asset *library*;
  scene rendering of §8 assets and the telemetry-binding driver functions are future work
  (recorded deferred obligation in contract §3).

**Verdict: APPROVE** (stage-2). Mergeable on this APPROVE + QA_PASS. No findings.
