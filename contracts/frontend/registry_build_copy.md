# Contract: Registry Build Copy

- **Status:** DRAFT — gate pending (frontend-reviewer)
- **Spec:** REBUILD_SPEC.md §8 (composable assets)
- **Owner:** frontend-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend
- **Task:** #37 (low priority)
- **Follow-up from:** PR #10 post-merge audit (frontend-reviewer flag)

---

## Problem

`src/config/registryData.json` is a **hand-maintained copy** of `assets/3d/registry.json`
kept inside `src/` as a TypeScript-resolution workaround (Vite/tsc cannot resolve a JSON
import from `../../assets/` when `rootDir` is `src/`). Every time `assets/3d/registry.json`
changes, a developer must manually copy it or `app_integration §T9` (deep-equals) fails.

---

## Solution

Replace the hand-maintained copy with an **auto-generated copy** produced by a Vite plugin
that fires at `configResolved` time (before any transform).

**Coverage note:** this project has a **separate `vitest.config.ts`** (uses `vitest/config`,
not `vite`). `vitest run` loads `vitest.config.ts`, not `vite.config.ts`. The plugin must
therefore be registered in **both** config files to cover all invocation paths:

| Invocation | Config loaded | Plugin needed in |
|------------|---------------|-----------------|
| `vite dev` | `vite.config.ts` | `vite.config.ts` |
| `vite build` | `vite.config.ts` | `vite.config.ts` |
| `npm run dev/build` | `vite.config.ts` | `vite.config.ts` |
| `npx vitest run` | `vitest.config.ts` | `vitest.config.ts` |
| `npm test` (via pretest hook) | `vitest.config.ts` | `vitest.config.ts` |

A standalone copy script is provided for CI pre-build steps and manual invocation outside Vite.

The `test:` block inside `vite.config.ts` is redundant (Vitest uses `vitest.config.ts`) and
must be removed to avoid config confusion.

---

## 1. Vite plugin (`src/config/registryBuildPlugin.ts`)

A new plain-TS module (no Vite runtime dependency) that exports a Vite plugin object:

```typescript
import { copyFileSync, mkdirSync } from "fs";
import { dirname } from "path";

export const registryBuildPlugin = {
  name: "copy-registry",
  configResolved() {
    mkdirSync(dirname("src/config/registryData.json"), { recursive: true });
    copyFileSync("assets/3d/registry.json", "src/config/registryData.json");
  },
};
```

The plugin is added to **both** config files:

**`vite.config.ts`** (covers `vite dev` and `vite build`):
```typescript
import { registryBuildPlugin } from "./src/config/registryBuildPlugin";
// ...
plugins: [react(), registryBuildPlugin],
```

**`vitest.config.ts`** (covers `npx vitest run` and `npm test`):
```typescript
import { registryBuildPlugin } from "./src/config/registryBuildPlugin";
// ...
plugins: [react(), registryBuildPlugin],
```

The `test:` block inside `vite.config.ts` must be removed — Vitest uses `vitest.config.ts`
exclusively; the duplicate `test:` key in `vite.config.ts` only causes confusion.

---

## 2. Standalone copy script (`scripts/copy_registry.js`)

**ESM syntax required** — `package.json` has `"type": "module"` so Node treats `.js`
files as ESM. `require()` is not available; use `import`.

**Partial-checkout behaviour** — builds from sandboxed fixtures or partial checkouts
(e.g. the serving acceptance test, CI bundles that do not include `assets/3d/`) must
not abort. The script and plugin are therefore conditional:

| Source exists | Dest exists | Behaviour |
|---------------|-------------|-----------|
| ✓ | any | Copy (fresh, overwrites committed fallback) |
| ✗ | ✓ | Log note, proceed — committed copy is the fallback |
| ✗ | ✗ | Hard-fail (nothing to resolve the import) |

```js
// scripts/copy_registry.js — copy assets/3d/registry.json → src/config/registryData.json
import { copyFileSync, mkdirSync, existsSync } from "fs";
import { dirname } from "path";
const SRC = "assets/3d/registry.json";
const DEST = "src/config/registryData.json";
if (existsSync(SRC)) {
  mkdirSync(dirname(DEST), { recursive: true });
  copyFileSync(SRC, DEST);
  console.log("registry copied: assets/3d/registry.json → src/config/registryData.json");
} else if (existsSync(DEST)) {
  console.log("registry copy skipped: source absent, using committed fallback");
} else {
  throw new Error("neither assets/3d/registry.json nor src/config/registryData.json exists");
}
```

