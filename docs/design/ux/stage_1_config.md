# Stage ① — Site Configuration: Per-Screen Layout

> **Owner:** ui-designer · **Task:** #65
> **Status:** DRAFT v0.1 (2026-06-12)
> **Gate:** frontend-reviewer verdict on PR #85 before frontend contract is authored.
> **Parent doc:** wizard_flow.md v0.5 (§4, §10) — this document deepens the Config stage only; all cross-stage rules stay in the parent.
> **Inputs:** wizard_flow.md §4, master_plan_geo_finance.md §3 (site config resolver), REBUILD_SPEC §3.2, contracts/frontend/app_integration.md

---

## 1. Purpose and scope

This document specifies the complete per-screen layout for Stage ① (Site Configuration) of the five-stage wizard. It covers every sub-state, section layout, component behaviour, and edge case needed to author the `contracts/frontend/stage_config.md` contract.

**What this document does NOT cover:**
- WizardBar internals or cross-stage navigation (see wizard_flow.md §3)
- Edit-class cascade rules (see wizard_flow.md §2)
- Backend validation endpoint schema (see contracts/serving/ — to be authored)
- Device model schema (see contracts/shared/device_model_schema.md — locked)

---

## 2. Stage state machine at Config

Config is always the first stage. It can never be LOCKED (the user always arrives here first).

```
FIRST_VISIT   — no saved config; all fields empty; Continue disabled
IN_PROGRESS   — fields partially filled; validation may show errors/warnings
VALIDATING    — debounced server call in flight (300 ms after last edit)
COMPLETE      — all hard errors resolved, soft warnings acknowledged; Continue enabled
STALE         — was COMPLETE, then the user returned and edited something;
                Continue shows "Save & Update →"; amber amber notice in Stage ③ only
```

The WizardBar shows the stage state as a badge on the ① step icon:
- `FIRST_VISIT` / `IN_PROGRESS` → no badge (unfilled circle)
- `VALIDATING` → spinning indicator on the step icon
- `COMPLETE` → green check ✓
- `STALE` → amber dot ●

---

## 3. Page-level layout

### 3.1 Desktop (≥ 1024 px) — two-column

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config  →  ②Algorithm  →  ③Train  →  ④Eval  →  ⑤Finance                  │
│  (provenance subtitle: last-saved config hash, or blank if unsaved)          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ LEFT COLUMN (40%) ─────────────────┐  ┌─ RIGHT COLUMN (60%) ──────────┐ │
│  │                                     │  │                               │ │
│  │  MAP TILE VIEW                      │  │  ┌── SITE METADATA ─────────┐ │ │
│  │  [MapLibre; ~400px tall]            │  │  │ Site name  [            ]│ │ │
│  │  [draggable blue pin]               │  │  │ Province   [Gansu     ▼ ]│ │ │
│  │  [zoom +/− controls]               │  │  │ Tariff     [TOU-2024  ▼ ]│ │ │
│  │  [open in full screen ↗]           │  │  └──────────────────────────┘ │ │
│  │                                     │  │                               │ │
│  │  ── LOCATION ─────────────────────  │  │  ┌── DEVICE FLEET ──────────┐ │ │
│  │  Lat  [38.0000   °N]               │  │  │ [fleet table — §5]       │ │ │
│  │  Lon  [102.0000  °E]               │  │  │                           │ │ │
│  │  [📍 Use my location]              │  │  │ Site totals strip         │ │ │
│  │                                     │  │  └──────────────────────────┘ │ │
│  │  ── WEATHER MODE ────────────────── │  │                               │ │
│  │  [● Synthetic  ○ Historical  ○ Bs ] │  │  ┌── SCENARIO COMPOSITION ──┐ │ │
│  │  (Historical/Bootstrap: availability│  │  │ [scenario toggles — §6]  │ │ │
│  │  indicator below: ✓ or ⊗ + reason)  │  │  └──────────────────────────┘ │ │
│  │                                     │  │                               │ │
│  └─────────────────────────────────────┘  │  ┌── VALIDATION ────────────┐ │ │
│                                           │  │ [errors / warnings — §7] │ │ │
│                                           │  └──────────────────────────┘ │ │
│                                           └───────────────────────────────┘ │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [← Back (disabled)]      [+ Add to Comparison]      [Save & Continue →]    │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Column proportions:** left `flex: 0 0 40%`, right `flex: 1`. Map is `position: sticky; top: 0` so it stays in view as the right column scrolls (device fleet table can grow long).

