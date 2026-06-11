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
