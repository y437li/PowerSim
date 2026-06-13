# Contract: `stage_config` — Wizard Stage ① Site Configuration

**Area:** `frontend`
**Feature file:** `contracts/frontend/stage_config.md`
**Branch:** `feat/frontend-stage-config`
**Task:** #2
**Status:** DRAFT — awaiting frontend-reviewer approval
**Inputs:**
- `docs/design/ux/stage_1_config.md` v0.1 — per-screen layout reference
- `docs/design/ux/wizard_flow.md` v0.6 — stage state machine, edit-class rules
- `contracts/serving/geo_site_api.md` v1.0.0 — REST endpoints consumed here
- `contracts/frontend/design_system.md` — design tokens (merged #98)
- `contracts/shared/device_model_schema.md` v2.0.0 (LOCKED)
- `contracts/shared/config_validation.md` v1.0.0 (LOCKED)

---

## 1. Purpose and scope

This contract specifies the frontend for Wizard Stage ① (Site Configuration): the form that
lets operators compose a site — geographic location, device fleet, weather source, tariff
region, and scenario type — before proceeding to Stage ② Algorithm.

**What this contract covers:**
- `StageOneConfig` — root page component
- `MapPicker` — map tile view + lat/lon inputs + weather-mode selector + coverage indicator
- `DeviceFleetTable` — device fleet table with autocomplete add, remove, and count edit
- `ScenarioComposer` — scenario composition panel (v1: single base scenario always active)
- `ValidationPanel` — errors/warnings/acknowledge panel
- `StageSaveButton` — footer "Save & Continue" button with loading state
- `useSiteMetaForm` — hook managing site name, province, tariff selection
- `useStageOneStore` — Zustand slice for Stage ① persistent state
- API consumption rules (debounce, error handling) for the geo_site_api endpoints used here

**Out of scope for this contract (pending future contracts):**
- `WizardBar` stepper — `contracts/frontend/wizard_shell.md` (future)
- `StageShell` wrapper — `contracts/frontend/wizard_shell.md` (future)
- `AddToComparisonModal` — separate contract
- `ProvenanceBadge` — part of wizard_shell contract
- Save & Continue persistence (`POST /api/site/config`) — `site_config_persistence.md` (future)
- Site totals strip (`GET /api/site/resolve`) — `site_resolve.md` (future)
- Historical weather fetch job flow (`POST /api/site/weather/fetch`, polling) — future contract
- Finance Stage ⑤ assumptions panel — future contract

**Design authority:** `docs/design/ux/stage_1_config.md` governs layout; this contract governs
the TypeScript API (props, state shape, hook contracts) and behavioral invariants.

---

## 2. Stage state machine

Stage ① follows the five-state model from `wizard_flow.md §2.2`. The state is stored in
`useStageOneStore` (Zustand, `localStorage`-persisted).

```
FIRST_VISIT   — no saved config; all fields empty; Continue disabled
IN_PROGRESS   — fields partially filled; validation may show errors/warnings
VALIDATING    — debounced server call in flight (300 ms debounce on changes)
COMPLETE      — all hard errors resolved, all soft warnings acknowledged; Continue enabled
STALE         — was COMPLETE, user returned and edited something; Continue shows "Save & Update →"
```

**Transition triggers:**

| From | Trigger | To |
|------|---------|-----|
| `FIRST_VISIT` | Any field edit | `IN_PROGRESS` |
| `IN_PROGRESS` | Debounce fires (300 ms) | `VALIDATING` |
| `VALIDATING` | API returns 0 errors + 0 unack'd warnings | `COMPLETE` |
| `VALIDATING` | API returns ≥ 1 error OR ≥ 1 unack'd warning | `IN_PROGRESS` |
| `COMPLETE` | Any field edit | `STALE` |
| `STALE` | Debounce fires → API returns 0 errors + 0 unack'd warnings | `COMPLETE` |
| `STALE` | Debounce fires → API returns errors/warnings | `IN_PROGRESS` |

**Invariant:** `Continue` button is enabled iff `stageState === 'COMPLETE'` (no exception).

---

## 3. TypeScript types

### 3.1 Stage state

```typescript
// src/types/stageConfig.ts

export type StageOneState =
  | 'FIRST_VISIT'
  | 'IN_PROGRESS'
  | 'VALIDATING'
  | 'COMPLETE'
  | 'STALE';

export type WeatherMode = 'synthetic' | 'historical' | 'bootstrap';

export interface LatLon {
  lat: number;   // decimal degrees N; positive = north
  lon: number;   // decimal degrees E; positive = east
}

export interface DeviceRow {
  id:       string;   // model_id from device_models.yaml
  count:    number;   // ≥ 1
  // Read-only fields resolved from GET /api/devices/models/{id}
  type?:    'wind_turbine' | 'pv_panel' | 'battery' | 'grid_connection';
  label?:   string;   // human label from search response
  valid?:   boolean;  // true = id resolved in library; false = not found; undefined = resolving
}

export interface ValidationIssue {
  rule_id:    string;
  field:      string;
  message:    string;
  constraint: string;
}

export interface ValidationResult {
  errors:   ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface WeatherCoverage {
  historical_available: boolean;
  available_year_count: number;
  year_range:           [number, number] | null;
  bootstrap_available:  boolean;
}
```

### 3.2 `useStageOneStore` — Zustand state shape

```typescript
// src/stores/stageOneStore.ts

export interface StageOneStoreState {
  // Stage machine
  stageState: StageOneState;

  // Form values
  siteName:     string;        // max 64 chars; optional
  province:     string;        // "" = not selected
  tariffRegion: string;        // region_id; "" = not selected; tracks province default unless overridden
  tariffManuallyOverridden: boolean;  // true = user explicitly chose tariff, province change shows [↺ Reset]

  location:    LatLon | null;
  weatherMode: WeatherMode;

  fleet:       DeviceRow[];    // ordered list; may be empty

  scenarioBasePowerActive: boolean;  // v1: always true; immutable

  // Validation cache
  lastValidation: ValidationResult | null;
  acknowledgedWarnings: string[];   // rule_id values that have been acknowledged

  // API call tracking
  validationPending: boolean;
  coveragePending:   boolean;
  coverageResult:    WeatherCoverage | null;
  coverageError:     string | null;

  // Save state (§9 footer)
  saveInProgress: boolean;
  saveError:      string | null;
}

export interface StageOneStoreActions {
  setSiteName(name: string): void;
  setProvince(province: string): void;
  setTariffRegion(regionId: string, isManualOverride: boolean): void;
  resetTariffToProvinceDefault(): void;
  setLocation(loc: LatLon | null): void;
  setWeatherMode(mode: WeatherMode): void;

  addDevice(row: DeviceRow): void;
  updateDeviceCount(index: number, count: number): void;
  removeDevice(index: number): void;
  resolveDevice(index: number, resolved: Pick<DeviceRow, 'type' | 'label' | 'valid'>): void;

  acknowledgeWarning(ruleId: string): void;
  receiveValidation(result: ValidationResult): void;
  setValidationPending(pending: boolean): void;
  receiveCoverage(result: WeatherCoverage): void;
  setCoverageError(msg: string | null): void;

  setSaveInProgress(v: boolean): void;
  setSaveError(msg: string | null): void;
  onSaveSuccess(configHash: string): void;   // transitions to COMPLETE, updates provenanceHash

  reset(): void;   // resets to FIRST_VISIT; used when wizard is mounted fresh
}
```

**Persistence:** `useStageOneStore` uses Zustand's `persist` middleware with `localStorage`
key `"energygo.stage1"`. On page reload the form values and `stageState` are restored.
`validationPending`, `saveInProgress`, `saveError`, `coveragePending` are NOT persisted
(they are reset to their zero values on rehydrate).

---

## 4. Component contracts

### 4.1 `StageOneConfig`

**File:** `src/components/wizard/StageOneConfig.tsx`

**Responsibilities:**
- Mount and coordinate all Stage ① sub-components.
- Read `useStageOneStore` for all state; write via store actions.
- Wire `ValidationPanel` to `lastValidation` + `acknowledgedWarnings` + `acknowledgeWarning`.
- Manage the 300 ms validation debounce: fire `POST /api/site/validate` after any meaningful change
  (fleet change, lat/lon change, tariff change, scenario toggle). See §5.1.
- Manage the 500 ms coverage debounce: fire `GET /api/site/weather-coverage` after lat/lon change.

**Props:**
```typescript
interface StageOneConfigProps {
  // Navigation callbacks — provided by WizardShell (future contract)
  onContinue?: () => void;       // called after successful save; navigates to Stage ②
  onAddToComparison?: () => void; // called when [+ Add to Comparison] footer action fires
  // Injected for testing — default undefined (tests provide them via mocked fetch)
  testId?: string;
}
```

**DOM structure:**
```
<div data-testid="stage-one-config">
  <div class="stage-one-layout">
    <div class="stage-one-left">
      <MapPicker … />
    </div>
    <div class="stage-one-right">
      <SiteMetaSection … />     {/* site name / province / tariff */}
      <DeviceFleetTable … />
      <ScenarioComposer … />
      <ValidationPanel … />
    </div>
  </div>
  <StageOneFooter …>            {/* footer with Back / Add to Comparison / Continue */}
    <StageSaveButton … />
  </StageOneFooter>
</div>
```

**Test id anchors** (required for RTL queries; must be stable, no index suffixes):
- `data-testid="stage-one-config"` on root div
- `data-testid="stage-one-left"`, `data-testid="stage-one-right"`
- `data-testid="stage-one-footer"`

---

### 4.2 `MapPicker`

**File:** `src/components/wizard/MapPicker.tsx`

**Props:**
```typescript
interface MapPickerProps {
  latLon:           LatLon | null;
  weatherMode:      WeatherMode;
  coverage:         WeatherCoverage | null;
  coveragePending:  boolean;
  coverageError:    string | null;
  onLatLonChange:   (loc: LatLon) => void;
  onWeatherModeChange: (mode: WeatherMode) => void;
  testId?:          string;   // default "map-picker"
}
```

**Behavioral invariants:**
- `[T-MAP-1]` When `latLon` is null, Lat/Lon text inputs are empty; map is centred on China (35°N 105°E, zoom 4).
- `[T-MAP-2]` When `latLon` is set, map flies to those coordinates at zoom 9.
- `[T-MAP-3]` Typing a valid decimal in the Lat field calls `onLatLonChange` with the parsed value and the current Lon (and vice versa). Parse fires on blur or Enter.
- `[T-MAP-4]` When MapLibre tiles fail to load, the component renders a fallback div `data-testid="map-tile-error"` with text "Map tiles unavailable — enter coordinates manually." Lat/Lon text inputs remain enabled.
- `[T-MAP-5]` `[📍 Use my location]` button (`data-testid="use-my-location"`) calls `navigator.geolocation.getCurrentPosition`. On success: calls `onLatLonChange`. On failure/denial: renders a toast `data-testid="location-toast"` with text "Location unavailable" (auto-dismisses after 4 s). No state change on failure.
- `[T-MAP-6]` Historical radio button is **disabled** when `coverage?.historical_available === false` OR when `coveragePending === true`.
- `[T-MAP-7]` Bootstrap radio button is **disabled** when `coverage?.bootstrap_available === false` OR when `coveragePending === true`.
- `[T-MAP-8]` When `coveragePending` is true, radio labels for Historical/Bootstrap show a spinner (`data-testid="coverage-spinner"`).
- `[T-MAP-9]` Lat/Lon fields accept `N`/`S`/`E`/`W` suffix (case-insensitive). "38S" → lat = -38; "102W" → lon = -102. Positive decimals are also valid.
- `[T-MAP-10]` Lat input is restricted to [-90, 90]; Lon to [-180, 180]. Values outside range show inline error `data-testid="lat-range-error"` / `data-testid="lon-range-error"` and do NOT call `onLatLonChange`.

**DOM anchors:**
- `data-testid="map-picker"` (or prop `testId`) on root
- `data-testid="lat-input"`, `data-testid="lon-input"`
- `data-testid="weather-mode-synthetic"`, `data-testid="weather-mode-historical"`, `data-testid="weather-mode-bootstrap"`
- `data-testid="coverage-indicator"` on the availability line block

---

### 4.3 `DeviceFleetTable`

**File:** `src/components/wizard/DeviceFleetTable.tsx`

**Props:**
```typescript
interface DeviceFleetTableProps {
  fleet:         DeviceRow[];
  onAdd:         (row: DeviceRow) => void;
  onRemove:      (index: number) => void;
  onCountChange: (index: number, count: number) => void;
  testId?:       string;   // default "device-fleet-table"
}
```

**Behavioral invariants:**
- `[T-FLEET-1]` When `fleet` is empty, renders `data-testid="fleet-empty-state"` with text "No devices added yet." and a primary-style `[+ Add device]` button (`data-testid="fleet-add-btn"`).
- `[T-FLEET-2]` `[+ Add device]` opens an inline add-row form with `data-testid="fleet-add-form"`: device ID autocomplete input (`data-testid="fleet-add-id"`) and count input (`data-testid="fleet-add-count"`, default 1), plus `[Add ✓]` (`data-testid="fleet-add-confirm"`) and `[Cancel ✕]` (`data-testid="fleet-add-cancel"`) buttons.
- `[T-FLEET-3]` Typing in `fleet-add-id` fires `GET /api/devices/search?q=<value>` (debounced 200 ms). Results populate a dropdown (`data-testid="fleet-add-dropdown"`).
- `[T-FLEET-4]` Each result entry in the dropdown shows `model_id` and `label` from the API.
- `[T-FLEET-5]` `[Add ✓]` is **disabled** while the device ID is empty, the search is in flight, or the search returned no result for the typed ID.
- `[T-FLEET-6]` When `[Add ✓]` is clicked and the API returned a valid match: calls `onAdd` with `{ id, count, type, label, valid: true }`.
- `[T-FLEET-7]` When a typed ID has no match in the search results: inline error in the ID cell: `data-testid="fleet-id-error"` with text `'"{id}" not found in device library'`.
- `[T-FLEET-8]` Each device row (`data-testid="fleet-row-{index}"`) renders: Device ID (text), type icon, count input (`data-testid="fleet-row-count-{index}"`), remove button (`data-testid="fleet-row-remove-{index}"`).
- `[T-FLEET-9]` Count input: min=1, max=999. Values outside this range are clamped on blur; no call to `onCountChange` with out-of-range values.
- `[T-FLEET-10]` `[✕]` remove button calls `onRemove(index)` immediately.
- `[T-FLEET-11]` The site totals strip (`data-testid="fleet-totals"`) is rendered even when the fleet is empty, showing `—` for all values until `GET /api/site/resolve` is available. (Note: `GET /api/site/resolve` is out of scope for this contract — the strip renders the placeholder until the `site_resolve.md` contract is implemented.)

**DOM anchors:**
- `data-testid="device-fleet-table"` (or prop `testId`) on root

---

### 4.4 `ScenarioComposer`

**File:** `src/components/wizard/ScenarioComposer.tsx`

**Props:**
```typescript
interface ScenarioComposerProps {
  scenarioBasePowerActive: boolean;   // v1: always true; immutable
  testId?: string;   // default "scenario-composer"
}
```

**Behavioral invariants:**
- `[T-SCENARIO-1]` Renders the "Power supply" base scenario as always-checked, non-interactive (`data-testid="scenario-base-power"` with `aria-checked="true"` and `aria-disabled="true"`).
- `[T-SCENARIO-2]` No other scenario rows are rendered in v1.
- `[T-SCENARIO-3]` The base scenario label reads "Power supply" with a sub-label `"[base — always active]"`.

---

### 4.5 `ValidationPanel`

**File:** `src/components/wizard/ValidationPanel.tsx`

**Props:**
```typescript
interface ValidationPanelProps {
  result:                ValidationResult | null;
  pending:               boolean;
  acknowledgedWarnings:  string[];    // rule_id values already acknowledged
  onAcknowledge:         (ruleId: string) => void;
  apiError:              string | null;   // non-null when POST /api/site/validate failed
  onRetry:               () => void;
  testId?:               string;   // default "validation-panel"
}
```

**Behavioral invariants:**
- `[T-VAL-1]` When `pending` is true, renders `data-testid="validation-loading"` with text containing "Checking...".
- `[T-VAL-2]` When `result` has one or more `errors`, each is rendered as `data-testid="validation-error-{rule_id}"` with the `message` text. Error items have `role="alert"`.
- `[T-VAL-3]` When `result` has one or more `warnings` not in `acknowledgedWarnings`, each is rendered as `data-testid="validation-warning-{rule_id}"` with an `[Acknowledge ✓]` button (`data-testid="validation-ack-{rule_id}"`).
- `[T-VAL-4]` Clicking `[Acknowledge ✓]` calls `onAcknowledge(ruleId)`.
- `[T-VAL-5]` Warnings whose `rule_id` is in `acknowledgedWarnings` render in a faint struck-through style with `data-testid="validation-acked-{rule_id}"` and NO Acknowledge button.
- `[T-VAL-6]` When `result` has zero errors AND zero unacknowledged warnings AND `pending` is false: renders `data-testid="validation-clean"` with text "✓ Configuration valid".
- `[T-VAL-7]` When `apiError` is non-null: renders `data-testid="validation-api-error"` with text "⚠ Validation unavailable — check connection" and a `[↺ Retry]` button (`data-testid="validation-retry"`). Clicking Retry calls `onRetry()`.
- `[T-VAL-8]` When `pending` is true for longer than 2 000 ms, renders an additional `data-testid="validation-still-checking"` element with text "Still checking…" alongside the spinner.
- `[T-VAL-9]` When an acknowledged warning's associated field changes (e.g., lat/lon changes after acknowledging a coverage warning), `acknowledgedWarnings` is cleared for that `rule_id`. **Note:** this clearing is the responsibility of `StageOneConfig` / `useStageOneStore` — `ValidationPanel` is presentational only and never clears `acknowledgedWarnings` itself.

---

### 4.6 `StageSaveButton`

**File:** `src/components/wizard/StageSaveButton.tsx`

**Props:**
```typescript
interface StageSaveButtonProps {
  stageState:     StageOneState;
  saveInProgress: boolean;
  onClick:        () => void;
  testId?:        string;   // default "stage-save-btn"
}
```

**Behavioral invariants:**
- `[T-SAVE-1]` When `stageState !== 'COMPLETE' && stageState !== 'STALE'`, button has `aria-disabled="true"` and does NOT call `onClick` when clicked. (Uses `aria-disabled`, not `disabled` attribute, per a11y spec §14.)
- `[T-SAVE-2]` When `saveInProgress` is true, button label is "Saving… ⟳" and button is `aria-disabled="true"`.
- `[T-SAVE-3]` When `stageState === 'STALE'` (and not saving), button label is "Save & Update →".
- `[T-SAVE-4]` When `stageState === 'COMPLETE'` (and not saving), button label is "Save & Continue →".
- `[T-SAVE-5]` When `stageState === 'COMPLETE'` or `'STALE'` and not saving: clicking the button calls `onClick()`.

---

### 4.7 `useSiteMetaForm`

**File:** `src/hooks/useSiteMetaForm.ts`

**Purpose:** encapsulates site name, province, and tariff form logic including the
province → tariff default relationship and the `[↺ Reset to province default]` logic.

```typescript
export function useSiteMetaForm(store: StageOneStoreState & StageOneStoreActions): {
  siteName: string;
  setSiteName: (name: string) => void;
  siteNameError: string | null;    // non-null when name.length > 64

  province: string;
  setProvince: (province: string) => void;

  tariffRegion: string;
  setTariffRegion: (regionId: string) => void;
  tariffManuallyOverridden: boolean;
  resetTariffToProvinceDefault: () => void;
  showTariffResetLink: boolean;    // true when tariffManuallyOverridden && province !== ""

  availableTariffs: TariffRegion[];   // from GET /api/tariff/regions (fetched on mount)
  tariffsLoading: boolean;
  tariffsError: string | null;
}
```

**Behavioral invariants:**
- `[T-META-1]` `siteNameError` is non-null when `siteName.length > 64`.
- `[T-META-2]` When `province` changes and `tariffManuallyOverridden` is false, `tariffRegion` is automatically updated to the province default (first tariff matching province prefix, e.g. `"cn-gansu"` for province `"Gansu"`).
- `[T-META-3]` When `province` changes and `tariffManuallyOverridden` is true, `tariffRegion` is NOT auto-updated; `showTariffResetLink` becomes `true`.
- `[T-META-4]` `resetTariffToProvinceDefault()` sets `tariffRegion` to the province default and sets `tariffManuallyOverridden = false`.
- `[T-META-5]` `availableTariffs` is populated from `GET /api/tariff/regions` on mount; `tariffsLoading` is true during the fetch.

---

## 5. API consumption

### 5.1 Validation debounce — `POST /api/site/validate`

**Trigger:** any of these fields change:
- `fleet` (add, remove, count change)
- `location` (lat or lon change)
- `tariffRegion`
- `scenarioBasePowerActive` (future scenarios)

**Debounce:** 300 ms from last change. If a new change arrives before the debounce fires,
the timer resets. While debounce is pending OR request is in flight, `validationPending = true`.

**Request body construction:**
```typescript
{
  site_config: {
    location: { lat: location.lat, lon: location.lon },
    assets: {
      // devices mapped from fleet rows where valid !== false
      fleet: fleet.filter(r => r.valid !== false).map(r => ({
        model_id: r.id,
        count: r.count
      }))
    },
    tariff_region: tariffRegion,
    scenario: { base_power: scenarioBasePowerActive }
  }
  // device_models omitted — backend uses its own loaded catalogue
}
```

**Error handling:** if `POST /api/site/validate` returns a non-200 response or network error:
- Set `validationPending = false`
- The `ValidationPanel` receives `apiError = "<message>"` and renders the retry UI.
- `stageState` is NOT advanced to COMPLETE on API failure — it stays `IN_PROGRESS`.

**Race-condition rule:** only the response to the most-recently-fired request is applied.
Stale responses (from earlier debounce cycles) are discarded. Use an AbortController keyed
to the debounce cycle.

### 5.2 Weather coverage debounce — `GET /api/site/weather-coverage`

**Trigger:** `location` changes (lat or lon).
**Debounce:** 500 ms from last change.

**On success:** store `coverageResult`, set `coveragePending = false`.
**On error/network failure:** set `coverageError = "<message>"`, `coveragePending = false`.
If coverage check fails, Historical/Bootstrap remain **disabled** (fail-safe). No retry
UI for coverage — user will get a fresh check on the next lat/lon change.

**Invariant:** `[T-API-COV-1]` While `coveragePending` is true, Historical and Bootstrap
radio buttons are disabled.

### 5.3 Device search debounce — `GET /api/devices/search`

**Trigger:** typing in the `fleet-add-id` autocomplete input.
**Debounce:** 200 ms.

**On success:** populate dropdown. If `results` is empty: show no-match error inline.
**On network error:** show spinner indefinitely (fail-open — user can still type and retry).

**Invariant:** `[T-API-SEARCH-1]` `[Add ✓]` button is disabled while the search is
in flight or has not yet returned a result for the current input value.

### 5.4 Tariff regions — `GET /api/tariff/regions`

**Trigger:** on `StageOneConfig` mount (once; no re-fetch).

**Usage:** populates the province → tariff default map and the tariff dropdown options.
Each tariff region entry shows: `region_id` + a summary line
`"¥{price_min}–{price_max}/MWh · 12×24 TOU"`.

**On error:** `tariffsError` is set; tariff dropdown renders an error placeholder
`"Tariff list unavailable"` (tariff selection is blocked until resolved; `[↺ Retry]`).

---

## 6. `Continue` invariants

**`[T-CONTINUE-1]`** `StageSaveButton` is enabled (not aria-disabled) iff `stageState === 'COMPLETE'`.

**`[T-CONTINUE-2]`** `stageState` can only be `COMPLETE` when:
- `lastValidation` is non-null
- `lastValidation.errors` is empty
- Every `rule_id` in `lastValidation.warnings` is in `acknowledgedWarnings`
- `validationPending` is false
- `saveInProgress` is false

**`[T-CONTINUE-3]`** A soft warning must be acknowledged for `stageState` to reach `COMPLETE`.
If a user acknowledges warning W, then changes a field that clears the acknowledgement,
`stageState` drops back from `COMPLETE` to `STALE` (or `IN_PROGRESS`), and W must be
re-acknowledged after the next successful validation.

---

## 7. Unhappy paths

**`[T-UNHAPPY-1]` Map tile failure:** If MapLibre fails to load tiles, `MapPicker` renders
`data-testid="map-tile-error"`. Lat/Lon text inputs remain enabled and are the fallback
input mechanism. No functional degradation to Stage ① workflow.

**`[T-UNHAPPY-2]` Validation API failure:** `POST /api/site/validate` 500 or network error →
`ValidationPanel` shows `data-testid="validation-api-error"` + `[↺ Retry]`. `stageState`
does NOT advance. `StageSaveButton` remains disabled.

**`[T-UNHAPPY-3]` Geolocation denied:** `navigator.geolocation.getCurrentPosition` failure →
toast `data-testid="location-toast"` shown (text: "Location unavailable"), auto-dismissed
after 4 s. No state change.

**`[T-UNHAPPY-4]` Empty fleet:** Continue is disabled when `fleet` is empty (hard error from
backend validation: "No battery device" — blocks save). The `ValidationPanel` shows this as
a hard error.

**`[T-UNHAPPY-5]` Device ID not found:** `GET /api/devices/search` returns no match for the
typed ID → `fleet-id-error` shown inline, `[Add ✓]` disabled.

**`[T-UNHAPPY-6]` NaN / extreme coordinates:** If lat/lon inputs are cleared or set to NaN,
`MapPicker` clears the pin but does NOT call `onLatLonChange` with invalid values.
`location` in the store becomes `null`.

**`[T-UNHAPPY-7]` Concurrent validation + save:** If the user clicks `[Save & Continue →]`
and a validation debounce is still pending (i.e., `validationPending === true`), the save
does NOT proceed. `StageOneConfig` waits for the validation response first:
  1. If validation resolves clean → proceed with save.
  2. If validation resolves with errors → abort save, show errors, re-enable button.
  3. If validation takes > 3 s → show "Still validating…" state; button remains in loading state.

---

## 8. Design token usage

All color values in Stage ① components MUST reference `TOKEN.*` from
`src/styles/tokenValues.ts` (design_system contract §6). Direct hex literals are prohibited.

Key tokens used in this feature:

| Token | Usage |
|-------|-------|
| `TOKEN.bgSurface` | Card backgrounds (sections, fleet table, validation panel) |
| `TOKEN.borderDefault` | Section dividers, table borders |
| `TOKEN.accentAmber` | `STALE` state badge, warnings, "Checking..." spinner |
| `TOKEN.accentGreen` | `COMPLETE` state badge, "✓ Configuration valid" |
| `TOKEN.accentRed` | Hard error text / borders |
| `TOKEN.accentBlue` | Active radio selection, focus rings |
| `TOKEN.accentGrey` | Disabled radio options (Historical/Bootstrap when unavailable) |
| `TOKEN.textMuted` | Secondary labels, placeholders |
| `TOKEN.textFaint` | Section headers, read-only cell text |

---

## 9. Accessibility

Per `docs/design/ux/stage_1_config.md §14`:

- `[T-A11Y-1]` Map container has `role="application"` and `aria-label="Site location map"`.
- `[T-A11Y-2]` Device ID autocomplete follows ARIA combobox pattern: `role="combobox"`,
  `aria-expanded`, `aria-controls` pointing to the results listbox.
- `[T-A11Y-3]` Each `ValidationPanel` error/warning is a `role="alert"` live region.
- `[T-A11Y-4]` `[Acknowledge ✓]` buttons have
  `aria-label="Acknowledge warning: {warning message}"`.
- `[T-A11Y-5]` `StageSaveButton` uses `aria-disabled="true"` (not the HTML `disabled`
  attribute) so disabled state is focusable with a descriptive `title` tooltip.
- `[T-A11Y-6]` `[← Back]` on Stage ① is rendered as `<span role="none">` (not `<button>`)
  — always disabled; not in the tab order.
- `[T-A11Y-7]` Color is never the only signal: hard errors use `✗` + red; warnings use `⚠` +
  amber; clean state uses `✓` + green.

---

## 10. File list

| File | Action |
|------|--------|
| `contracts/frontend/stage_config.md` | NEW — this contract |
| `tests/frontend/stage_config.test.tsx` | NEW — test suite (fails until impl) |
| `src/types/stageConfig.ts` | NEW — shared types |
| `src/stores/stageOneStore.ts` | NEW — Zustand store |
| `src/hooks/useSiteMetaForm.ts` | NEW — site meta form hook |
| `src/components/wizard/StageOneConfig.tsx` | NEW — root stage component |
| `src/components/wizard/MapPicker.tsx` | NEW — map + lat/lon + coverage |
| `src/components/wizard/DeviceFleetTable.tsx` | NEW — fleet table + add/remove |
| `src/components/wizard/ScenarioComposer.tsx` | NEW — scenario toggles (v1) |
| `src/components/wizard/ValidationPanel.tsx` | NEW — errors/warnings/ack |
| `src/components/wizard/StageSaveButton.tsx` | NEW — footer Continue button |

---

## 11. Out of scope / deferred

| Feature | Pending contract |
|---------|-----------------|
| `POST /api/site/config` (save persistence + config hash) | `site_config_persistence.md` |
| `GET /api/site/resolve` (site totals strip) | `site_resolve.md` |
| Historical weather fetch + polling | future contract |
| `WizardBar` stepper | `wizard_shell.md` |
| `StageShell` layout wrapper | `wizard_shell.md` |
| `AddToComparisonModal` | separate contract |
| Custom tariff upload (CSV) | v2 |
| Province → tariff default map (full list) | derived from `GET /api/tariff/regions` at runtime |
| Province list (full Chinese provinces list) | public config, served from `GET /api/tariff/regions` for now |

---

## 12. Deliberate deviations

1. **`aria-disabled` instead of HTML `disabled`** on `StageSaveButton` — per a11y spec §14:
   disabled buttons with `disabled` attribute are removed from tab order and cannot receive
   focus for a screen-reader tooltip. `aria-disabled="true"` keeps the button focusable.
2. **`stageState` does not advance on validation API failure** — the fail-safe is that Continue
   cannot be enabled without a successful backend validation response. This matches
   stage_1_config.md §8: "Validation unavailable → Continue remains disabled."
3. **Site totals strip renders `—` until `site_resolve.md` is implemented** — the strip DOM
   is present (layout is stable) but shows placeholder values. This avoids a mid-stream
   layout shift when `site_resolve.md` lands.

---

*contracts/frontend/stage_config.md — frontend-engineer, task #2 — v0.1 2026-06-13 (initial draft)*
