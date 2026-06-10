# Review Record: 3D Site Scene (contract + tests gate)

- **Contract:** `contracts/frontend3d/site_scene.md`
- **Tests:** `tests/frontend3d/site_scene.test.tsx`
- **PR:** #7 (`feat/frontend3d-site-scene`, draft)
- **Reviewer:** frontend-reviewer
- **Stage:** 1 — contract + test-cases gate (pre-implementation)
- **Date:** 2026-06-10
- **Verdict:** **REQUEST_CHANGES** (4 must-fix; reviewer tests pushed to branch)

---

## Scope

Held the contract to REBUILD_SPEC §3.1/§3.3, D3/D4/D5, the just-approved telemetry schema
(PR #6, pending LOCK), and `contracts/frontend/app_shell.md` (`SceneMountPoint.onReady`).
Verified every physics formula's hand-computed expected value and hunted for data-binding
gaps. All telemetry-dependent items are PENDING_LOCK and re-verified at the telemetry LOCK.

## What is excellent (no change)

- **Pure-function physics core is solid** — every formula is pinned with correct, hand-checked
  expected values, with the arithmetic shown:
  - `calcRotorOmega`: v=4→0.2·(1/9), v=7.5→0.1, v=12/18→0.2, v=3/25/30/−1→0 — all correct;
    boundary handling (cut-in inclusive→0, cut-out exclusive plateau) is right.
  - `calcSocFill`: (soc−0.2)/0.7; 0.2→0, 0.55→0.5, 0.9→1, clamps both ends — correct (D4).
  - `calcFlowWidth`/`calcFlowSpeed`: 0→0.5/0.2, 472.5→3.25/1.6, 945→6.0/3.0, neg→min,
    >max→cap — correct (§4.2); div-by-zero guard tested.
  - `calcEmissive`: irr/1000 clamp; 0→0, 540→0.54, 1000→1, 1200→1, 1→0.001 — correct (§7).
- Registry resolution exact-match/case-sensitive/empty/no-partial — good guards.
- Instancing (one InstancedMesh per assetId, count=3 / 146), single canvas, canvas portalled
  into `containerEl` not React root, unmount cleanup — good structural coverage.

## MUST-FIX (blocking)

1. **Component/data-binding tests don't actually inject telemetry — they're comment stubs.**
   The §7 (flow visibility), §8 (stale/freeze), §11 (flow direction) tests render `<SiteScene>`
   and assert on `data-width`/`data-visible`/`data-source`, but the envStep values they claim
   to test ("after store update with wind_to_grid_mw = 80", "store injected with
   ren_curtailed_mw = 50", soc=0.7) are **only in comments** — no `telemetryStore` mock is set
   up and no dispatch happens. As written they cannot pin the data path (the prime directive):
   with a null store, `getByTestId("flow-line-wind_to_grid")` either throws or the asserted
   width is never exercised. **Fix:** add a `telemetryStore` mock harness (e.g. `vi.mock` the
   store, or a `setEnvStep(fixture)` helper) and have each of these tests inject the exact
   envStep it references, then assert the computed attribute. This is the half of the suite that
   actually verifies "which telemetry field drives which visual."

2. **Contract §4.2 omits the upper clamp its own tests assert.** Tests (lines 354, 382) require
   width to cap at 6.0 and speed at 3.0 for `flow_mw > site_max_mw`, but the §4.2 formula
   `0.5 + (flow_mw/site_max)·5.5` has no `[0,1]` clamp on `normalized`. An implementer following
   the contract literally produces width>6.0 and fails the test. **Fix:** §4.2 must state
   `normalized = clamp(flow_mw / site_max_mw, 0, 1)` (it already specifies the lower `flow<0→0`;
   add the upper) and the `site_max_mw == 0 → normalized = 0` guard that test line 766 asserts.

3. **`flows.ren_curtailed_mw` is retired by the now-approved telemetry schema.** PR #6 (frontend
   APPROVE posted) splits it into `solar_curtailed_mw` + `wind_curtailed_mw` and adds
   `generation.gross_*`. The contract (§3.1 table, §4.3 curtailment width
   `ren_curtailed_mw / site_max`, §12.6) and test line 470 still use the old aggregate field.
   **Fix at LOCK:** migrate to the split fields; decide whether curtailment renders as one
   aggregate line (`solar_curtailed + wind_curtailed`) or two per-source lines, and update the
   §4.3 width calc + test accordingly. (Reviewer added a conservation test using the new names.)

4. **Grid import-line denominator is untested and silently maskable.** §8 normalizes export by
   `max_export_mw` and import by `max_import_mw`. For Gansu `max_export_mw == site_max_mw == 945`,
   so an export line that wrongly used `site_max` would pass every test — but import uses 400 MW
   (D12), so a 200 MW import is width 3.25 at /400 vs ~1.66 at /945 (a 2× error). No test pins
   the import denominator. **Fix:** add a test asserting the import grid line passes
   `max_import_mw` (400), not `site_max`/945. (Reviewer added the pure-function half; the
   binding assertion needs the §1 store harness.)

## SHOULD-FIX / notes (non-blocking)

- **Battery charge/discharge/idle indicator (§5, §3.1 binding) is untested.** A swapped
  charge↔discharge label is a real data-correctness bug. Add a test (p_charge>0→"Charging",
  p_discharge>0→"Discharging", both 0→"Idle") once the store harness (must-fix 1) exists.
- **Rotor curve mislabeled "cubic" in comments** (test line 250, contract §6 header context).
  The formula is **linear** in (v−cutin) and the tests assume linear — which is correct for rotor
  RPM (cubic is for power). Fix the wording so an implementer doesn't "correct" it to cubic.
- **Draw-call budget:** only the turbine ≤50 is tested. The headline total ≤100 (§9.3),
  flow-lines ≤15, and battery+substation+terrain ≤20 are unverified. Add at least the total.
- **LOD switching (§9.2) and GLB-404 placeholder (§12.8)** are not unit-testable in jsdom —
  flag for QA / manual verification; acknowledge in the contract.
- **`registry.json` is a SHARED contract** (§1.2, consumed by scene + QA, keys == site-YAML
  asset IDs). Like the telemetry schema it needs rl-architect LOCK and backend-reviewer comment,
  not just this frontend gate — and no `registry.json` instance exists on the branch yet. The
  key↔YAML-asset-ID sync is a config/assets cross-area concern; route it to rl-architect.
- **Optional:** use `generation.gross_solar_mw/gross_wind_mw` (now on the wire) to label source
  totals in the scene.

## Consistency with app_shell (PR #5)

`SceneMountPoint.onReady(el: HTMLDivElement)` (§11) matches app_shell §7.5, and the
`onReady` API is **not** among PR #5's open must-fix items — so this binding is safe even though
PR #5 is currently REQUEST_CHANGES. No contradiction found.

## Reviewer-added tests (pushed, marked `// reviewer:`)

1. Grid import width uses `max_import_mw`=400 → 3.25 (D12)
2. 400 vs 945 denominators give materially different widths (anti-confusion)
3. Grid export at cap → 6.0 via `max_export_mw`=945 (D5)
4. Per-source solar conservation using PR #6 `gross_solar_mw` + `solar_curtailed_mw`
5. Per-source wind conservation (12.5 + 80 == 92.5) — matches PR #6 golden A
6. `calcRotorOmega` monotonic ramp + plateau + v=9 (catches inverted numerator)

**Approved suite = developer cases + these 6 reviewer cases**, all PENDING_LOCK fixtures
conditional on the telemetry LOCK re-check.

## Re-review trigger

(a) the 4 must-fix items addressed (esp. the store-mock harness so component tests inject real
telemetry), and (b) the telemetry LOCK (migrate `ren_curtailed_mw`→split, re-verify all
PENDING_LOCK fixtures). Stage-2 implementation audit on PR-ready.
