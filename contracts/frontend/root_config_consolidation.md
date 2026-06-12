# Contract: `root_config_consolidation` — 9 → 6 Root Tool Files

**Area:** `frontend`
**Feature file:** `contracts/frontend/root_config_consolidation.md`
**Branch:** `chore/config-tidy`
**Task:** #62
**Status:** DRAFT — awaiting frontend-reviewer approval

---

## 1. Motivation

USER directive (2026-06-12): too many scattered `.json`/`.ts` files at repo root.
Reduces root tool-file count from 9 to 6 with zero behavior change and zero CI regression.

---

## 2. Before / After

### Before (9 root-level tool files)

```
/
├── package.json          ← stays
├── package-lock.json     ← stays
├── tsconfig.json         ← stays  (editor root anchor)
├── vite.config.ts        ← stays  (Vite mandates root placement)
├── index.html            ← stays  (Vite mandates root placement)
├── pyproject.toml        ← stays  (Python tooling)
├── vitest.config.ts      ← DELETED (merged into vite.config.ts)
├── tsconfig.app.json     ← MOVED  → .config/tsconfig.app.json
├── tsconfig.node.json    ← MOVED  → .config/tsconfig.node.json
└── playwright.config.ts  ← MOVED  → tests/frontend_e2e/playwright.config.ts
```

### After (6 root-level tool files)

```
/
├── package.json
├── package-lock.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── pyproject.toml
├── .config/
│   ├── tsconfig.app.json
│   └── tsconfig.node.json
└── tests/frontend_e2e/
    ├── playwright.config.ts   ← moved here (alongside the tests it configures)
    └── *.spec.ts
```

---

## 3. Change specification

### 3.1 Merge vitest.config.ts → vite.config.ts

**Action:** Delete `vitest.config.ts`. Add `test` block to `vite.config.ts`.

**Pattern:** [official Vitest merged-config pattern](https://vitest.dev/config/#test)

```typescript
// vite.config.ts — after merge
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
// ... existing imports ...

export default defineConfig({
  plugins: [...],
  server: { ... },   // unchanged
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.tsx", "tests/**/*.test.ts"],
  },
});
```

**Note:** `/// <reference types="vitest/config" />` is required for TypeScript to type-check the
`test` key. The underlying `defineConfig` import remains from `"vite"` (not `"vitest/config"`),
which is the correct pattern for merged configs.

**Invariant:** `npm test` (→ `vitest run`) continues to find and run all frontend tests.

### 3.2 Move tsconfig.app.json → .config/tsconfig.app.json

**Action:** Create `.config/` directory. Move file. Update two internal fields.

**Content changes** in `.config/tsconfig.app.json`:
- `"extends": "./tsconfig.json"` → `"extends": "../tsconfig.json"` (one level up to root)
- `"include": ["src"]` → `"include": ["../src"]`

  **Why `include` must change:** TypeScript resolves `include` patterns relative to the
  tsconfig file, not the process CWD. After the move to `.config/`, `["src"]` resolves to
  `.config/src` (which does not exist), causing `tsc -p .config/tsconfig.app.json` to error
  with "No inputs were found" — breaking `npm run build` in CI. The correct relative path
  from `.config/` to the source tree is `"../src"`.

**Script change** in `package.json`:
- `"build": "tsc -p tsconfig.app.json && vite build"` → `"build": "tsc -p .config/tsconfig.app.json && vite build"`

**Invariant:** `npm run build` continues to typecheck and bundle.

### 3.3 Move tsconfig.node.json → .config/tsconfig.node.json

**Action:** Move file. Update internal include path.

**Content change** in `.config/tsconfig.node.json`:
- `"include": ["vite.config.ts"]` → `"include": ["../vite.config.ts"]` (one level up to root)

**No script changes needed** — `tsconfig.node.json` is not referenced in any npm script; it
exists for editor/IDE project-reference support only.

### 3.4 Move playwright.config.ts → tests/frontend_e2e/playwright.config.ts

**Action:** Move file alongside its tests. Update two paths inside the config.

**Content changes** in `tests/frontend_e2e/playwright.config.ts`:
- `testDir: './tests/frontend_e2e'` → `testDir: '.'`
  (config is now in the test dir; `'.'` = same directory as the config file)
- `reporter` `outputFile: 'playwright-report/results.json'` path stays relative to
  Playwright `rootDir`, which defaults to config file's directory. If reporter output
  should stay at repo root, set to `'../../playwright-report/results.json'`. Either
  is acceptable — implementer picks and documents.
- `webServer.cwd` — **must be set explicitly** to the repo root:

  ```typescript
  webServer: {
    command: 'npm run dev',
    cwd: path.resolve(__dirname, '../..'),   // ← REQUIRED after move
    // ...
  }
  ```

  **Why `cwd` must be set:** Playwright's `webServer.cwd` "defaults to the directory of
  the configuration file" (verified in `playwright/types/test.d.ts`), **not** the
  process CWD. After the move, the default cwd becomes `tests/frontend_e2e/`, so
  `npm run dev` would launch Vite from there — where neither `vite.config.ts` nor
  `index.html` exist — causing the e2e dev server to misconfigure. CI does not run
  `test:e2e`, so this would merge green and silently break all local/CI e2e runs.
  `path.resolve(__dirname, '../..')` climbs from `tests/frontend_e2e/` to the repo root.

**Script change** in `package.json`:
- `"test:e2e": "playwright test"` → `"test:e2e": "playwright test --config tests/frontend_e2e/playwright.config.ts"`

**Invariant:** `npm run test:e2e` continues to discover and run `tests/frontend_e2e/*.spec.ts`.

---

## 4. Files explicitly NOT moved

Per task #62 (USER directive):

| File | Reason |
|---|---|
| `package.json` | npm mandates root placement |
| `package-lock.json` | npm mandates root placement |
| `tsconfig.json` | root anchor for editor TypeScript support |
| `vite.config.ts` | Vite mandates root placement |
| `index.html` | Vite mandates root placement |
| `pyproject.toml` | Python tooling root convention |

---

## 5. STACK.md update

Add a note under the Frontend tooling section that:
- Vitest config lives in `vite.config.ts` (merged), not a separate file
- TypeScript project configs live under `.config/`
- Playwright config lives at `tests/frontend_e2e/playwright.config.ts`

---

## 6. CI invariants

| CI check | Before | After | Change |
|---|---|---|---|
| `npm test` | reads `vitest.config.ts` | reads `vite.config.ts` `test:` block | merged source, same behaviour |
| `npm run build` | `tsc -p tsconfig.app.json` | `tsc -p .config/tsconfig.app.json` | path updated in script |
| `npm run test:e2e` | `playwright test` | `playwright test --config tests/frontend_e2e/playwright.config.ts` | explicit config path |
| CI workflow `.github/workflows/ci.yml` | uses `npm test` + `npm run build` | unchanged | CI file not modified |

**The CI workflow file is NOT modified** — it invokes npm scripts, which are updated in
`package.json`. Any path-based grep of the workflow file for `tsconfig.app.json`,
`vitest.config.ts`, or `playwright.config.ts` must return zero hits (they were never hardcoded
there).

---

## 7. Deliberate deviations

None — this is a pure structural relocation with no behavior change.

---

## 8. Out of scope

- Any changes to `tsconfig.json` content (root anchor stays as-is)
- Changing test files themselves
- Any frontend component changes
- `eslint.config.js` if present (not in scope)
- Additional build config cleanup beyond the 3 moves + 1 merge specified
