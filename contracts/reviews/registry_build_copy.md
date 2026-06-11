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