### 3.2 Tablet (768–1023 px) — stacked, map collapsed

Map moves above the right-column sections. Map height collapses to 240 px. Location inputs remain below the map. Right column becomes full width.

### 3.3 Mobile (< 768 px) — stacked, map 180 px

Map collapses to 180 px. A `[↕ Expand map]` toggle expands it to 50 vh. Location inputs below map as two narrow inline fields. All right-column sections stack vertically and scroll.

---

## 4. Left column — Map and Location

### 4.1 Map component

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│        [OpenStreetMap tile background]                         │
│                                                                │
│                      📍 (blue draggable pin)                  │
│                                                                │
│                                          [+]  (zoom in)        │
│                                          [−]  (zoom out)       │
│                                          [↗]  (fullscreen)     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
│  Lat  [38.0000  ]°N     Lon  [102.0000  ]°E                    │
│  [📍 Use my location]                                          │
└────────────────────────────────────────────────────────────────┘
```

**Behaviour:**
- Map initialises centred on China (35°N 105°E, zoom 4) if no saved lat/lon.
- On saved lat/lon: fly to coordinates, zoom 9, drop pin.
- **Bidirectional sync:** typing in Lat/Lon updates the pin position (after valid parse); dragging the pin updates the Lat/Lon fields.
- Lat/Lon fields accept decimal degrees. Accept `N/S/E/W` suffix or positive/negative. Max precision: 4 decimal places (≈11 m).
- **Tile failure:** if tiles fail to load (network error or CORS), map background becomes a solid `#1e2533` (card background) and a notice appears: "Map tiles unavailable — enter coordinates manually." Lat/Lon text inputs remain fully functional.
- `[📍 Use my location]`: calls `navigator.geolocation.getCurrentPosition`. On success, flies to coordinates and fills fields. On failure or denial: shows `"Location unavailable"` toast (dismisses after 4 s), no state change.
- `[↗ Fullscreen]`: expands map to full viewport in a modal overlay; same bidirectional sync applies.

**Weather-mode availability indicator:**
Immediately below the Weather Mode selector, a small one-line indicator shows data availability for the current coordinates:
```
Synthetic:    ✓ Always available
Historical:   ✓ 4 yr available (2020–2023) — Open-Meteo ERA5
Bootstrap:    ✓ derived from historical
```
or, if outside coverage:
```
Historical:   ⊗ Outside Open-Meteo coverage — synthetic only
Bootstrap:    ⊗ requires historical data
```
This check calls `GET /api/site/weather-coverage?lat=…&lon=…` (debounced 500 ms on coordinate change). Historical/Bootstrap options are disabled (greyed) if coverage is unavailable.

### 4.2 Weather mode selector

Three-way radio: `● Synthetic  ○ Historical  ○ Bootstrap`

- **Synthetic** (default): always enabled; uses the JAX weather generator.
- **Historical**: enabled only when Open-Meteo ERA5 data covers the coordinates; shows `(4 yr)` count next to the label when enabled.
- **Bootstrap**: enabled only when Historical is available; shows `(derives from historical)` sub-label.

Selecting Historical/Bootstrap while the coverage check is still loading shows a spinner on the label; if check fails, both remain greyed with tooltip "Checking coverage…"

---

## 5. Right column — Device Fleet

### 5.1 Fleet table

