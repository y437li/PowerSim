# Review Record: Registry Build Copy (contract + tests gate)

- **Contract:** `contracts/frontend/registry_build_copy.md` · **Tests:**
  `tests/frontend/registry_build_copy.test.ts` · **Plugin:** `src/config/registryBuildPlugin.ts`
- **PR:** #62 (`feat/frontend-registry-build-copy`, draft) · task #37
- **Reviewer:** frontend-reviewer · **Stage:** 1 · **Date:** 2026-06-11
- **Verdict:** **REQUEST_CHANGES** (1 must-fix; 1 reviewer test pushed)
- **Origin:** my PR #10 post-merge flag (auto-generate the hand-maintained registryData.json copy).

## Direction is right
Auto-generating `registryData.json` from the canonical `assets/3d/registry.json` (plugin +
script + npm pre-hooks) and gitignoring the copy eliminates the manual-sync drift at the source.

## MUST-FIX
1. **The plugin won't fire for `vitest run` — the contract's coverage claim is wrong, and this
   breaks the test path on a fresh checkout.** There is a dedicated **`vitest.config.ts`**
   (`defineConfig` from `vitest/config`, own `plugins: [react()]`); Vitest uses it, NOT
   `vite.config.ts`. §1/§Solution add the plugin only to `vite.config.ts` and claim it "covers …
   vitest run (Vitest runs inside Vite)" — false here. Consequence: with `registryData.json`
   gitignored and **every** frontend test importing `gansuSiteConfig → registryData.json`, running
   `npx vitest run` (no `pretest` hook) generates nothing → the whole suite (including the §T9
   correctness gate) fails to import. Only `npm test` (via the `pretest` hook) survives. **Fix:**
   register `registryBuildPlugin` in **`vitest.config.ts`** `plugins` (keep it in `vite.config.ts`
   for dev/build); correct §1/§Solution. The `pretest` hook then becomes a backstop, not the sole
   mechanism for tests. (Note: `vite.config.ts` also still carries a redundant `test:` block now
   that `vitest.config.ts` exists — pre-existing; worth removing to avoid config confusion, non-blocking.)

## Reviewer test pushed (this commit)
- **RB.5** — invokes `registryBuildPlugin.configResolved()` directly and asserts the produced
  `registryData.json` deep-equals `assets/3d/registry.json`. RB.1–4 are structural-only (name /
  hook-shape / script-string-grep) and never execute the copy; RB.5 pins the actual mechanism
  (RED until `configResolved` really copies).

## Approved-on-re-request suite
Developer RB.1–4 + my RB.5. Re-request once the plugin is registered in `vitest.config.ts` and the
contract claim is corrected.

**Verdict: REQUEST_CHANGES.**

---

## Round 2 @ commit `9e6b4af` — **APPROVE**

Must-fix resolved (verified):
- **`vitest.config.ts`** imports + registers `registryBuildPlugin` in `plugins` → the plugin's
  `configResolved` now fires for `vitest run`, so `registryData.json` is generated before any test
  imports `gansuSiteConfig` (incl. §T9 + RB.5). `vite.config.ts` keeps the plugin for dev/build and
  drops its now-redundant `test:` block (Vitest uses `vitest.config.ts` exclusively).
- **Contract §Solution** corrected: the false "Vitest runs inside Vite" claim is replaced with an
  accurate coverage table (invocation → config loaded → plugin location). §5 gains the RB.5 row.
- My **RB.5** functional copy test is intact.

All invocation paths (`vite dev`/`build`, `npm dev/build/test`, `npx vitest run`) now generate the
copy before the gitignored import resolves; the `pretest` hook is a backstop. 5/5 RED at gate
(stub), 780 others green — correct gate state.

**Verdict: APPROVE** (stage-1 gate). Cleared for implementation (real `configResolved` copy +
`copy_registry.js` + npm pre-hooks + `.gitignore`). Mark ready for stage-2.

---

## Stage-2 implementation audit — PR #62 @ `4d9bc1a` — **REQUEST_CHANGES**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

### Good (verified)
- `registryData.json` **gitignored + untracked** — absent in a fresh checkout, `git check-ignore`
  confirms ignored, `git rm --cached` removed it from the index (diff shows −120 lines). ✓
- **Plugin** (`registryBuildPlugin.configResolved`) and **script** share identical `SRC`/`DEST`
  constants; the plugin works (my RB.5 green; 785/785 via `npx vitest run`, which uses the plugin).

