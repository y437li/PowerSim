# Contract: Frontend App Shell

- **Status:** ADDRESSING REVIEW — must-fix items resolved; PENDING_LOCK sections updated to telemetry_schema.md v1.0.0 LOCK (PR #6, 98beee0); awaiting VERDICT: APPROVE from frontend-reviewer
- **Spec:** REBUILD_SPEC.md §2 (MDP/obs), §3 (physics & costs), §3.7 (tariff/TOU), §5 (training/eval), telemetry schema `contracts/shared/telemetry_schema.md` (DRAFT — wire-format-dependent sections marked **⚠ PENDING TELEMETRY LOCK**)
- **Owner:** frontend-engineer · **Reviewer:** frontend-reviewer
- **Area:** frontend
- **Depends on DECISIONS:** D3 (Δt=1h, ep 168/8760), D4 (SOC 0.2–0.9), D5 (export 945 MW), D7 (spread clamp ≥0), D8 (minute-aware tariff)

## Purpose

React + Vite + TypeScript application shell that hosts the 3D scene (3d-assets-engineer) and the dashboard (dashboard-engineer). This contract covers:

1. **Project structure** — directory layout, tsconfig, Vite config, entry point
2. **Routing** — three top-level views with error boundaries
3. **Data layer** — typed WebSocket client (telemetry stream) + typed REST client; single source of truth
4. **Shared state** — Zustand stores that the 3D scene, dashboard, and training panel all read
5. **Component library** — shared primitives (formatting, colours, layout)
6. **3D scene mount point** — the `div` / props interface the 3d-assets-engineer plugs into

Nothing here implements the 3D scene, the chart library, or training controls — those live in other agents' contracts. This contract defines **the skeleton and the data plumbing only**.

---

## 1. Project structure

```
src/
  main.tsx              # React 18 createRoot, strict mode, BrowserRouter
  App.tsx               # Routes, Layout shell, top-level ErrorBoundary
  routes/
    SiteView.tsx        # Route "/" — 3D scene + live dashboard side-by-side
    TrainingPanel.tsx   # Route "/training" — training dashboard
    EvalComparison.tsx  # Route "/eval" — eval comparison table
  stores/
    telemetryStore.ts   # Zustand: live env_step state
    trainingStore.ts    # Zustand: train_metrics history
    evalStore.ts        # Zustand: eval_compare results
  clients/
    wsClient.ts         # WebSocket; demuxes by kind → stores
    restClient.ts       # fetch-based; typed request/response
  types/
    telemetry.ts        # TypeScript types from telemetry_schema.md ⚠ PENDING TELEMETRY LOCK
  components/
    Layout.tsx          # Top nav, sidebar skeleton, <Outlet />
    ErrorBoundary.tsx   # React ErrorBoundary wrapper
    SceneMountPoint.tsx # Container div for 3D scene; exposes ref + width/height
    Card.tsx            # Common card wrapper (border, padding, title slot)
    NumberDisplay.tsx   # Formatted numeric value + unit label
    TouBadge.tsx        # TOU tier colour chip
    TimeAxis.tsx        # Shared time-axis tick/label utility (not a full chart)
  utils/
    units.ts            # ALL unit conversions live here, nowhere else
    touColors.ts        # TOU tier → CSS colour token
index.html              # Vite entry; id="root"
vite.config.ts
tsconfig.json
tsconfig.node.json
package.json
```

No test files next to source — all tests live under `tests/frontend/`.

---

## 2. Routing

| Path | Component | Purpose |
|---|---|---|
| `/` | `SiteView` | 3D scene + live env_step dashboard |
| `/training` | `TrainingPanel` | Training curves, hyperparams, checkpoint list |
| `/eval` | `EvalComparison` | RL vs no-battery vs rule-based-TOU table |
| `*` | 404 inline | "Page not found" fallback |

- React Router v6 (`BrowserRouter` + `Routes` + `Route`).
- Each route is wrapped in its own `ErrorBoundary`; a route crash does not kill the nav bar.
- Lazy-loaded via `React.lazy` + `Suspense`; fallback is a centered spinner.

---

## 3. Type definitions (LOCKED — telemetry_schema.md v1.0.0, PR #6)

> These types are derived from `contracts/shared/telemetry_schema.md` v1.0.0 (LOCKED, PR #6, 98beee0). Implementations MUST use these exact field names and units. A field change here requires a new rl-architect DECISION and re-review.

### 3.1 Envelope

```typescript
type TelemetryKind = "env_step" | "train_metrics" | "eval_compare";

interface TelemetryEnvelope {
  schema_version: string;    // semver e.g. "1.0.0"
  kind: TelemetryKind;
  ts_utc: string;            // ISO-8601 UTC
  run_id: string;
  seq: number;               // monotonic per (run_id, kind)
  payload: EnvStepPayload | TrainMetricsPayload | EvalComparePayload;
}
```

### 3.2 EnvStepPayload (kind = "env_step")

```typescript
interface BatteryState {
  soc: number;               // fraction [0.2, 0.9] (D4) — display as soc*100 %
  p_charge_mw: number;       // MW ≥ 0
  p_discharge_mw: number;    // MW ≥ 0; charge XOR discharge
  p_max_charge_mw: number;   // §3.6 row 3 — carried so 3D can scale the battery wire
  p_max_discharge_mw: number;// §3.6 row 3
  soc_violation_mwh: number; // MWh ≥ 0
  capacity_mwh: number;      // MWh (294.5 Gansu)
}

interface GenerationBlock {
  gross_solar_mw: number;    // §3.1 P_pv before curtailment/dispatch; conservation: solar_to_*+solar_curtailed == gross_solar
  gross_wind_mw: number;     // §3.1 P_wind before curtailment/dispatch; conservation: wind_to_*+wind_curtailed == gross_wind
}

interface PowerFlows {
  solar_to_load_mw: number;
  solar_to_bat_mw: number;
  solar_to_grid_mw: number;
  wind_to_load_mw: number;
  wind_to_bat_mw: number;
  wind_to_grid_mw: number;
  bat_to_load_mw: number;
  bat_to_grid_mw: number;
  grid_to_load_mw: number;
  grid_to_bat_mw: number;
  solar_curtailed_mw: number; // §3.3 step 3 — per-source (was ren_curtailed_mw in DRAFT, split at LOCK)
  wind_curtailed_mw: number;  // §3.3 step 3
  bat_curtailed_mw: number;
  load_unserved_mw: number;
}

interface PccState {
  export_mw: number;         // MW
  import_mw: number;         // MW
  max_export_mw: number;     // MW (D5: 945 Gansu physics limit)
  max_import_mw: number;     // MW (D12: 400 Gansu)
}

type TariffTier = "critical_peak" | "peak" | "mid" | "valley";

interface PerStepCosts {
  // Real-money summands — additive identity: cost_total_real_yuan = c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
  c_energy_yuan: number;        // = c_import_yuan − r_export_yuan (§3.4); can be negative (net revenue)
  c_import_yuan: number;        // decomposition of c_energy — display-only, NOT an additional summand
  r_export_yuan: number;        // decomposition of c_energy — display-only, NOT an additional summand
  c_demand_charge_yuan: number; // REAL monthly charge; 0 except at month-boundary / terminal flush step (D10)
  c_degradation_yuan: number;
  c_curtail_yuan: number;
  c_voll_yuan: number;
  // Reward-shaping terms (NOT real money, excluded from cost_total_real_yuan)
  c_demand_shape_yuan: number;  // RAW C_DC_shape (§3.4); reward applies 2.0× weight, not stored pre-weighted
  penalty_yuan: number;         // SOC overshoot etc. (D4/§3.5); enters reward, NOT a cost summand
  // Rates (carried so dashboard needs no hardcoded constant)
  demand_rate_yuan_per_mw_month: number; // §3.7 = 32 000 ¥/MW·month
  // Two cost totals — see "Cost-accounting model" in telemetry_schema.md
  cost_total_real_yuan: number;         // real money only: c_energy+c_demand_charge+c_degradation+c_curtail+c_voll
  cost_total_reward_basis_yuan: number; // reward basis: c_energy+2.0·c_demand_shape+c_degradation+c_curtail+c_voll
}

interface CumulativeCosts {
  c_energy_yuan_cum: number;
  c_demand_charge_yuan_cum: number;
  c_demand_shape_yuan_cum: number;
  c_degradation_yuan_cum: number;
  c_curtail_yuan_cum: number;
  c_voll_yuan_cum: number;
  penalty_yuan_cum: number;
  cost_total_real_yuan_cum: number;
  cost_total_reward_basis_yuan_cum: number;
}

interface GasAsset { id: string; p_mw: number; c_fuel_yuan: number; setpoint: number; }
interface ElectrolyzerAsset {
  id: string; p_mw: number; h2_kg: number;
  h2_level_kg: number; tank_kg: number; r_h2_yuan: number; setpoint: number;
}
interface AssetsExt {
  gas?: GasAsset[];
  electrolyzer?: ElectrolyzerAsset[];
}

interface EnvStepPayload {
  step: number;
  episode: number;
  dt_hours: number;          // 1.0 (D3)
  sim_time_utc: string;
  hour_of_day: number;       // 0–23
  minute_of_hour: number;    // 0–59
  wind_speed_mps: number;
  irradiance_wm2: number;
  temperature_c: number;
  load_mw: number;           // MW
  price_buy_yuan_per_mwh: number;
  price_sell_yuan_per_mwh: number;
  tariff_tier: TariffTier;   // price label for this step only — NOT band geometry (draw TOU bands from static §3.7 schedule)
  battery: BatteryState;
  generation: GenerationBlock;
  flows: PowerFlows;
  pcc: PccState;
  costs: PerStepCosts;
  cost_cum: CumulativeCosts;
  month_peak_mw: number;     // MW
  reward: number;            // unitless, = −(cost_total_reward_basis_yuan + penalty_yuan)×1e-5 (§3.5)
  assets_ext?: AssetsExt;    // absent for Gansu parity; feature-detect by key presence
}
```

### 3.3 TrainMetricsPayload (kind = "train_metrics")

```typescript
interface TrainMetricsPayload {
  global_step: number;
  wall_seconds: number;
  env_steps_per_sec: number;
  actor_loss: number;
  critic_loss: number;
  ent_coef: number;
  reward_scaled_mean: number;           // batch mean of ×1e-5-scaled env reward (matches env_step.reward); unitless
  reward_norm_mean: number | null;      // VecNormalize-normalized reward seen by optimizer (§5 norm_reward=True);
                                        //   null on eval checkpoints (eval is unnormalized)
  cost_total_real_mean_yuan: number;    // mean per-episode REAL-money cost (negative = net revenue)
  is_eval_checkpoint: boolean;
  checkpoint_id: string | null;
}
```

### 3.4 EvalComparePayload (kind = "eval_compare")

```typescript
interface PolicyMetrics {
  // Real-money cost components — additive identity: total_cost_yuan = energy+demand_charge+degradation+curtailment+voll
  energy_cost_yuan: number;
  demand_charge_yuan: number;
  degradation_yuan: number;
  curtailment_yuan: number;
  voll_yuan: number;
  total_cost_yuan: number;       // real-money headline (excludes soc/penalty which are reward-shaping safety metrics)
  // Safety metrics — reported alongside but NOT included in total_cost_yuan
  soc_violations_count: number;  // integer count
  soc_violation_mwh: number;     // cumulative overshoot energy
  penalty_yuan: number;          // reward-basis penalty total (transparency; not real money)
}

interface EvalComparePayload {
  eval_horizon_steps: number;    // 8760 (D3)
  checkpoint_id: string;
  cost_basis: "real_money";      // explicit: all *_yuan fields are real money, not reward-basis
  policies: {
    rl: PolicyMetrics;
    no_battery: PolicyMetrics;
    rule_based_tou: PolicyMetrics;
  };
}
```

---

## 4. WebSocket client (`src/clients/wsClient.ts`)

```typescript
type WsStatus = "connecting" | "connected" | "disconnected" | "stale";

interface WsClientOptions {
  url: string;
  onEnvStep: (msg: TelemetryEnvelope & { payload: EnvStepPayload }) => void;
  onTrainMetrics: (msg: TelemetryEnvelope & { payload: TrainMetricsPayload }) => void;
  onEvalCompare: (msg: TelemetryEnvelope & { payload: EvalComparePayload }) => void;
  onStatusChange: (status: WsStatus) => void;
  bufferSize?: number;    // max env_step messages to buffer (default 1000)
  staleAfterMs?: number;  // mark stale if no message for this duration (default 10000)
  reconnectBaseMs?: number; // base reconnect delay (default 50)
  reconnectMaxMs?: number;  // cap reconnect delay (default 30000)
}

function createWsClient(opts: WsClientOptions): {
  connect(): void;
  disconnect(): void;
  getStatus(): WsStatus;
};
```

### 4.1 Connection lifecycle

1. `connect()` opens WebSocket to `opts.url`.
2. On `open` → status `"connected"`, reset backoff.
3. On `message` → parse JSON → validate `schema_version` major ≤ 1; dispatch by `kind`.
4. On `close` or `error` → status `"disconnected"` → schedule reconnect with exponential backoff: `delay = min(base * 2^attempt, max)`, jitter ±10%.
5. A stale-detection timer fires if no message is received for `staleAfterMs`: status → `"stale"` (stays open, still reconnects).
6. `disconnect()` cancels reconnect timers, closes socket cleanly.

### 4.2 Buffering

- `env_step` messages are appended to a ring buffer of size `bufferSize`.
- Oldest entries are dropped when the buffer is full (ring behaviour, not blocking).
- `train_metrics` and `eval_compare` are NOT buffered — latest replaces previous.

### 4.3 Error handling

- Invalid JSON → log warning, discard message, do not crash.
- Unknown `kind` → log warning, discard.
- `schema_version` major > 1 → emit status `"disconnected"`, stop parsing, surface error via `onStatusChange`.
- Missing required envelope fields → log warning, discard.

---

## 5. REST client (`src/clients/restClient.ts`)

```typescript
interface RunInfo {
  run_id: string;
  started_at: string;        // ISO-8601 UTC
  status: "running" | "completed" | "failed";
  checkpoint_count: number;
}

interface SiteConfig {
  site_id: string;
  wind_capacity_mw: number;
  solar_capacity_mw: number;
  battery_capacity_mwh: number;
  battery_max_charge_mw: number;
  battery_max_discharge_mw: number;
  pcc_max_export_mw: number;
  pcc_max_import_mw: number;
}

interface RestClientOptions {
  baseUrl: string;
  timeoutMs?: number;   // default 10000
}

interface RestClient {
  getRuns(): Promise<RunInfo[]>;
  getSiteConfig(siteId: string): Promise<SiteConfig>;
  getCheckpoint(checkpointId: string): Promise<{ checkpoint_id: string; url: string }>;
}

function createRestClient(opts: RestClientOptions): RestClient;
```

Error handling:
- Network failure → `Promise.reject(new Error("network_error: <message>"))`.
- 4xx → `Promise.reject(new Error("http_4xx: <status> <url>"))`.
- 5xx → `Promise.reject(new Error("http_5xx: <status> <url>"))`.
- Timeout → `Promise.reject(new Error("timeout: <url>"))`.

---

## 6. Shared state stores

### 6.1 Telemetry store (`src/stores/telemetryStore.ts`)

```typescript
interface TelemetryState {
  // Connection meta
  wsStatus: WsStatus;
  runId: string | null;
  lastSeq: number | null;
  seqGap: boolean;           // true when gap detected between consecutive seq values

  // Latest env_step values (null until first message)
  step: number | null;
  episode: number | null;
  simTimeUtc: string | null;
  // ... all EnvStepPayload fields mirrored as store state ...
  envStep: EnvStepPayload | null;   // full latest payload kept for 3D scene + dashboard

  // History ring buffer: last N steps for timeline charts
  history: EnvStepPayload[];
  historyMaxLen: number;     // default 168 (one training episode, D3)

  // Actions
  receiveEnvStep(msg: TelemetryEnvelope & { payload: EnvStepPayload }): void;
  // receiveEnvStep run_id change handling (§12.3, store-internal):
  //   When msg.run_id differs from the current non-null runId, the store
  //   MUST reset history, envStep, lastSeq, seqGap, step, episode, simTimeUtc
  //   (equivalent to clearHistory() followed by updating runId) BEFORE appending
  //   the new message. After reset, msg.seq is treated as the first seq (no gap).
  //   wsClient does NOT call clearHistory() explicitly — the store handles it.
  //
  // seqGap semantics:
  //   seqGap = true  iff seq > lastSeq + 1  (a forward gap, i.e. missed messages).
  //   Out-of-order or duplicate delivery (seq ≤ lastSeq) is silently accepted and
  //   does NOT set seqGap. The first message (lastSeq === null) never sets seqGap.
  setWsStatus(status: WsStatus): void;
  clearHistory(): void;
  // clearHistory also resets lastSeq to null and seqGap to false so that the
  // first message after a reconnect is never a false gap.
}
```

### 6.2 Training store (`src/stores/trainingStore.ts`)

```typescript
interface TrainingState {
  history: TrainMetricsPayload[];   // all received train_metrics, newest last
  latest: TrainMetricsPayload | null;
  receiveTrainMetrics(msg: TelemetryEnvelope & { payload: TrainMetricsPayload }): void;
  clear(): void;
}
```

### 6.3 Eval store (`src/stores/evalStore.ts`)

```typescript
interface EvalState {
  latest: EvalComparePayload | null;
  history: EvalComparePayload[];    // all evals for this run, ordered
  receiveEvalCompare(msg: TelemetryEnvelope & { payload: EvalComparePayload }): void;
  clear(): void;
}
```

---

## 7. Component library

### 7.1 `Card.tsx`

```typescript
interface CardProps {
  title?: string;
  className?: string;
  children: React.ReactNode;
}
// Renders: <div class="card [className]"><h3>{title}</h3><div>{children}</div></div>
```

### 7.2 `NumberDisplay.tsx`

```typescript
interface NumberDisplayProps {
  value: number | null;
  unit: string;
  decimals?: number;      // default 1
  className?: string;
  nullText?: string;      // shown when value === null; default "—"
}
// Renders: <span class="number-display"><span class="value">123.4</span><span class="unit"> MW</span></span>
// null value renders nullText, no unit suffix
```

### 7.3 `TouBadge.tsx`

```typescript
interface TouBadgeProps {
  tier: TariffTier | null;
  showPrice?: boolean;        // if true and priceYuanPerMwh is provided, appends the price
  priceYuanPerMwh?: number;  // fed from telemetryStore.envStep.price_buy_yuan_per_mwh;
                              //   formatted via formatYuanPerMwh() — never a hardcoded table
}
// Renders: <span class="tou-badge tou-{tier}">Peak</span>
//   — with showPrice=true and priceYuanPerMwh provided:
//   <span class="tou-badge tou-{tier}">Peak ¥620/MWh</span>
// tier === null → renders "—" with neutral style
// Price source is ALWAYS the wire value from telemetryStore; the component renders
// whatever is passed in and does no §3.7 table lookup.
```

### 7.4 `TimeAxis.tsx`

```typescript
interface TimeAxisProps {
  simTimeUtc: string | null;  // ISO-8601; renders formatted local sim clock
  step: number | null;
  dtHours: number;            // always 1.0 (D3)
  className?: string;
}
// Renders: <div class="time-axis"><span class="sim-time">Mon 08:00</span><span class="step">Step 168</span></div>
// null inputs render "—"
```

### 7.5 `SceneMountPoint.tsx`

```typescript
interface SceneMountPointProps {
  className?: string;
  onReady?: (el: HTMLDivElement) => void; // called once on mount with the container div
}
// Renders: <div class="scene-mount-point [className]" ref={...} />
// The 3d-assets-engineer attaches their R3F canvas to this div via the forwarded ref.
// This component owns NO 3D logic — it is a styled, measured container only.
// Width/height are 100% of parent; the 3D scene is responsible for its own canvas sizing.
```

---

## 8. Unit conversion utilities (`src/utils/units.ts`)

All unit conversions live **only** in this file. Other files import from here; no inline conversion math elsewhere.

```typescript
// SOC: fraction [0,1] → display percent
function socToPercent(soc: number): number;    // soc * 100, returns e.g. 55.0

// Power: MW ↔ kW  (display only — wire values are always MW)
function mwToKw(mw: number): number;           // mw * 1000
function kwToMw(kw: number): number;           // kw / 1000

// Money: ¥ formatting (wire values are ¥)
function formatYuan(yuan: number, decimals?: number): string;  // e.g. "¥53,100" or "¥-52,700"
function formatYuanPerMwh(yuanPerMwh: number): string;        // e.g. "¥620/MWh"

// Power formatting: picks MW or kW based on magnitude
function formatPower(mw: number): string;      // <1 MW → "850 kW"; ≥1 MW → "1.2 MW"

// Time: ISO-8601 UTC → display string for sim clock
function formatSimTime(isoUtc: string): string;
// Returns e.g. "Tue 08:00" — 3-letter day-of-week abbreviation (Mon/Tue/Wed/Thu/Fri/Sat/Sun)
// followed by HH:MM in 24-hour format.
// Implementation MUST use getUTCDay() / getUTCHours() / getUTCMinutes() — the sim clock
// is the UTC clock and must be rendered as-is regardless of the browser/CI runner timezone.
// A getHours()/getDay() implementation is incorrect.
```

No `Date.now()` or timezone conversions — `formatSimTime` displays the UTC sim clock as-is.

---

## 9. TOU tier colours (`src/utils/touColors.ts`)

```typescript
const TOU_COLORS: Record<TariffTier, { bg: string; text: string; border: string }> = {
  critical_peak: { bg: "#fee2e2", text: "#991b1b", border: "#f87171" },  // red
  peak:          { bg: "#fef3c7", text: "#92400e", border: "#fcd34d" },  // amber
  mid:           { bg: "#dbeafe", text: "#1e40af", border: "#93c5fd" },  // blue
  valley:        { bg: "#dcfce7", text: "#166534", border: "#86efac" },  // green
};

function getTouColor(tier: TariffTier): { bg: string; text: string; border: string };
function getTouCssVar(tier: TariffTier): string;  // returns "--tou-{tier}" CSS variable name
```

---

## 10. Layout and theming (`src/components/Layout.tsx`)

- Top navigation bar with three links: "Site View", "Training", "Eval".
- Active link highlighted via `NavLink` `isActive`.
- Connection status indicator (dot + label) reading from `telemetryStore.wsStatus`.
- `<Outlet />` renders the active route below the nav.
- No global CSS framework dependency — a single `src/style.css` with CSS custom properties for colours; TOU colours are CSS variables.

---

## 11. Error boundaries (`src/components/ErrorBoundary.tsx`)

```typescript
interface ErrorBoundaryProps {
  fallback?: React.ReactNode;  // default: "Something went wrong — reload to retry"
  children: React.ReactNode;
}
class ErrorBoundary extends React.Component<ErrorBoundaryProps, { hasError: boolean; error: Error | null }> {
  static getDerivedStateFromError(error: Error): { hasError: true; error: Error };
  componentDidCatch(error: Error, info: React.ErrorInfo): void;  // logs to console
  render(): React.ReactNode;
}
```

---

## 12. Edge cases and unhappy paths (testable commitments)

All of the following must be handled gracefully — no crashes, no silent data corruption:

1. **WS never connects:** stores have `null` payloads; all components render their `nullText` / "—" fallbacks.
2. **WS disconnects mid-stream:** `wsStatus` transitions `connected → disconnected`; reconnect backoff fires; history ring buffer is preserved.
3. **Reconnect with new `run_id`:** `telemetryStore.clearHistory()` is called; old run data is not merged.
4. **Sequence gap:** `seqGap = true` in store; dashboard can surface a warning.
5. **`env_step` with `assets_ext` absent:** all components that read `assets_ext` must feature-detect by key presence; no crash.
6. **`env_step` with all-zero flows:** valid; `NumberDisplay` renders `0.0 MW`, not `NaN` or blank.
7. **`NaN` / `Infinity` in numeric fields:** `NumberDisplay` must render `nullText` ("—"), not `NaN` / `Infinity`. A guard runs on all numeric props.
8. **Unknown `schema_version` major > 1:** wsClient stops parsing and emits `"disconnected"` status; stores are not corrupted.
9. **Unknown `kind` in envelope:** silently discarded; no store update.
10. **Empty eval history:** `EvalComparison` renders a "No eval run yet" placeholder.
11. **History buffer exactly full (168 items):** oldest item is dropped, not a crash.
12. **Route 404:** renders fallback, does not crash the nav bar.
13. **REST 5xx:** error propagated as rejected promise; caller responsible for display; client does not retry automatically.

---

## 13. Deliberate deviations

- **No 3D logic in the shell:** the shell provides only `SceneMountPoint`. The R3F canvas, scene graph, and asset loading live entirely in 3d-assets-engineer's code.
- **No chart library:** all charting is dashboard-engineer's domain; the shell provides `TimeAxis` as a utility only.
- **Wire-format types are now LOCKED:** TypeScript types match `telemetry_schema.md` v1.0.0 exactly. Implementations build against these.
- **TOU band geometry vs. per-step label:** `tariff_tier` in `env_step` is the price label for that step only — NOT band geometry. TOU timeline bands (e.g., "critical peak from 10:30–11:30") MUST be drawn from the static §3.7 tariff schedule, not reconstructed from the `tariff_tier` stream (C1 in telemetry schema). The shell's `TouBadge` and `TouColors` use `tariff_tier` for per-step labeling only; band geometry is dashboard-engineer's responsibility.

---

## 14. Out of scope

- 3D scene implementation (3d-assets-engineer owns that).
- Chart/tile implementations (dashboard-engineer owns those).
- Training controls (env-harness-engineer owns those).
- Authentication / multi-user sessions.
- Server-side rendering.
- §8 gas/electrolyzer UI — `assets_ext` types defined here; rendering is out of scope for the shell.