```
┌─ DEVICE FLEET ──────────────────────────────────────────────────────────────┐
│                                                                              │
│  Device ID                │ Type  │  Count  │  Capacity (from model)  │     │
│  ─────────────────────────┼───────┼─────────┼─────────────────────────┼──── │
│  vestas-v150-4.2          │ 🌬 W   │   100   │  100 × 4.2 MW = 420 MW  │ [✕] │
│  catl-lmp-300mwh          │ 🔋 B   │    1    │  1 × 300 MWh / 90 MW    │ [✕] │
│  [+ Add device ▼]         │       │         │                          │     │
│                                                                              │
│  SITE TOTALS                                                                 │
│  420 MW wind  ·  0 MWp PV  ·  300 MWh / 90 MW battery  ·  Grid: 945 MW    │
│  (from server resolver — GET /api/site/resolve)                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Column spec:**

| Column | Width | Type | Behaviour |
|--------|-------|------|-----------|
| Device ID | flex | Autocomplete text input | Queries `GET /api/devices?q=…` (debounced 200 ms); shows dropdown of matching IDs from device_models.yaml |
| Type | 2rem | Read-only icon | Resolved from device model: W=wind, S=solar, B=battery, G=grid |
| Count *(non-PV)* | 5rem | Integer input | min=1, max=999; spinner ↑↓; keyboard arrows. **Not rendered for `pv_panel` rows** — see PV variant below. |
| Fleet capacity *(PV only)* | 5rem | Float input (MWp) | Editable total installed PV capacity in MWp. **Replaces Count for `pv_panel` rows.** |
| Capacity | flex | Read-only text | Non-PV: `n × capacity_mw MW` or `n × capacity_mwh MWh / peak_mw MW`. PV: `{fleet_capacity_mw} MWp`. Highlighted amber if near a physical limit. |
| Remove | 2.5rem | [✕] button | Removes row immediately; triggers revalidation |

**PV device row variant:**

`pv_panel` devices are sized by total installed site capacity (MWp), not unit count. This reflects
a hard constraint in `device_model_schema` v2.0 — the schema has no `panel_mw_per_unit` field, so
a "count × per-panel MW" formula is not possible. Combined with D37 server-side assembly, the wizard
sends `fleet_capacity_mw` directly to `/api/site/assemble` for PV entries (no count).

The fleet table adapts for PV rows:
- **Count column hidden** — replaced by the Fleet capacity (MWp) input
- **Fleet capacity (MWp) column** — editable float; operator enters the total MWp for this PV array
- **Capacity column** — read-only `{fleet_capacity_mw} MWp`

Example with a PV row:
```
┌────────────────────────────────────────────────────────────────────────────────┐
│  Device ID                │ Type │ Count │ Capacity (from model)       │      │
│  ─────────────────────────┼──────┼───────┼─────────────────────────────┼───── │
│  vestas-v150-4.2          │ 🌬 W  │  100  │ 100 × 4.2 MW = 420 MW       │ [✕]  │
│  trina-vertex-n-670w      │ ☀ S  │ [330] │ 330 MWp                     │ [✕]  │
│                           │      │  MWp  │ ← float input, not count    │      │
│  catl-lmp-300mwh          │ 🔋 B  │   1   │ 1 × 300 MWh / 90 MW         │ [✕]  │
└────────────────────────────────────────────────────────────────────────────────┘
```

**Autocomplete dropdown (Device ID):**
```
  vestas-v150-4.2       │ Wind turbine · 4.2 MW · CATL motor
  vestas-v150-4.5       │ Wind turbine · 4.5 MW · ...
  [+ Create custom ID]  │ (future, v2 — greyed for now)
```
- Shows name + type + peak capacity as a one-liner per match.
- If the typed ID is not found in the library after the API returns: shows `✗ "my-turbine" not found in device library` inline in the row (red, hard error).
- If the API call is in flight: shows a spinner in the Device ID cell; row is not validated until response arrives.

**Add device flow:**

`[+ Add device ▼]` opens a small inline form that adapts to the resolved device type:

Non-PV (wind_turbine / battery / grid_connection):
```
  Device ID [              ]   Count [  1  ]   [Add ✓]  [Cancel ✕]
```

PV (pv_panel — shown once the search resolves the type):
```
  Device ID [trina-vertex-n-670w  ]   Fleet capacity (MWp) [      ]   [Add ✓]  [Cancel ✕]