### MUST-FIX (caught by running it)
1. **`scripts/copy_registry.js` crashes under the project's `"type": "module"`.** It uses
   `require("fs")`/`require("path")`; Node treats `.js` as ESM → `ReferenceError: require is not
   defined in ES module scope` (exit 1, reproduced in a clean worktree). All three pre-hooks
   (`predev`/`prebuild`/`pretest`) call `node scripts/copy_registry.js`, so **`npm dev`/`build`/
   `test` all abort at the pre-hook step — including CI's `npm test`.** The full-suite pass was via
   `npx vitest run` (plugin path); the script path was never exercised (RB.3/RB.4 only string-grep
   the script source — nothing runs it). **Fix:** rename to `scripts/copy_registry.cjs` + update the
   three package.json hooks to `.cjs` (simplest), OR convert to ESM `import`. Verify `node
   scripts/copy_registry.<ext>` exits 0 and produces a byte-identical copy.

### Test gap (address with the fix)
- No test **executes** the script. RB.5 covers the plugin's `configResolved`; the script's
  ESM-loadability + copy output are untested. Add a test that runs the script (e.g. spawn `node
  scripts/copy_registry.cjs`, assert exit 0 + output deep-equals canonical), or otherwise exercise
  the script path so this class of failure can't recur.

**Verdict: REQUEST_CHANGES.** Rename the script to CJS (or ESM-convert) + fix the hooks + add a
script-execution test, then re-request.

---

## Stage-2 re-audit — PR #62 @ `28eaa4e` — **APPROVE**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

Blocker resolved + verified by running it (the same check that caught it):
- `scripts/copy_registry.js` converted to ESM `import` (no `require()`). In a clean worktree,
  `node scripts/copy_registry.js` → **exit 0**, output byte-identical to `assets/3d/registry.json`,
  still gitignored.
- **RB.6** `execSync`s the script (no-throw = exit 0) + deep-equals the output vs canonical — the
  script path is now functionally guarded (RB.1–4 only grepped the source; RB.5 covers the plugin).
- All invocation paths verified: plugin (registered in vite.config.ts + vitest.config.ts) for
  `vite dev/build` + `vitest run`; the ESM script (via npm pre-hooks) for `npm dev/build/test` + CI.
  RB.1–6 green; 786/786.

**Verdict: APPROVE** (stage-2). Mergeable on this + QA_PASS. Closes task #37 — the hand-maintained
registryData.json copy is now auto-generated and drift-guarded (§T9 content + RB.5 plugin + RB.6 script).

---

## Re-review — CI fix @ `92a2f92` (committed-fallback design change) — **REQUEST_CHANGES**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

**Context:** this commit changed the design AFTER my stage-2 APPROVE + QA_PASS (both @ `28eaa4e`,
the gitignored design). The CI fix reverses it: `registryData.json` is now **committed** (removed
from `.gitignore`, re-added to the index) as a partial-checkout fallback, and the copy (script +
plugin) is **conditional** (`existsSync(SRC)` → copy; source absent + dest present → no-op; neither
→ throw). This supersedes the prior APPROVE + QA_PASS — both need refreshing on `92a2f92`.

### Good
- Conditional logic is correct and symmetric in script + plugin; fixes the partial-checkout ENOENT
  (serving fixture sandbox lacking `assets/3d/`). Committed copy is currently identical to canonical.

