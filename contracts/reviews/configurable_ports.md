# Review Record: Configurable Dev Ports (contract + tests gate)

- **Contract:** `contracts/frontend/configurable_ports.md`
- **Tests:** `tests/frontend/configurable_ports.test.tsx`
- **PR:** #55 (`feat/frontend-configurable-ports`, draft) · task #31
- **Reviewer:** frontend-reviewer · **Stage:** 1 (contract + test-cases gate)
- **Date:** 2026-06-11 · **Verdict:** **APPROVE** (1 reviewer test pushed)

## What is good (verified)
- **Backward-compat is sound.** `VITE_PROXY_CONFIG` stays a module-level const (`= buildViteProxy()`)
  → existing `app_integration` §T1 tests (target `:8000`, changeOrigin, ws) still pass when env is
  unset (CP.12). `playwright.config.ts` derives `baseURL`/`webServer.url` from
  `ENERGY_GO_FRONTEND_PORT ?? 5173` → the existing `playwright_harness` `baseURL === :5173`
  assertion still passes with env clean.
- **Env read at call time** (not module-load) for `buildViteProxy()` — correct for testability and
  for picking up the env at Vite startup. Defaults: backend 8000, frontend 5173.
- **`/api` and `/ws` both read the same backend port** (§2.3) → REST + the two WS endpoints
  (`/ws/inference`, `/ws/training/stream`, PR #45) stay in sync on a custom port. The `/api`
  rewrite is unchanged (CP.10/11).
- **Serving coordination (§6)** correctly framed as a cross-area handoff: same `ENERGY_GO_BACKEND_PORT`
  for uvicorn bind; serving-engineer updates the backend launch script (not in this frontend PR).
- Test env isolation (save/restore `ENERGY_GO_BACKEND_PORT`, afterEach) is correct.

## Reviewer test pushed (this commit)
- **CP.13 — explicit arg precedence over a SET env var.** CP.3/4 pass an explicit port with env
  unset, so they don't prove §2.1's "explicit wins". CP.13: `env='9001'` + `buildViteProxy(8801)`
  → `:8801`. Catches an env-first impl that would otherwise pass all 12 CP tests.

## Notes (non-blocking)
- §1 punts on non-numeric/out-of-range values ("undefined behavior, operator responsibility").
  Acceptable for a dev-only convenience var, but note `?? "5173"` only catches *unset*, not empty
  string (`""` → `parseInt` NaN → broken proxy/port silently). A `Number.isInteger` guard with
  fallback would be more robust if revisited; not required for v1.

## Approved suite
Developer CP.1–12 + my CP.13. Cleared for implementation (the `buildViteProxy` export, vite/
playwright config wiring, and deleting `vite.demo.config.mts`). Mark ready for stage-2.

**Verdict: APPROVE** (stage-1 gate).

---

## Stage-2 implementation audit — PR #55 @ `3b5a50e` — **APPROVE**

- **Reviewer:** frontend-reviewer · **Date:** 2026-06-11 · No findings.

- **`buildViteProxy` precedence/defaults correct** — `backendPort ?? parseInt(process.env.
  ENERGY_GO_BACKEND_PORT ?? "8000", 10)`: explicit arg wins (and `??` not `||`, so a valid
  falsy value is honoured), env read at call time, default 8000. My CP.13 precedence test passes.
  `/api` + `/ws` both target the same `port`; rewrite unchanged.
- **Backward-compat preserved** — `VITE_PROXY_CONFIG = buildViteProxy()` module const → §T1 still
  passes when env unset. `vite.config.ts` `server.port` from `ENERGY_GO_FRONTEND_PORT ?? "5173"`;
  `playwright.config.ts` derives `frontendUrl` for `baseURL` + `webServer.url` → playwright_harness
  `:5173` assertion still passes. 743/743.
- **`vite.demo.config.mts` deleted** (§5).
- §6 serving handoff (uvicorn `--port ENERGY_GO_BACKEND_PORT`) tracked as task #32.

**Verdict: APPROVE** (stage-2). Mergeable on this + QA_PASS.