```
- Count is replaced by "Fleet capacity (MWp)" with no default
- `[Add ✓]` disabled until a positive MWp value is entered

On `[Add ✓]`: validates device ID against the library, resolves capacity, appends to table, triggers revalidation.

**Site totals strip:**
- Computed server-side: `GET /api/site/resolve` with current config (debounced 500 ms on fleet change)
- Shows: `{wind_mw} MW wind · {pv_mwp} MWp PV · {bat_mwh} MWh / {bat_mw} MW battery · Grid: {pcc_mw} MW`
- `—` shown while loading or if no devices yet
- Grid connection capacity comes from a special device class (type=G); if no grid device is in the fleet, Grid shows `(none)` in amber.

**Empty state (no devices yet):**
```
┌─ DEVICE FLEET ──────────────────────────────────────────────────────────────┐
│                                                                              │
│  No devices added yet.                                                       │
│  [+ Add device]   ← centred, primary-style button                           │
│                                                                              │
│  Site totals: —                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```
Continue is disabled until at least one valid device is present (hard error).

---

## 6. Right column — Site Metadata

```
┌─ SITE ─────────────────────────────────────────────────────────────────────┐
│  Name     [Gansu demo site                    ]  (optional, max 64 chars)  │
│  Province [Gansu                            ▼ ]                            │
│  Tariff   [Gansu-TOU-2024 (auto from province)▼ ]  [ℹ]                    │
└────────────────────────────────────────────────────────────────────────────┘
```

**Site name:** Optional free text field. Used as the human-readable label in the policy library provenance and the WizardBar subtitle. If blank, defaults to `Config #<hash>`. Max 64 chars; inline character count shown at 50+ chars.

**Province selector:** Drives the tariff default. Options: all Chinese provinces + a "Custom" entry. On province change: tariff selector auto-updates to the province default if the tariff was previously the other province's default (i.e., has not been manually overridden). If user manually selected a tariff: province change shows a `[↺ Reset to province default]` link next to the tariff.

