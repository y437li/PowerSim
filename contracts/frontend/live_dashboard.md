# Contract: Live Operations Dashboard

- **Status:** DRAFT — gate pending (frontend-reviewer)
- **Spec:** REBUILD_SPEC.md §3.4 (costs), §3.5 (reward), §3.7 (Gansu 4-tier TOU tariff), §5 (eval)
- **Owner:** dashboard-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend
- **Depends on DECISIONS:** D3 (Δt=1h), D4 (SOC 0.2–0.9), D5 (export 945 MW), D7 (spread clamp ≥0),
  D8 (minute-aware tariff boundaries), D10 (demand-charge per calendar month), D12 (import 400 MW),
  D13 (real-money vs reward-basis cost split)
- **Schema:** `contracts/shared/telemetry_schema.md` v1.0.0 (LOCKED, PR #6)
- **Golden fixtures:** `contracts/shared/telemetry_examples/env_step_a.json`,
  `contracts/shared/telemetry_examples/env_step_b.json`

## Purpose

Live operations dashboard at the `/` route (`SiteView`), alongside the 3D scene. Displays the
real-time state of the Gansu battery energy storage site from `env_step` telemetry:

- **(a) Cost breakdown** — per-step and cumulative real-money D13 components; `c_import`/`r_export`
  shown as a display-only decomposition of `c_energy` (never additional summands).
- **(b) SOC + price timelines** — SOC history with D4 bounds band; price history with static §3.7
  TOU bands drawn from the tariff schedule (NOT from the `tariff_tier` stream — see C1 below).
- **(c) Monthly peak tracker** — `month_peak_mw` and the ¥ demand-charge exposure it implies.
- **(d) Alerts** — curtailment, VOLL (unserved load), SOC violations, visible immediately with the
  ¥ penalty.
- **(e) Power-flows table** — current-step power flow edges in MW.

**Data source:** `telemetryStore` only. No REST client, no rogue WebSocket — the store is the
single source of truth, populated by the shell's `wsClient`.

**Fixture-driven development:** all components are testable against `env_step_a` and `env_step_b`
golden fixtures and synthetic stream stubs; no live backend required.

---

## C1 — Critical: TOU band geometry (§3.7, D8)

> This is the most important correctness invariant in this contract.

The `tariff_tier` field in `env_step` is the **price label for that specific step**, NOT band
geometry. At Δt=1 h (D3) all steps land on `:00`, so the critical-peak window (10:30–11:30)
never coincides with a step boundary. Reading band edges from the stream gives wrong geometry
(appears as 11:00–12:00 instead of 10:30–11:30).

**Rule:** TOU background bands are drawn from the static `TOU_SCHEDULE` constant (see §2 below),
never from `tariff_tier` alone. `tariff_tier` may be used to label the **current step's badge**
only.

---

## 1. TOU tariff schedule (static constant — §3.7)

```typescript
// src/utils/touSchedule.ts  — consumed by PriceTimeline background bands and getTouTier()
type TariffTier = "critical_peak" | "peak" | "mid" | "valley";

interface TouBand {
  fromMinutes: number;  // minutes-from-midnight (inclusive start)
  toMinutes: number;    // minutes-from-midnight (exclusive end)
  tier: TariffTier;
  priceYuanPerMwh: number;
}

// §3.7 Gansu 4-tier TOU — minute-accurate (D8)
// 10:30 = 630 min; 11:30 = 690 min; 19:00 = 1140 min; 21:00 = 1260 min; 23:00 = 1380 min
const TOU_SCHEDULE: TouBand[] = [
  { fromMinutes: 0,    toMinutes: 420,  tier: "valley",        priceYuanPerMwh: 250 },
  { fromMinutes: 420,  toMinutes: 480,  tier: "mid",           priceYuanPerMwh: 450 },
  { fromMinutes: 480,  toMinutes: 630,  tier: "peak",          priceYuanPerMwh: 620 },
  { fromMinutes: 630,  toMinutes: 690,  tier: "critical_peak", priceYuanPerMwh: 780 },
  { fromMinutes: 690,  toMinutes: 1080, tier: "mid",           priceYuanPerMwh: 450 },
  { fromMinutes: 1080, toMinutes: 1140, tier: "peak",          priceYuanPerMwh: 620 },
  { fromMinutes: 1140, toMinutes: 1260, tier: "critical_peak", priceYuanPerMwh: 780 },
  { fromMinutes: 1260, toMinutes: 1380, tier: "peak",          priceYuanPerMwh: 620 },
  { fromMinutes: 1380, toMinutes: 1440, tier: "valley",        priceYuanPerMwh: 250 },
];

/**
 * Return the tier for a given minute-of-day (0–1439).
 * Used by the price timeline to shade background bands; also verifiable in tests.
 * 10:30 → 630 min → critical_peak (NOT peak — the 10:00 step is "peak", 10:30 boundary is exact).
 */
function getTouTier(minuteOfDay: number): TariffTier;

/**
 * Return the static buy-price for a tier from the §3.7 table.
 * Used ONLY for background band reference labels — the actual live price comes from the wire.
 */
function getTouPrice(tier: TariffTier): number;
```

### TOU boundary verification (D8 — must be tested exactly)

| Minute-of-day | Time  | Expected tier   |
|---|---|---|
| 629           | 10:29 | `peak`          |
| 630           | 10:30 | `critical_peak` |
| 689           | 11:29 | `critical_peak` |
| 690           | 11:30 | `mid`           |
| 0             | 00:00 | `valley`        |
| 420           | 07:00 | `mid`           |
| 480           | 08:00 | `peak`          |
| 1079          | 17:59 | `mid`           |
| 1080          | 18:00 | `peak`          |
| 1139          | 18:59 | `peak`          |
| 1140          | 19:00 | `critical_peak` |
| 1259          | 20:59 | `critical_peak` |
| 1260          | 21:00 | `peak`          |
| 1379          | 22:59 | `peak`          |
| 1380          | 23:00 | `valley`        |
| 1439          | 23:59 | `valley`        |

---

## 2. Component interfaces

### 2.1 `LiveDashboard` (route component — mounts at `/`)

```typescript
// src/routes/SiteView.tsx — already exists; LiveDashboard is the dashboard panel within it
// src/components/live/LiveDashboard.tsx

export function LiveDashboard(): JSX.Element;
```

- Consumes `useTelemetryStore()` (no selector, for mock compatibility — same pattern as TrainingPanel).
- Renders: `StreamStatusBanner` (existing), `CostBreakdownCard`, `SocTimeline`, `PriceTimeline`,
  `MonthPeakCard`, `AlertList`, `PowerFlowsTable`.
- Empty state (no `envStep`): shows "Waiting for live data…" spinner (not disconnected) or blank
  (disconnected — `wsStatus === "disconnected"`). Same E11c pattern as TrainingPanel.
- All sub-components receive plain props extracted from the store state; they hold no store
  subscriptions of their own.

### 2.2 `CostBreakdownCard`

```typescript
// src/components/live/CostBreakdownCard.tsx

interface CostBreakdownCardProps {
  costs: PerStepCosts;       // current-step costs (env_step.costs)
  costCum: CumulativeCosts;  // episode cumulative costs (env_step.cost_cum)
}

export function CostBreakdownCard(props: CostBreakdownCardProps): JSX.Element;
```

**Display layout:**

```
Cumulative Cost: ¥-52,700   (cost_total_real_yuan_cum, headline)

Per-step breakdown (real money — §3.4 D13):
  Energy          ¥-53,100     (c_energy_yuan; can be negative = net revenue)
    ↳ Import      ¥0           (c_import_yuan — display-only sub-item)
    ↳ Export     −¥53,100      (r_export_yuan — display-only sub-item, shown as negative)
  Demand charge   ¥0           (c_demand_charge_yuan; real monthly booking)
  Degradation     ¥400         (c_degradation_yuan)
  Curtailment     ¥0           (c_curtail_yuan)
  VOLL            ¥0           (c_voll_yuan)
  ─────────────────────────
  Step total      ¥-52,700     (cost_total_real_yuan)
```

**Rules:**
- `c_import_yuan` and `r_export_yuan` are rendered as sub-rows under Energy with `data-role="decomposition"`.
  They are NEVER added to the total. A consumer test asserts the sum of the five real-money summands
  equals `cost_total_real_yuan` (not six including import/export).
- The demand-shaping term (`c_demand_shape_yuan`) and `penalty_yuan` are **not shown** in this card
  — they are reward-basis only.
- All ¥ values formatted via `formatYuan(v, 0)`.
- Negative `c_energy_yuan` (net revenue) renders with a green colour token; positive renders neutral.
- `data-testid="cost-breakdown-card"` on the root element.
- Each row uses `data-field="<fieldname>"` (e.g. `data-field="c_energy_yuan"`) for test selection.

### 2.3 `SocTimeline`

```typescript
// src/components/live/SocTimeline.tsx

interface SocTimelineProps {
  history: EnvStepPayload[];  // telemetryStore.history (ring buffer, chronological)
}

export function SocTimeline(props: SocTimelineProps): JSX.Element;
```

- Recharts `LineChart` (same library as MetricCurves — already in package.json).
- X-axis: `step` index (integer, from each history entry).
- Y-axis: SOC as **percent** (0–100), converted via `socToPercent()` from `units.ts`.
  Wire value is fraction [0.2, 0.9] — convert to [20, 90] for display.
- **D4 bounds band:** horizontal reference lines at 20% (lower bound) and 90% (upper bound).
  The band between them is shaded (Recharts `ReferenceArea` with low opacity).
  Labels: "Min 20%" and "Max 90%" at the reference lines.
- `data-testid="soc-timeline"`.
- Empty history → `data-testid="soc-timeline"` with `data-state="empty"` + "No data yet" text.
- Tooltip: `socToPercent(soc).toFixed(1) + " %"` on hover.

### 2.4 `PriceTimeline`

```typescript
// src/components/live/PriceTimeline.tsx

interface PriceTimelineProps {
  history: EnvStepPayload[];  // telemetryStore.history
}

export function PriceTimeline(props: PriceTimelineProps): JSX.Element;
```

- Recharts `ComposedChart` with `Line` (live price) + `ReferenceArea` bands (TOU background).
- X-axis: `step` index.
- Y-axis: `price_buy_yuan_per_mwh` (¥/MWh). Wire values, no conversion.
- **TOU background bands (C1):** drawn from `TOU_SCHEDULE` (static), NOT from `tariff_tier`.
  Each `TouBand` entry is rendered as a coloured `ReferenceArea` spanning the
  x-range that corresponds to that band's hour window.
  - Band geometry is computed in minutes-from-midnight using `sim_time_utc` from the first
    visible history entry; bands repeat every 24 h.
  - The critical-peak window (10:30–11:30) must span exactly 630–690 min-of-day, not 660–720.
- Live price line: `price_buy_yuan_per_mwh`, colour from `touColors.ts` keyed by the step's
  `tariff_tier` (wire value, fine for per-point colouring — only the background band edges need
  the static schedule).
- Accessible band list: hidden `<ul aria-label="TOU bands">` with each tier name (for tests
  that can't query SVG).
- `data-testid="price-timeline"`.
- Empty history → `data-testid="price-timeline"` with `data-state="empty"`.

### 2.5 `MonthPeakCard`

```typescript
// src/components/live/MonthPeakCard.tsx

interface MonthPeakCardProps {
  monthPeakMw: number;                  // env_step.month_peak_mw
  demandRateYuanPerMwMonth: number;     // env_step.costs.demand_rate_yuan_per_mw_month
}

export function MonthPeakCard(props: MonthPeakCardProps): JSX.Element;
```

**Display:**
```
Monthly Peak Demand
  Current peak:    95.0 MW
  Rate:            ¥32,000/MW·month
  Exposure:       ¥3,040,000       (= monthPeakMw × demandRateYuanPerMwMonth)
```

- Exposure computed as `monthPeakMw * demandRateYuanPerMwMonth` — no hardcoded 32,000; the
  rate comes from the wire field `demand_rate_yuan_per_mw_month` (D10).
- `data-testid="month-peak-card"`.
- `data-testid="month-peak-mw"` on the MW value, `data-testid="demand-exposure"` on the ¥ value.
- Peak in MW formatted via `formatPower()` (or plain `${v.toFixed(1)} MW` if `formatPower` changes
  the unit for small values — use `${monthPeakMw.toFixed(1)} MW` directly, since site-scale peak
  is always ≥1 MW and the wire unit is already MW).

### 2.6 `AlertList`

```typescript
// src/components/live/AlertList.tsx

interface AlertEvent {
  kind: "curtailment" | "voll" | "soc_violation";
  stepIndex: number;      // env_step.step
  penaltyYuan: number;    // cost relevant to this alert
  detail: string;         // e.g. "12.5 MW curtailed" or "5.0 MWh SOC overshoot"
}

interface AlertListProps {
  alerts: AlertEvent[];   // derived by LiveDashboard from history
}

export function AlertList(props: AlertListProps): JSX.Element;
```

**Alert derivation (in LiveDashboard, not AlertList):**

```typescript
// Curtailment: total curtailed MW for a step > 0
// curtailed = solar_curtailed_mw + wind_curtailed_mw + bat_curtailed_mw
// penalty = c_curtail_yuan (already in costs)

// VOLL: load unserved > 0
// penalty = c_voll_yuan

// SOC violation: soc_violation_mwh > 0
// penalty = penalty_yuan (D4 / §3.5)
```

- `data-testid="alert-list"`.
- Each alert row: `data-testid="alert-{kind}"` (e.g. `data-testid="alert-curtailment"`).
- When `alerts.length === 0`: renders `data-testid="alert-list"` with text "No alerts".
- Alert severity colour: curtailment → amber; VOLL → red; SOC violation → orange.
- ¥ penalty formatted via `formatYuan(v, 0)`.

### 2.7 `PowerFlowsTable`

```typescript
// src/components/live/PowerFlowsTable.tsx

interface PowerFlowsTableProps {
  flows: PowerFlows;         // env_step.flows
  generation: GenerationBlock; // env_step.generation
}

export function PowerFlowsTable(props: PowerFlowsTableProps): JSX.Element;
```

**Display columns:** Flow | MW

Rows (in this order):
1. Solar → Load
2. Solar → Battery
3. Solar → Grid
4. Wind → Load
5. Wind → Battery
6. Wind → Grid
7. Battery → Load
8. Battery → Grid
9. Grid → Load
10. Grid → Battery
11. Solar curtailed
12. Wind curtailed
13. Battery curtailed
14. Unserved load (VOLL)
15. Gross solar (generation block)
16. Gross wind (generation block)

- `data-testid="power-flows-table"`.
- Each row: `data-field="<snake_case_field>"` matching the wire field name
  (e.g. `data-field="solar_to_load_mw"`, `data-field="gross_solar_mw"`).
- All values formatted via `formatPower(mw)` — shows kW for sub-1 MW values.
- Non-zero flows highlighted (bold or accent colour); zero flows render in muted colour.

---

## 3. Store interface (consumed via telemetryStore)

This component reads the existing `TelemetryState` (contracts/frontend/app_shell.md §6.1):

```typescript
// fields consumed (from telemetryStore):
const { envStep, history, wsStatus } = useTelemetryStore();

// envStep: EnvStepPayload | null
// history: EnvStepPayload[]     — ring buffer, up to historyMaxLen (default 168)
// wsStatus: WsStatus
```

No new store fields needed. All dashboard state derives from these three.

---

## 4. Alert derivation logic

```typescript
// Derived in LiveDashboard — pure function, testable without React:
function deriveAlerts(history: EnvStepPayload[]): AlertEvent[] {
  const alerts: AlertEvent[] = [];
  for (const step of history) {
    const curtailed = step.flows.solar_curtailed_mw
                    + step.flows.wind_curtailed_mw
                    + step.flows.bat_curtailed_mw;
    if (curtailed > 0) {
      alerts.push({
        kind: "curtailment",
        stepIndex: step.step,
        penaltyYuan: step.costs.c_curtail_yuan,
        detail: `${curtailed.toFixed(1)} MW curtailed`,
      });
    }
    if (step.flows.load_unserved_mw > 0) {
      alerts.push({
        kind: "voll",
        stepIndex: step.step,
        penaltyYuan: step.costs.c_voll_yuan,
        detail: `${step.flows.load_unserved_mw.toFixed(1)} MW unserved`,
      });
    }
    if (step.battery.soc_violation_mwh > 0) {
      alerts.push({
        kind: "soc_violation",
        stepIndex: step.step,
        penaltyYuan: step.costs.penalty_yuan,
        detail: `${step.battery.soc_violation_mwh.toFixed(2)} MWh overshoot`,
      });
    }
  }
  return alerts;
}
```

---

## 5. Formatting rules (all via `src/utils/units.ts`)

| Quantity | Format | Example |
|---|---|---|
| ¥ costs / exposure | `formatYuan(v, 0)` | `¥-52,700` |
| ¥/MWh prices (live) | `formatYuanPerMwh(v)` | `¥620/MWh` |
| SOC (display) | `socToPercent(soc).toFixed(1) + " %"` | `55.0 %` |
| Power flows | `formatPower(mw)` (from units.ts) | `40.0 MW` or `850 kW` |
| Monthly peak | `${v.toFixed(1)} MW` directly (always ≥1 MW site-scale) | `95.0 MW` |

No inline unit conversion math. All conversions imported from `units.ts`.

---

## 6. Deliberate deviations / out-of-scope

- **TOU price timeline background bands** use the static `TOU_SCHEDULE` with minute-precise
  boundaries (10:30 = 630 min, 11:30 = 690 min). This is a **deviation from naively reading
  `tariff_tier`**: per C1 and D8, reading band edges from the hourly stream would misplace the
  critical-peak window by 30 minutes.
- **Demand-shape term (`c_demand_shape_yuan`)** and `penalty_yuan` are **not shown** in the cost
  breakdown card — they are reward-basis / safety metrics, not real money (D13).
- **`cost_total_reward_basis_yuan`** is not displayed — this is the RL reward signal, not the
  operations dashboard's business metric.
- **`assets_ext`** (gas/electrolyzer) is out of scope for this contract — Gansu parity config
  has no `assets_ext` block; feature-detect by key presence if extending later.
- **The 3D scene** is not touched — `LiveDashboard` renders in the dashboard panel only.
- **No history persistence** — only the in-memory `telemetryStore.history` ring buffer (168 steps);
  no localStorage or IndexedDB.

---

## 7. Test strategy

Tests in `tests/frontend/live_dashboard.test.tsx`:

1. **Golden-fixture validation** — full-envelope conformance against `env_step_a.json` and
   `env_step_b.json` (validate-telemetry skill requirement).
2. **TOU schedule** — `getTouTier()` boundary tests for all 16 boundary points in §1.
3. **`CostBreakdownCard`** — renders D13 summands correctly; `c_import`/`r_export` sub-rows
   present with `data-role="decomposition"`; step total matches `cost_total_real_yuan`;
   `c_demand_shape_yuan` and `penalty_yuan` absent from the display.
4. **`MonthPeakCard`** — exposure = `monthPeakMw × demandRateYuanPerMwMonth` (hand-computed:
   95 × 32,000 = ¥3,040,000); no hardcoded rate.
5. **`AlertList`** — empty → "No alerts"; curtailment/VOLL/SOC-violation alerts from fixture data.
6. **`deriveAlerts()`** — pure function; tested independently of React render.
7. **`SocTimeline`** — SOC displayed as percent (55 → "55.0 %"); D4 bounds reference lines present;
   empty state renders `data-state="empty"`.
8. **`PriceTimeline`** — accessible `<ul>` with all four tier names present; empty state.
9. **`PowerFlowsTable`** — all 16 flow rows present with correct `data-field` attributes; values
   from golden fixture A.
10. **`LiveDashboard`** — empty+connected → "Waiting" spinner; empty+disconnected → blank;
    with envStep → renders cost card + peak card.