Same conditional guard applies in `registryBuildPlugin.ts`'s `configResolved()`.

Wire npm pre-hooks so the copy also runs for `npm run build`, `npm run dev`, `npm test`:

```json
{
  "prebuild": "node scripts/copy_registry.js",
  "predev":   "node scripts/copy_registry.js",
  "pretest":  "node scripts/copy_registry.js"
}
```

---

## 3. `src/config/registryData.json` — committed fallback

`src/config/registryData.json` is **committed** (tracked in git) and serves as the
fallback for partial-checkout builds. It is NOT gitignored.

When `assets/3d/registry.json` is present (full checkout), the copy script/plugin
overwrites the committed file with the fresh copy. `§T9` (deep-equals
`ASSET_REGISTRY` vs raw `assets/3d/registry.json`) guards drift on full-checkout CI
runs — if both exist and differ, the test fails.

Developer workflow when updating `assets/3d/registry.json`:
1. Update the registry
2. Run `npm test` (pretest hook auto-copies the updated file)
3. Commit both `assets/3d/registry.json` and the updated `src/config/registryData.json`

The source of truth is `assets/3d/registry.json` (LOCKED, `registry.json` v1.0.1).
`src/config/registryData.json` is the committed fallback; it is **not** gitignored and
**must** be kept in the index so partial-checkout builds (§9.5 serving fixture) can
resolve the import without `assets/3d/` present.

### CI drift check (`.github/workflows/ci.yml` — "Registry committed-copy drift check" step)

Because the plugin regenerates the file *before* §T9 runs, §T9 cannot catch a stale
committed copy. A dedicated CI step closes this gap:

```yaml
- name: Registry committed-copy drift check
  shell: bash
  run: |
    if [ -f assets/3d/registry.json ] && [ -f src/config/registryData.json ]; then
      node scripts/copy_registry.js
      git diff --exit-code src/config/registryData.json || \
        (echo "ERROR: src/config/registryData.json is stale" && exit 1)
    fi
```

This step runs after "Frontend tests" (where `pretest` already ran the copy). If
`assets/3d/registry.json` and the committed copy differ, `git diff --exit-code` returns
non-zero and CI fails with a clear message. Skipped on partial-checkout environments
where `assets/3d/registry.json` is absent.

---

## 4. Backward compatibility

- `gansuSiteConfig.ts` continues to import `./registryData.json` unchanged — no code changes.
- `app_integration §T9` (deep-equals `ASSET_REGISTRY` vs raw `assets/3d/registry.json`)
  remains the correctness gate; it now also implicitly verifies that the plugin ran when
  both files exist.
- On a fresh checkout, `src/config/registryData.json` is present immediately (committed
  fallback). Running `npm run dev`, `npm test`, or `npx vitest run` refreshes it with the
  latest `assets/3d/registry.json` when that file is available.

---

## 5. Acceptance criteria

### §T_RBC (registry-build-copy unit tests)

All tests live in `tests/frontend/registry_build_copy.test.ts`.

| ID | Description | Expected |
|----|-------------|----------|
| RB.1 | `registryBuildPlugin.name` | `"copy-registry"` |
| RB.2 | `registryBuildPlugin.configResolved` is a function | `true` |
| RB.3 | `scripts/copy_registry.js` mentions the source path | contains `"assets/3d/registry.json"` |
| RB.4 | `scripts/copy_registry.js` mentions the dest path | contains `"src/config/registryData.json"` |
| RB.5 (reviewer) | calling `configResolved()` produces a `src/config/registryData.json` that deep-equals `assets/3d/registry.json` | `expect(copied).toEqual(canonical)` |
| RB.6 | `node scripts/copy_registry.js` exits 0 and the produced `registryData.json` deep-equals canonical | `execSync("node scripts/copy_registry.js")` + `expect(copied).toEqual(canonical)` |
| RB.7 | script and plugin both contain `existsSync` guard (partial-checkout safe) | source-grep asserts `"existsSync"` present in both files |
| RB.8 | `copyRegistryIfNeeded(src, dest)` — functional three-branch test (temp dirs, no real-FS side effects) | branch-1: copies + returns `"copied"`; branch-2: no-op + returns `"skipped"` + dest unchanged; branch-3: throws |
