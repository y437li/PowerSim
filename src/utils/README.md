# `src/utils`

<!-- curated -->
## Purpose

Shared pure-function utilities with no React, no state, and no network dependencies. Any module that needs a unit conversion, a TOU lookup, or an alert derivation imports from here; the inverse is forbidden — nothing in this folder may import from components, stores, or clients.

`units.ts` is the single source of all unit conversions (MW ↔ kW, SOC fraction → %, ¥ and ¥/MWh formatting). Wire values throughout the app are always in MW / MWh / ¥ / ¥/MWh; conversion to display units happens only here. `touSchedule.ts` encodes the §3.7 Gansu 4-tier TOU schedule as the `TOU_SCHEDULE` constant and exposes `getTouTier()` (minute-accurate, consistent with D8). `touColors.ts` maps TOU tiers to display colour tokens; all TOU colour definitions are consolidated here and nowhere else. `deriveAlerts.ts` exposes `deriveAlerts()`, which scans `env_step` history for constraint-violation events (curtailment, VOLL, SOC out-of-bounds) using an `ALERT_EPSILON` guard of 0.001 MW — the function derives display events from physics data and has no opinion on what caused them.
<!-- /curated -->

---

<!-- generated:start -->

## Index

### `deriveAlerts.ts`

| Symbol | Kind | Purpose |
|--------|------|---------|
| `AlertEvent` | `interface` | — |
| `deriveAlerts` | `function` | — |

### `touColors.ts`

> All TOU tier colour tokens live here — nowhere else defines them inline.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TOU_COLORS` | `const` | — |
| `getTouColor` | `function` | Returns the colour tokens for a TOU tier. |
| `getTouCssVar` | `function` | Returns the CSS variable name for a TOU tier, e.g. "--tou-peak". |

### `touSchedule.ts`

> src/utils/touSchedule.ts — consumed by PriceTimeline background bands and getTouTier()

| Symbol | Kind | Purpose |
|--------|------|---------|
| `TouBand` | `interface` | — |
| `TOU_SCHEDULE` | `const` | — |
| `getTouTier` | `function` | — |
| `getTouPrice` | `function` | — |
| `BandSegment` | `interface` | One contiguous run of steps sharing the same TOU tier on the PriceTimeline x-axis. |
| `computeBandSegments` | `function` | Map history entries onto x-axis band segments for PriceTimeline ReferenceArea. |

### `units.ts`

> ALL unit conversions live here — nowhere else imports conversion math inline.

| Symbol | Kind | Purpose |
|--------|------|---------|
| `socToPercent` | `function` | SOC: fraction [0,1] → display percent. D4: 0.2→20.0, 0.9→90.0. |
| `mwToKw` | `function` | Power: MW → kW (display only; wire values are always MW). |
| `kwToMw` | `function` | Power: kW → MW |
| `formatYuan` | `function` | Format a ¥ amount with thousands separator. |
| `formatYuanPerMwh` | `function` | Format a ¥/MWh price. Contract rule: wire prices are ¥/MWh, NEVER ¥/kWh. |
| `formatPower` | `function` | Format power picking unit by magnitude: |
| `formatSimTime` | `function` | Format an ISO-8601 UTC sim clock as "DDD HH:MM". |
| `formatThroughput` | `function` | Format env_steps_per_sec throughput. |
| `formatSteps` | `function` | Format a global_step count. |
| `formatWallSeconds` | `function` | Format wall_seconds duration. Floor (not round) for sub-unit truncation. |

<!-- generated:end -->
