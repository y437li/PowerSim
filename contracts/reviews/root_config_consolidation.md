# Review record — `root_config_consolidation` (PR #99)

**Reviewer:** frontend-reviewer · **Stage:** contract + tests gate · **Date:** 2026-06-12
**Verdict:** REQUEST_CHANGES

## Verified correct
- The 3 moves + 1 merge are well-specified; most path updates are right: tsconfig.app.json
  `extends ./ -> ../`, tsconfig.node.json `include ["vite.config.ts"] -> ["../vite.config.ts"]`,
  build script `tsc -p .config/tsconfig.app.json`, `test:e2e --config`, playwright `testDir: '.'`.
- `tsconfig.json` has NO `references` to the moved configs, so §8's "tsconfig.json unchanged" is safe.
- ci.yml hardcodes none of the moved paths (it invokes npm scripts) — the §6 no-hardcoded-path
  tests are correct.
- Engineer's Q1 (vitest types): the `/// <reference types="vitest/config" />` + `defineConfig`
  from "vite" is the valid official merged-config pattern; the test accepts that OR import from
  "vitest/config". Fine.

## Must-fix
1. **tsconfig.app.json `include` not updated -> breaks `npm run build` in CI.** The file has
   `"include": ["src"]`. `include` resolves relative to the tsconfig file, so after moving to
   `.config/`, `["src"]` -> `.config/src` (nonexistent) -> `tsc -p .config/tsconfig.app.json`
   errors "No inputs were found" -> CI build step (PR #70) fails. Contract §3.2 omits this; it
   must specify `include: ["src"] -> ["../src"]`. ALSO the developer test (suite 6, ~"has include
   array with 'src'") asserts `toContain("src")` — it ENFORCES the broken value and would FAIL on
   the correct `["../src"]`. Change it to `toContain("../src")` + `not.toContain("src")`.
2. **Playwright `webServer.cwd` -> breaks e2e silently.** Verified in
   `node_modules/playwright/types/test.d.ts`: cwd "defaults to the directory of the configuration
   file" — NOT the process CWD as §3.4 claims. After the move, cwd = `tests/frontend_e2e/`, so
   `npm run dev` runs vite from there and can't find root-mandated `vite.config.ts`/`index.html`.
   CI does not run `test:e2e`, so nothing catches it. The moved config MUST set
   `webServer.cwd` back to the repo root (e.g. `cwd: path.resolve(__dirname, '../..')`); correct
   §3.4's reasoning. The developer test only checks `webServer` contains "npm run dev" (no cwd).

## Should-fix
3. **No functional verification.** All tests are structural (existence / field / regex), so a
   structurally-plausible-but-broken config passes (exactly how the include bug slipped in). My
   reviewer tests add structural-but-correct checks (include-resolves-to-real-dir; webServer-cwd-
   climbs-to-root). A `npm run build` smoke in CI/QA would be the belt-and-suspenders.

## Reviewer tests added (`// reviewer:`)
- `.config/tsconfig.app.json include resolves to a real source tree` (catches the include bug;
  requires `../src`, not `src`).
- `playwright webServer runs from repo root after the move` (requires an explicit cwd climbing to
  repo root).

**Verdict: REQUEST_CHANGES** — fix #1 (include + the suite-6 assertion) and #2 (webServer.cwd +
§3.4 text). The migration is otherwise well-specified.
