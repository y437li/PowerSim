# `src/components/live`

<!-- curated -->
## Purpose

Live-dashboard panel components rendered by `routes/LiveDashboard.tsx` at the `/` route. Each component reads telemetry state from `stores/telemetryStore` and presents a focused view of one operational metric; none of them mutate store state or make network calls.

Current panels: `AlertList` (constraint-violation alerts derived by `utils/deriveAlerts`), `CostBreakdownCard` (per-step and cumulative cost breakdown), `MonthPeakCard` (monthly demand-peak tracker), `PowerFlowsTable` (real-time power flows across wind, solar, battery, grid, and load), `PriceTimeline` (electricity price over time with TOU band backgrounds per §3.7), and `SocTimeline` (battery state-of-charge trajectory with SOC bounds overlay).

This folder is strictly display-only. Store write operations, WebSocket handling, and physics semantics all live elsewhere.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `AlertList.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `AlertList` | `function` | — |

### `CostBreakdownCard.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `CostBreakdownCard` | `function` | — |

### `MonthPeakCard.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `MonthPeakCard` | `function` | — |

### `PowerFlowsTable.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `PowerFlowsTable` | `function` | — |

### `PriceTimeline.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `PriceTimeline` | `function` | — |

### `SocTimeline.tsx`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `SOC_LINE_COLOR` | `const` | — |
| `SOC_BOUNDS_COLOR` | `const` | — |
| `SOC_BAND_BG` | `const` | — |
| `SocTimeline` | `function` | — |

<!-- generated:end -->
