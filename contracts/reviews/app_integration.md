# Review Record: App Integration Wiring (contract + tests gate)

- **Contract:** `contracts/frontend/app_integration.md`
- **Tests:** `tests/frontend/app_integration.test.tsx`
- **PR:** #45 (`feat/frontend-app-integration`, draft) · task #22
- **Reviewer:** frontend-reviewer · **Stage:** 1 (contract + test-cases gate)
- **Date:** 2026-06-11
- **Verdict:** **REQUEST_CHANGES** (2 blockers + test-coverage gaps)

## Blockers

1. **WS endpoint mismatch — recreates the empty-render.** §2 singleton uses one socket at
   `url: '/ws'` wiring both `onEnvStep` + `onTrainMetrics`. Serving exposes two endpoints with
   different kinds: `WS /ws/inference` (env_step + status, `contracts/serving/inference_stream.md:24`)
   and `WS /ws/training/stream` (train_metrics, `contracts/serving/training_proxy.md:9`).
   `wsClient.ts` does `new WebSocket(url)` (no path append) → `/ws` connects to a non-existent
   endpoint → stores still get no data. Contradicts the locked serving contracts. Fix: two clients
   (telemetry → `/ws/inference`, training → `/ws/training/stream`), or a serving-contract change for
   a unified `/ws` (escalate; do not assume).

2. **Wrong Gansu nameplates (displayed-data) + wrong citation.** §5 contradicts §1 authoritative
   totals (`section_01_overview.md:12`: Wind **615**, Solar 330, Battery **294.5 MWh / 98.16 MW**)
   and cites "D4" (SOC bounds, not nameplate): `wind_capacity_mw 400`→615 (400 = import limit, D12);
   `battery.capacity_mwh 300`→294.5; `max_charge/discharge_mw 60`→98.16; solar 330 ✓. Feeds
   SiteScene `site_max_mw` flow-line normalization → mis-scaled scene.

## Test-coverage gaps (must close — gate's job)

- §T8 asserts `> 0` only → all four wrong nameplates pass. Pin exact §1 values (615/330/294.5/98.16).
- No test exercises the **real** `wsClientSingleton` handler wiring (mocked everywhere) → the literal
  "stores get no data" fix is untested. Add: env_step→`receiveEnvStep`, train_metrics→
  `receiveTrainMetrics`, status→`setWsStatus`; and pin the socket URL(s) to the serving endpoints.
- StrictMode double-mount: §T3/§T4 "exactly once" hold only without `StrictMode`; note idempotent
  connect + cleanup disconnect self-heals, or test it.

## Good (no change)

- §4/§6: SiteScene via `SceneMountPoint.onReady` + LiveDashboard within SiteView + no new route —
  matches `live_dashboard.md` §2.1. §T9 deep-equals registry.json; §T8 assetId↔registry cross-checks.
- Confirmed `TrainingPanel` reads `wsStatus` from `telemetryStore` (`TrainingPanel.tsx:33`), so the
  single `onStatusChange → telemetryStore.setWsStatus` wiring serves both panels — correct.
- eval_compare no-op documented and acceptable (no v1 consumer).

Re-request when both blockers land; reviewer edge tests (exact nameplates, real handler wiring) to be
added/verified on re-review.

---

## Round 2 @ commit `5349b2e` — **APPROVE**

Both blockers + all coverage gaps resolved (verified against the diff):

1. **WS endpoint mismatch — resolved.** §2 now defines TWO clients: `telemetryWsClient` →
   `TELEMETRY_WS_URL = '/ws/inference'` (env_step + status) and `trainingWsClient` →
   `TRAINING_WS_URL = '/ws/training/stream'` (train_metrics) — matching the serving contracts
   (inference_stream.md:24, training_proxy.md:98). App connects/disconnects both (§3). §T_url
   pins both URLs via `vi.importActual` on the real module — would have caught the original bug.
2. **Gansu nameplates — resolved.** §5 corrected to §1 authoritative values (wind 615, solar 330,
   battery 294.5 MWh / 98.16 MW) with proper §1 citation + explicit "400 = import limit D12" note.
   §T8 pins exact values (`=== 615 / 330 / 294.5 / 98.16`), not `> 0`.
3. **Handler-wiring coverage — resolved.** §T_wire uses `vi.importActual` to get the REAL
   `handleEnvStep`/`handleTrainMetrics`/`handleStatusChange`, feeds golden fixtures
   (`env_step_a.json`, `train_metrics.json` — both present), and asserts the REAL Zustand stores
   update (`telemetryStore.envStep.step`, `trainingStore.latest.global_step`, `setWsStatus`). This
   directly tests the "stores get no data" fix that was previously untested.
4. **StrictMode** documented in §3/§T4 (idempotent connect + cleanup self-heals).
5. Confirmed (no change): single `handleStatusChange → telemetryStore.setWsStatus` is correct since
   `TrainingPanel` reads `wsStatus` from `telemetryStore`; eval_compare no-ops documented.

### Reviewer test added (this commit)
- **`reviewer: §T1 /api proxy rewrite`** — §T1 pinned target/changeOrigin/ws but not the rewrite;
  a wrong rewrite silently 404s every REST call. Pins the §1 rule: `/api/sites`→`/sites`,
  `/api`→`/`, `/api/`→`/`, and `/ws` has no rewrite.

### Approved suite
Developer cases (§T1–§T9, §T_url, §T_wire) + my reviewer `/api`-rewrite group. Locked stage-1 spec;
tests are RED (stubs/no real impl yet) and go green under QA after the implementation replaces the
stubs at stage 2.

**Verdict: APPROVE** (contract+tests gate). Cleared for implementation. Mark ready when the real
`viteProxy.ts` / `wsClientSingleton.ts` / `gansuSiteConfig.ts` / `App.tsx` / `SiteView.tsx` land,
and I run the stage-2 audit.