**Tariff selector:** Dropdown listing all available tariffs from the tariff library (task #58). Each entry shows tariff name + season structure summary (`12×24 TOU · Gansu · 2024`). An `[ℹ]` icon opens a mini popover showing the tariff preview table (peak/off-peak price bands by hour). "Custom" option (v2): uploads a 12×24 CSV. For v1, Custom shows `(coming in v2)` — greyed.

---

## 7. Right column — Scenario Composition

```
┌─ SCENARIO ──────────────────────────────────────────────────────────────────┐
│  ☑ Power supply  [base — always active]                                     │
│  (additional scenario groups appear when activated in future versions)       │
└──────────────────────────────────────────────────────────────────────────────┘
```

In v1, only the "Power supply" base scenario is shown. It is always checked and cannot be unchecked. The section header remains present so the layout is stable when additional scenarios (H₂, datacenter) appear in future versions as additional toggleable rows.

When a future scenario activates (out of scope for v1):
```
  ☑ Power supply  [base — always active]
  ☐ Green hydrogen   ▸ (collapsed — click to expand device config)
  ☐ Datacenter load  ▸ (collapsed)
```
Each toggled-on scenario appends its device config rows to the Device Fleet table and adds its revenue streams to Stage ⑤ Finance.

---

## 8. Right column — Validation

```
┌─ VALIDATION ────────────────────────────────────────────────────────────────┐
│                                                                              │
│  [ Checking... ]          ← while POST /api/site/validate is in flight     │
│                                                                              │
│  OR, when results arrive:                                                    │
│                                                                              │
│  ✗ [hard error]  Device "my-turbine" not found in device library             │
│  ✗ [hard error]  No battery device — at least one required for this scenario │
│                                                                              │
│  ⚠ [soft warning]  Historical weather: 2 yr available (2022–2023) —         │
│                     short horizon may affect training diversity              │
│                     [Acknowledge ✓]                                          │
│                                                                              │
│  ✓ Configuration valid                  ← shown when no errors/warnings     │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Validation source:** backend-only. `POST /api/site/validate` called debounced 300 ms after any meaningful change (device add/remove/count change, lat/lon change, tariff change, scenario toggle). Never TS-recomputed.

**Hard errors (red ✗):**
- Block `[Save & Continue →]` — button is `disabled`
- Examples from the backend: `"Device 'x' not found"`, `"No battery device"`, `"C-rate 0.67 exceeds limit 0.5"`, `"Lat/lon outside valid range"`
- Messages are field-level and numbers-shown (e.g. `"98 MW / 294.5 MWh = 0.33 C — OK"`)

**Soft warnings (amber ⚠):**
- Each warning has an `[Acknowledge ✓]` button
- `[Save & Continue →]` is disabled until ALL warnings are acknowledged
- Acknowledging a warning: the warning row gains a `✓ Acknowledged` state (faint, struck through) and the acknowledge button disappears
- Acknowledged warnings are re-shown as unacknowledged if the relevant field changes (e.g., if the user changes lat/lon after acknowledging a coverage warning, the coverage warning reappears fresh)

**Clean state:**
- Shows `✓ Configuration valid` (green checkmark + text) only when: validation has returned with zero errors AND zero warnings (or all warnings acknowledged)

**Loading state:**
- `[ Checking... ]` with a subtle spinner — shown for at most ~2 s (typical backend response); if the call takes > 2 s, a secondary "Still checking…" message appears

**Error state (validation API failure):**
- Shows `⚠ Validation unavailable — check connection` (amber)
- `[Save & Continue →]` remains disabled (fail-safe: cannot proceed without backend confirmation)
- Retry button: `[↺ Retry]` beside the message

---

## 9. Footer

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [← Back]                 [+ Add to Comparison]         [Save & Continue →] │
│  (always disabled         (enabled if no hard           (disabled if any     │
│   on Step ①)               errors; see §9.2)             hard error or any   │
│                                                          unack'd warning)    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 9.1 [← Back]
Always disabled on Stage ①. Renders as a greyed `← Back` text (not a button) to keep layout consistent with other stages. No `<button>` element — a `<span role="none">` with disabled styling, so it is not focusable.

### 9.2 [+ Add to Comparison]
- Enabled when: no hard validation errors present (soft warnings do not need to be acknowledged to add to comparison)
- Opens the `AddToComparisonModal` (see comparison_workbench.md §6.1)
- What is sent: current in-memory config state (not the last saved config). If the user has unsaved changes, the modal shows: "You have unsaved changes. The comparison variant will use the current (unsaved) config. Save first to lock this config."
- A saved config hash is shown in the modal; an unsaved config shows `"(unsaved draft)"`.

### 9.3 [Save & Continue →]
- **Label:** `Save & Continue →` on first save; `Save & Update →` in STALE state
- **Enabled when:** no hard errors AND all soft warnings acknowledged (or no warnings)
- **On click:**
  1. Calls `POST /api/site/config` (or `PUT /api/site/config/{hash}`) to persist the config
  2. Receives back a `config_hash`
  3. Updates the WizardBar Step ① subtitle with the hash
  4. Transitions stage state to COMPLETE
  5. Navigates to Stage ②

---

## 10. First-visit / empty state

When the user opens the wizard for the first time (no saved config):

```
Map:           centred on China (35°N, 105°E, zoom 4); no pin
Lat/Lon:       empty fields
Weather mode:  ● Synthetic (default, always available)
Site name:     empty
Province:      "(select province)" placeholder
Tariff:        "(select tariff)" placeholder (disabled until province chosen)
Device fleet:  empty — "No devices added yet" + [+ Add device] prompt
Validation:    silent (no check until user starts filling fields)
Footer:        [← Back: disabled]  [+ Add to Comparison: disabled]  [Save & Continue →: disabled]
```

First interaction that triggers validation: any device add, lat/lon change, or tariff selection.

---

## 11. Returning to a COMPLETE stage (STALE flow)

When the user has previously completed Config and navigates back to edit it:

```
Map:           shows saved coordinates; pin present
All fields:    pre-filled with saved values
Validation:    shows last-known-good state (no re-check until user edits)
Footer:        [Save & Update →]  (label change signals this is an update, not first save)
Stage ③ Train: amber notice: "Current config differs from trained policies — start a new run..."
               (this notice is in Stage ③, NOT in Config — Config makes no declaration about it)
```

The stage transitions from COMPLETE → STALE immediately on any field edit (even if reverted back to the original value — STALE clears only on Save). The STALE indicator on the WizardBar step ① is visible but does not block anything in Stage ①.

---

## 12. Sub-state: saving in progress

When `[Save & Continue →]` is clicked and the `POST /api/site/config` call is in flight:

```
Footer:  [← Back: disabled]  [+ Add to Comparison: disabled]  [Saving…  ⟳ ]
```
- All form fields are `disabled` (prevent edits during save)
- The Continue button shows a spinner + "Saving…" label
- On success: animate to Stage ②
- On API failure: show an error toast `"Save failed — check connection"` (4 s), re-enable all fields and footer buttons; do NOT navigate away

---

## 13. Sub-state: validation in flight while continuing

If the user clicks `[Save & Continue →]` and a validation debounce is in flight simultaneously:

1. Wait for the validation response (up to 3 s)
2. If validation returns clean: proceed with save
3. If validation returns errors: abort save, show errors in Validation panel, re-enable button

Never proceed to Stage ② with an unvalidated config.

---

## 14. Accessibility notes

- Map container: `role="application"` with `aria-label="Site location map"`. Keyboard users can tab to it and use arrow keys to pan (MapLibre default). The map is non-essential for form submission — lat/lon text inputs are the fallback.
- Device ID autocomplete: follows ARIA combobox pattern (`role="combobox"`, `aria-expanded`, `aria-controls` pointing to the listbox).
- Validation panel: each error/warning is a `role="alert"` live region so screen readers announce changes as they arrive.
- `[Acknowledge ✓]` button: `aria-label="Acknowledge warning: [warning text]"` to identify which warning is being dismissed.
- Color is never the only signal: hard errors use `✗` symbol + red color; warnings use `⚠` symbol + amber color; clean state uses `✓` + green color.
- Footer buttons: all have descriptive `aria-label`s; disabled buttons use `aria-disabled="true"` (not `disabled` attribute, to remain focusable for screen readers with a tooltip explaining why).

---

## 15. Component checklist (from wizard_flow.md §10)

Components required for this stage (to be specced in `contracts/frontend/stage_config.md`):

| Component | Role in this stage |
|-----------|-------------------|
| `WizardBar` | Top stepper; shows stage ①–⑤ with state badges; provenance subtitle for ① |
| `MapPicker` | Left column map + lat/lon inputs + weather-coverage indicator |
| `DeviceFleetTable` | Right column fleet table + site totals strip |
| `ScenarioComposer` | Right column scenario toggle section (v1: single base scenario) |
| `StageShell` | Outer wrapper: header slot, content (two columns), footer slot |
| `AddToComparisonModal` | Footer `[+ Add to Comparison]` action |

Shared (already contracted):
| Component | Source |
|-----------|--------|
| `ErrorBoundary` | contracts/frontend/error_boundary_reset_key.md |

New primitives needed (shared across stages):
| Component | Used for |
|-----------|----------|
| `ValidationPanel` | §8 — errors/warnings/acknowledge; also used in other stages with validation |
| `StageSaveButton` | Footer "Save & Continue / Update" with loading state |
| `ProvenanceBadge` | Stage subtitle (config hash + human summary) |

---

## 16. Open questions

**Q1 — Province/tariff dependency edge case:** If the user selects a province, then manually overrides the tariff, then changes province again — should the tariff reset to the new province default, or stay at the manual override? Current design: show `[↺ Reset to province default]` link but do NOT auto-reset. USER decision pending; design assumes non-destructive (keep override). Flag in contract.

**Q2 — Grid connection device:** The fleet table includes a grid connection device (type=G, e.g. `pcc-substation-945mw`). If the user doesn't add a grid device, the site totals show `Grid: (none)` in amber. Is a grid device required (hard error) or optional (soft warning)? Current assumption: required — no grid device = hard error blocking Continue. Confirm with rl-architect / backend contract.

**Q3 — Map tile provider:** OpenStreetMap is the default; for China deployments, OSM tiles may be blocked or slow. A Mapbox/Amap fallback should be planned. For v1, OSM default is acceptable; the tile-failure fallback (text-only mode) handles the edge case. Flag for task #59 design-system tokens: tile provider config should be an env var, not hardcoded.

**Q4 — Config versioning:** When the user saves an updated config (`PUT /api/site/config/{hash}`), does the backend return a new hash (immutable configs) or update in place? The design assumes immutable (each save = new hash), which supports the policy library's provenance model. Confirm with serving-engineer when authoring the endpoint contract.

---

*docs/design/ux/stage_1_config.md — ui-designer, task #65 — v0.1 2026-06-12 (initial per-screen layout: two-column desktop, all sub-states, device fleet table, map/location, validation panel, footer interactions, a11y notes, component checklist)*
