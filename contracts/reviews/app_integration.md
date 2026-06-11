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