### MUST-FIX
1. **No drift guard for the now-committed `registryData.json` — re-opens the task-#37 drift risk in
   committed form.** With the file committed AND the plugin regenerating it at `configResolved`
   *before* §T9 runs, **§T9 can no longer catch a stale committed copy** (regen overwrites it first);
   RB.7 is structural (greps `"existsSync"`); no CI step compares the committed copy to canonical.
   So: edit `assets/3d/registry.json`, forget to regenerate+commit `registryData.json` → the
   committed copy is stale, ships to main, and is used verbatim by any partial-checkout env (the
   conditional's no-op branch) — with nothing catching it. That is precisely the manual-sync drift
   task #37 exists to eliminate. **Fix:** add a CI step (in the frontend job, before/with `npm
   test`) that runs `node scripts/copy_registry.js` then `git diff --exit-code
   src/config/registryData.json` — fail if the committed copy differs from a fresh regen. This forces
   regenerate-and-commit and makes the committed fallback trustworthy. (Document it in §3.)

### SHOULD-FIX
- **RB.7 is structural-only** (greps `"existsSync"`). Add a functional test of the conditional's
  three branches (source present → copies; source absent + dest present → no-op, dest unchanged;
  neither → throws) so the partial-checkout behaviour is actually exercised, not just present in
  source text.

**Verdict: REQUEST_CHANGES.** Add the drift-guard CI check (+ ideally the conditional functional
test), then re-request. The committed-fallback approach is fine *with* the guard.

---

## Re-review — drift guard @ `ffc9f75` — **APPROVE** (stage 2)

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

Both findings from the `92a2f92`/`c716d07` REQUEST_CHANGES are resolved. Verified by running
at `ffc9f75` (detached worktree), not by claim:

**MUST-FIX — CI drift guard (resolved).** `.github/workflows/ci.yml` "Registry committed-copy
drift check" step (in the single full-checkout `checks` job, repo root): runs
`node scripts/copy_registry.js` then `git diff --exit-code src/config/registryData.json`,
guarded by `[ -f assets/3d/registry.json ] && [ -f src/config/registryData.json ]`.
- Positive: in-sync committed copy → step passes. ✓
- **Negative (load-bearing): edited canonical `assets/3d/registry.json`, left committed copy
  stale → step FAILS (nonzero exit).** ✓ This is the real drift scenario (canonical advances,
  regen-and-commit forgotten) and the guard catches it. The earlier §T9 gap (plugin regenerates
  before §T9 runs) is now closed by a check that compares the *committed* copy to canonical.
- §3 documents the step and the rationale.

**SHOULD-FIX — RB.8 functional branch test (resolved).** `copyRegistryIfNeeded(src,dest)`
extracted and exported; `configResolved()` delegates to it (production path == tested path).
RB.8: branch-1 source present → `"copied"` + dest === payload; branch-2 source absent + dest
present → `"skipped"` + dest byte-unchanged (the committed-fallback guarantee); branch-3 neither
→ throws `/copy-registry/`. Temp dirs, no real-FS assumptions. RB suite 11/11 green.

**Verdict: APPROVE (stage 2).** Supersedes my REQUEST_CHANGES. Note: head changed
`28eaa4e`→`ffc9f75`, so the prior QA_PASS @ `28eaa4e` is stale — QA must re-verify at `ffc9f75`
before merge.

---

## Re-review — plugin→scripts/ move @ `f14332f` — **REQUEST_CHANGES**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

This commit moves `src/config/registryBuildPlugin.ts` → `scripts/registryBuildPlugin.ts`
"to fix the §9.5 sandbox `tsc && vite build` TS2307 (fs/path)". It supersedes my APPROVE @
`ffc9f75`. Verified by running, not by claim.

### The move does NOT achieve its stated goal (proven)
- **Probe:** injected `const __PROBE__: string = 123;` into `scripts/registryBuildPlugin.ts`
  and ran `npx tsc` → it reported `scripts/registryBuildPlugin.ts(33,7): error TS2322`. So the
  file is **still in the tsc program** — `tests/frontend/registry_build_copy.test.ts` does
  `await import("../../scripts/registryBuildPlugin")`, and `tests/` is in `tsconfig.include`.
  Moving the plugin out of `src/` does not remove it from `tsc`'s purview while a test imports
  it. In the sandbox env that produced the original TS2307 (no resolvable `@types/node` →
  `fs`/`path` unresolved), the error would **persist via the test's import**.
- The premise "`scripts/` is never typechecked" is false for the default `tsc` (project
  `tsconfig.json`, `include: ["src","tests"]`), which `npm run build` runs (§9.5 step 5).

### The §9.5 build is independently red (pre-existing, not caused by this PR)
- `npx tsc` exits **2** with **138 errors** on `origin/main`, `3bc4ba1`, AND `f14332f`
  (identical — the move changes the tsc outcome by 0). 90 are `toBeInTheDocument` (TS2339):
  `tsconfig.json` has no `types[]`/jest-dom reference, so `tests/setup.ts`'s
  `@testing-library/jest-dom/matchers` augmentation is invisible to `tsc`.
- Therefore `tsc && vite build` never reaches `vite build` — the §9.5 `serving`/`full` build
  is broken regardless of this PR. CI didn't catch it because CI runs `npm test` (vitest =
  esbuild, no tsc), not `npm run build`. The PR's "791/791 + 11/11" were vitest too — they do
  not exercise the `tsc` path this PR claims to fix.

### What's actually correct (keep) / what's missing
- `vite build` is green (exit 0), RB suite 11/11, `copyRegistryIfNeeded` logic byte-identical
  (diff = rename + a rationale comment only). The move is harmless and is the right *direction*.
- **Required fix:** exclude `tests/` from the production build typecheck. e.g. add
  `tsconfig.app.json` (`extends ./tsconfig.json`, `include: ["src"]`) and set
  `"build": "tsc -p tsconfig.app.json && vite build"`. That (a) removes the 138 test-only tsc
  errors from the build, and (b) removes the test's dynamic import of the plugin from the build
  program — at which point relocating the plugin out of `src/` genuinely closes the TS2307. So
  **keep the move, but it must be paired with the build-tsconfig split.**
- Then re-run the **actual `npm run build`** (ideally in a no-devDeps / `--omit=dev` sandbox to
  mirror §9.5 `serving`) and confirm green — vitest does not substitute for this.

### Scope note
This touches build/tsconfig architecture and the (not-yet-implemented) §9.5 install task.
Flagging team-lead + rl-architect on whether the build-tsconfig split belongs in this PR or a
dedicated task. Either way, `f14332f` as-is should not merge under the banner "§9.5 build fixed."

**Verdict: REQUEST_CHANGES.** Supersedes APPROVE @ ffc9f75.

---

## Re-review — tsconfig.app.json split @ `350093a` — **APPROVE** (stage 2, final)

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

Addresses the `f14332f` REQUEST_CHANGES per team-lead's in-scope ruling. Verified by running
the **actual `npm run build`** (not vitest — that was the path that hid the original problem).

- `tsconfig.app.json` (`extends ./tsconfig.json`, `include: ["src"]`, `noEmit`); `package.json`
  `"build": "tsc -p tsconfig.app.json && vite build"`. Base `tsconfig.json` keeps
  `["src","tests"]` for editor/vitest. STACK.md + contract §1 updated.

### Verified by running (worktree @ 350093a, full node_modules = faithful §9.5 build env)
1. **`npm run build` exits 0** end-to-end: `tsc -p tsconfig.app.json` clean → `vite build`
   (1376 modules, ✓ built). The §9.5 step-5 command is genuinely green now.
2. **`tsc -p tsconfig.app.json`: 0 errors** — no TS2307, no 138 `toBeInTheDocument` (tests
   excluded from the production typecheck).
3. **Probe A (plugin out of build program):** injected `const __PROBE__: string = 123;` into
   `scripts/registryBuildPlugin.ts` → build tsc did **not** flag it (count 0). So the plugin is
   truly outside the build program; the TS2307 cannot recur via the RB test's dynamic import.
4. **Probe B (src still checked):** injected a type error into `src/clients/restClient.ts` →
   build tsc **did** flag it (count 1). The build still genuinely typechecks `src/` — not hollow.
5. RB suite green; registry copy + drift guard unchanged from the approved `ffc9f75`.

Both prior findings resolved: TS2307 fix is real (proven, not claimed), and the pre-existing
138-error breakage is cured in the build. Note: team-lead is adding `npm run build` to the
frontend CI job (follow-up) so this path can't regress unseen behind vitest again.

**Verdict: APPROVE (stage 2).** Supersedes my REQUEST_CHANGES @ f14332f. Head moved to
`350093a`, so QA must re-verify here — and should run the real `npm run build`, not just vitest.

---

## Marker refresh @ `8f687ab` — **APPROVE** carried forward

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11

`git diff 350093a 8f687ab` = my review-record file + a 1-line change to
`tests/serving/test_serving_launch_scripts.py` (`+ "tsconfig.app.json"` to the fixture copy
tuple). **No frontend file changed — byte-identical to the `350093a` I probe-tested and
APPROVE'd.** The fixture edit is the correct, necessary co-change: since `build` is now
`tsc -p tsconfig.app.json && vite build`, the §9.5 serving sandbox must copy `tsconfig.app.json`
in or the build hits TS5058 — so this addition makes the sandbox build resolvable. That serving
test is backend-reviewer's gate (blessed, setup-only). My frontend APPROVE stands at `8f687ab`.
