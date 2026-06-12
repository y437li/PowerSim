# Stage ⑤ — Finance: Per-Screen Layout

> **Owner:** ui-designer · **Task:** #65
> **Status:** DRAFT v0.2 (2026-06-12) — distribution-aware results: P50/P90 bankability pair headline, NpvFanChart, percentile-selector cash-flow chart, ensemble-size indicator, CI convergence hint; M-series instant client-side re-discount; workbench delta footnote
> **Gate:** frontend-reviewer verdict before frontend contract is authored.
> **Parent doc:** wizard_flow.md v0.6 (§8, §10) — this document deepens Stage ⑤ only.
> **§13 alignment pending:** finance-expert is drafting §13 (project-finance spec); field names in this doc should be reconciled with §13 before the frontend contract is written.
> **Prerequisite:** Stage ④ Eval must have at least one COMPLETE eval result.
> **Core principle:** Every finance parameter is displayed and editable in this panel — nothing buried in config files. The compute-residency split (instant vs ~1–3 s) is invisible plumbing. The operator adjusts any assumption; results update.

---

## 1. Purpose and scope

Stage ⑤ runs a project finance simulation over a 10–20 year horizon: IRR, NPV, MIRR, LCOE, payback period, and year-by-year cash flows. The full assumptions panel is always visible and editable, with CAPM decomposition, provenance badges, and per-field ↺ resets. Results update immediately or within a beat depending on which parameters changed (see §9).

This document covers the complete layout, all six assumptions sections, the results panel, chart specs, export, and the `[+ Add to Comparison]` entry point.

---

## 2. Stage states

```
LOCKED    — Stage ④ has no COMPLETE eval results
PENDING   — Stage ④ has results; user has not yet selected an eval basis
COMPLETE  — finance projection has been computed and displayed
```

Stage ⑤ is never STALE — eval results are immutable. The assumptions panel always shows the current assumptions; results always show what the current assumptions produce from the selected eval basis. If the eval basis was computed against a different site config than the current wizard config, a blue `ℹ` provenance notice is shown (not a warning).

WizardBar badge: LOCKED → 🔒, PENDING → empty circle, COMPLETE → green ✓

---

## 3. Page-level layout

### 3.1 Desktop (≥ 1280 px) — two-column (assumptions left, results right)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WIZARD BAR                                                                  │
│  ①Config ✓  →  ②Algorithm ✓  →  ③Train ✓  →  ④Eval ✓  →  ⑤Finance ●        │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─ LEFT: ASSUMPTIONS (40%) ──────────────┐  ┌─ RIGHT: RESULTS (60%) ─────┐ │
│  │  (scrollable; sticky header)           │  │  (scrollable; AssumpStrip  │ │
│  │                                        │  │   sticky at top)           │ │
│  │  ┌─ EVAL BASIS ───────────────────┐    │  │                            │ │
│  │  │ SAC run-a1b2c3 · #a1b2c3  [▼] │    │  │  [AssumptionsStrip — §8]   │ │
│  │  │ ℹ Config match ✓              │    │  │  ─────────────────────────  │ │
│  │  └────────────────────────────────┘    │  │                            │ │
│  │                                        │  │  [Headline Metrics — §10]  │ │
│  │  ┌─ ASSUMPTIONS PANEL ────────────┐    │  │                            │ │
│  │  │ ▾ DISCOUNT RATE          [§4]  │    │  │  [CashFlowChart — §11]     │ │
│  │  │ ▸ CAPITAL STRUCTURE      [§5]  │    │  │                            │ │
│  │  │ ▸ ESCALATION / CURRENCY  [§6]  │    │  │  [NpvCurveChart — §12]     │ │
│  │  │ ▸ LIFECYCLE COSTS        [§7]  │    │  │                            │ │
│  │  │ ▸ CAPEX / OPEX           [§8]  │    │  │  [TornadoChart — §13]      │ │
│  │  │ ▸ ACCOUNTING             [§9]  │    │  │                            │ │
│  │  │                                │    │  │                            │ │
│  │  │ [↺ Reset all to defaults]      │    │  │                            │ │
│  │  └────────────────────────────────┘    │  │                            │ │
│  │                                        │  │                            │ │
│  └────────────────────────────────────────┘  └────────────────────────────┘ │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  [← Back to Eval]                 [+ Add to Comparison]  [Export results ▾] │
��───────────────────────��──────────────────────────────────────────────────────┘
```

**Column behaviour:**
- Left column has a sticky section header so the user always sees which assumptions section they are in as they scroll.
- Right column has the `AssumptionsStrip` sticky at the top — always visible while scrolling through charts.
- On screens 1024–1279 px: both columns remain but left collapses to 36%, right expands to 64%.

### 3.2 Tablet / mobile — stacked

Left column (assumptions) appears as a collapsible `▾ Assumptions` section above the results. Right column fills full width. On mobile, charts are 100% width with horizontal scroll disabled (charts reflow to a single-series view).

---

## 4. Assumptions section: DISCOUNT RATE (default open)

```
▾  DISCOUNT RATE                                         [↺ Reset section]

   ── CAPM BUILD-UP ──────────────────────────────────────────────────────
   r_f (risk-free)   [ 2.85   ] %     Tenor: [10yr CNY Treasury ▼]
                      [benchmark-cited ↺]     Date: 2026-06-01

   β (equity beta)   [ 0.75   ]       China utility-scale renewable
                      [benchmark-cited ↺]

   ERP               [ 5.50   ] %     Equity risk premium
                      [benchmark-cited ↺]

   ── DERIVED ─────────────────────────────────────────────────────────────
   WACC              = r_f + β × ERP = 2.85% + 0.75 × 5.50% = 7.0 %
   (formula shown; WACC is read-only while CAPM is active)

   ── OVERRIDE ────────────────────────────────────────────────────────────
   Override WACC     [──────●──────────]  7.0 %   (slider, range 1%–20%)
                     (drag slider → CAPM fields dim → [↺ Restore CAPM] appears)

   ── IF OVERRIDDEN ────────────────────────────────────────────────────────
   WACC override     [ 8.00   ] %                [USER-set ↺]
                     [↺ Restore CAPM (would give 7.0%)]
```

**Behaviour:**
- While CAPM is active (not overridden): the WACC readout is computed from r_f, β, ERP and is read-only. A formula tooltip shows on hover.
- When the override slider is dragged: CAPM fields (`r_f`, `β`, `ERP`) visually dim (opacity 0.5); WACC becomes editable; a `[↺ Restore CAPM]` button appears.
- `[↺ Restore CAPM]`: clears the override, re-computes WACC from r_f/β/ERP, fields restore to full opacity.
- r_f tenor picker: `[1yr · 5yr · 10yr · 30yr CNY]` — changing the tenor updates r_f to the current market yield for that tenor (fetched from `GET /api/finance/rfrate?tenor=10yr`; falls back to the current displayed value if offline).
- ERP auto-adjusts when r_f changes (ERP = total expected market return − r_f; if total return is held constant, ERP decreases as r_f increases). The user can always manually override ERP.

**Response:** r_f / β / ERP / WACC override → instant client-side recompute of NPV/IRR/MIRR (Class B parameter).

---

## 5. Assumptions section: CAPITAL STRUCTURE (default collapsed)

```
▸  CAPITAL STRUCTURE                                     [↺ Reset section]
   (expand to edit)

   ── WHEN EXPANDED ────────────────────────────────────────────────────────
   Debt / Equity ratio   [ 60 / 40   ] %               [benchmark-cited ↺]
   Cost of debt (Kd)     [ 4.50      ] %                [benchmark-cited ↺]
   Tax rate              [ 25        ] %   (corporate)  [benchmark-cited ↺]
   Enable tax shield     [● Yes  ○ No]                  [USER-set ↺] / [default ↺]
   Enable debt financing [● Yes  ○ No]                  [benchmark-cited ↺]
```

**Response:** D/E ratio change → instant (recalculates WACC from Kd and equity beta); tax shield toggle / debt enable toggle → ~1–3 s server-side (structural cash-flow change, Class C parameter).

---

## 6. Assumptions section: ESCALATION / CURRENCY (default collapsed)

```
▸  ESCALATION / CURRENCY                                 [↺ Reset section]

   Revenue escalation    [ 1.5  ] %/yr   tariff increase rate  [tariff-default ↺]
   OPEX escalation       [ 2.0  ] %/yr   cost inflation        [benchmark-cited ↺]
   Currency              [● CNY  ○ USD]                        [USER-set ↺]
   Exchange rate         [ 7.25  ]  CNY/USD                    [benchmark-cited ↺]
                         (shown only when USD selected)
```

**Response:** escalation changes → instant client-side (Class B). Currency toggle → instant (scales all monetary outputs).

---

## 7. Assumptions section: LIFECYCLE COSTS (default collapsed)

```
▸  LIFECYCLE COSTS                                       [↺ Reset section]

   Battery replacement   Year  [ 12  ]   Cost  [ 80  ] % of initial CAPEX
                                                         [benchmark-cited ↺]
   (additional replacement rows can be added for multi-cycle horizon)
   [+ Add replacement event]

   Major overhaul (wind)  Year  [ 10  ]   Cost  [¥ 25 M  ]  [benchmark-cited ↺]
   [+ Add overhaul event]
```

**Replacement year marker:** the year-value here drives the vertical marker on the CashFlowChart (a dotted vertical line at year 12 labelled "Batt. replace").

**Response:** lifecycle cost changes → ~1–3 s server-side (cash-flow series change, Class C).

---

## 8. Assumptions section: CAPEX / OPEX OVERRIDES (default collapsed)

```
▸  CAPEX / OPEX                                          [↺ Reset section]

   ── CAPEX BY DEVICE TYPE ─────────────────────────────────────────────────
   Wind turbines         [¥ 7 200  ] ¥/kW    × 420 MW = ¥3 024 M
                          [benchmark-cited ↺]   (CATL 2024 catalogue)
   Battery (LFP)         [¥ 1 400  ] ¥/kWh   × 300 MWh = ¥420 M
                          [benchmark-cited ↺]
   Grid connection       [¥ 120    ] ¥M       (substation; lump sum)
                          [benchmark-cited ↺]
   Soft costs            [ 8       ] %        of total CAPEX [benchmark-cited ↺]
   ─────────────────────────────────────────────────────────────────────────
   Total CAPEX (computed) ¥3 614 M                 [from server resolver]

   ── OPEX ─────────────────────────────────────────────────────────────────
   Annual OPEX           [¥ 28     ] M/yr     O&M, insurance, land rent
                          [benchmark-cited ↺]
```

**Notes:**
- All CAPEX defaults come from the benchmark library (task #63). The `[benchmark-cited ↺]` badge shows the source.
- Total CAPEX is read-only computed from the individual line items by the server resolver.
- Per-device type CAPEX rows are populated from the Device Fleet (Stage ①). If the fleet has wind + battery + grid, three rows appear. If only battery (e.g. standalone BESS), only one row.
- Grid connection CAPEX shows `[USER-set]` if the operator typed a custom value (e.g. SST premium).

**Response:** CAPEX/OPEX changes → ~1–3 s server-side (cash-flow series change, Class C).

---

## 9. Assumptions section: ACCOUNTING (default open alongside DISCOUNT RATE)

```
▾  ACCOUNTING                                            [↺ Reset section]

   View       [● View I — Absolute project  ○ View II — Battery-incremental]
   Horizon    [● 20 yr  ○ 10 yr]
   Boundary   [● Merchant  ○ Self-supply]
   Tax        [● Pre-tax  ○ Post-tax]    (post-tax requires tax rate in §5)
   Depreciation [● None  ○ Straight-line ○ MACRS]  (v2 — greyed for now)
```

**View I vs View II:**
- View I (default): absolute project economics — all revenues and costs of the full site.
- View II: battery-incremental — delta vs a hypothetical no-battery baseline. Shows "what does adding storage add/subtract?".

**Response:** View toggle, horizon, boundary, tax mode → instant client-side (all Class B — same cash-flow series, different discount arithmetic or scoping).

---

## 10. Results panel — Headline metrics (distribution-aware)

Finance results are distributions over the M-scenario weather ensemble. The headline shows the P50 (median) as the primary value with the P90 immediately beneath — the "bankability pair" that lenders and investors use. Detailed percentile breakdown and histogram are one click away.

```
┌─ HEADLINE METRICS ──────────────────────────────────────────────────────────┐
│                                                                              │
│  IRR                              NPV @ WACC                                │
│  8.2 %   ← P50 (median)          ¥142 M   ← P50                            │
│  7.6 %   ← P90 (downside)        ¥118 M   ← P90                            │
│  [▾ P50/P75/P90/P99 + hist]       [▾ P50/P75/P90/P99 + hist]               │
│                                                                              │
│  MIRR  7.1 % P50    Payback  8.3 yr P50    LCOE  ¥312/MWh P50              │
│                                            LCOS  ¥148/MWh P50 (View II)    │
│                                                                              │
│  M = 50 weather draws · 90% CI: IRR 7.4%–8.9%                              │
│  ↑ Wide IRR range — add more weather scenarios for tighter confidence bounds│
│  (hint appears only when P10–P90 spread exceeds threshold — see §Q5)        │
│                                                                              │
│  [loading state: shimmer cards while ~1–3 s server call completes]          │
└──────��───────────────────────────────���───────────────────────────────────────┘
```

**P50 / P90 semantics:**
- **P50** = median scenario. The "expected case" headline — half the M weather draws produce a better result, half worse.
- **P90** = 90th-worst-case percentile. In 90% of weather scenarios the project achieves *at least* this IRR / NPV. The bankability floor — the number a lender uses to stress-test debt service coverage. For IRR/NPV/MIRR, *higher* P90 = better; for LCOE/payback, *lower* P90 = better.

**Expandable distribution block** (`[▾ P50/P75/P90/P99 + hist]`)

Clicking the expand control on any headline metric opens an inline panel:

```
  IRR distribution (M = 50 draws)
  ───────────────────────────────────────────
  P50 (median)     8.2 %
  P75              7.9 %   (75th worst case)
  P90              7.6 %   (bankability floor)
  P99              6.9 %   (stress scenario)
  ───────────────────────────────────────────
  [histogram sparkline: M bars, x = IRR %, y = count]
  90% CI (P5–P95): 7.4 % – 8.9 %
  ───────────────────────────────────────────
  [▲ Collapse]
```

**Ensemble-size indicator:** `M = 50` appears in the headline area, always visible. If M = 1 (point-estimate, no ensemble), P90 / CI / histogram are hidden gracefully; the single-scenario value is shown without a percentile label. No error state — M = 1 is valid for quick iteration.

**Convergence hint:** if the 90% CI width exceeds a threshold (suggested: ≥ 2 pp for IRR, ≥ 20% of NPV magnitude), a subtle inline notice appears: "↑ Wide IRR range — add more weather scenarios for tighter confidence bounds." Dismissable. Threshold values to be locked in the finance contract (§Q5 below).

**Loading state:** when a Class C parameter change triggers a server-side recalculation, all metric cards show a shimmer/skeleton overlay. The assumptions panel remains fully interactive — the operator can stack multiple changes during the loading period; the backend batches them.

**Units:**
- IRR, MIRR, WACC: % (one decimal place)
- NPV: ¥M (one decimal place; negative = project destroys value)
- LCOE: ¥/MWh (no decimal)
- LCOS: ¥/MWh (View II only; hidden in View I)
- Payback: yr (one decimal)

---

## 11. AssumptionsStrip (sticky header on results side)

The AssumptionsStrip is always visible on the results panel — it does not scroll away.

```
┌─ ASSUMPTIONS ───────────────────────────────────────────────────────────────┐
│  r_f 2.85% · β 0.75 · ERP 5.50% → WACC 7.0% · 20yr · View I · Merchant   │
│  Pre-tax · Synthetic M=50 · Config #a1b2c3                                 │
│  Results: P50 IRR 8.2% · P90 7.6% · P50 NPV ¥142M                         │
│  (or, when WACC is overridden:)                                              │
│  WACC 8.0% (overridden; CAPM 7.0%) · 20yr · View I · Synthetic M=50 · ...  │
└────────────────────────────────���─────────────────────────────────────────────┘
```

When any assumption differs from its tagged default (i.e. has `[USER-set]` badge), the strip shows the value with an `*` or with the override annotation inline: `WACC 8.0% (overridden)`.

This strip is the **investment-committee guard**: it is reproduced verbatim on every export. Finance results exported without their assumptions context are not valid deliverables.

---

## 12. CashFlowChart (with percentile selector)

```
Year-by-year bar/waterfall chart, year 0 to 20.

 Scenario: [P50 ▼]  (selector: P10 / P50 / P90 / P99)

 ¥200M │
       │       ████████████████████████████
       │       ████████████████████████████
  ¥50M │       ████████████████████████████
       │       │             │     │       │
    ¥0 ├───────│─────────────│─────│───────│──────────────────────────── yr
       │  ████ │             │  ████       │     yr 12: battery replace
       │  ████ │             │             │  (dotted vertical line)
-¥800M │  ████ (yr 0: CAPEX)│             │
       │       └─────────────┘ (yr 12: batt replace cost)

  (optional range overlay when M > 1 draws:)
  ░░░░░ P25–P75 envelope (shaded, same color as bars at low opacity)
```

**Percentile selector:** `[P50 ▼]` dropdown switches the year-by-year bars to show the selected scenario's cash flows: P10 (optimistic), P50 (median, default), P90 (conservative), P99 (stress). The selected scenario's IRR and cumulative NPV are shown in a subtitle below the chart.

**Range overlay (M > 1):** when the ensemble has more than one draw, a light shaded envelope (P25–P75) can be toggled on with `[Show ±P25-P75 range]`. This shows year-by-year variability without cluttering the main bars. The envelope is hidden by default.

**Chart elements:**
- Year 0: large negative bar = CAPEX outlay (identical across scenarios — CAPEX is deterministic)
- Years 1–N: positive bars = net annual cash flow for the selected percentile scenario
- Year 12 (or configured replacement year): a notch negative bar for battery replacement cost + dotted vertical reference line with label
- Cumulative line (optional `[Show cumulative]` toggle): shows running NPV accumulation for the selected scenario

**Responsive:** chart is 100% width of the right column; minimum height 280 px.

---

## 13. NpvFanChart (replaces single-curve NpvCurveChart)

With M > 1 weather draws, the NPV-vs-rate chart becomes a **fan chart**: a median line flanked by two shaded uncertainty bands. The fan chart shows at a glance both expected performance and downside risk across the full rate spectrum.

```
NPV vs Discount Rate — fan chart (M = 50 draws)

  ¥300M │
        │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ P10-P90 band (light)
  ¥200M │ ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒ P25-P75 band (dark)
        │          ────────────────────────────────── median (P50)
  ¥100M │   ░░░░░▒▒▒▒▒────────────────────────────────────────────
        │           ▒▒────────────────────────────────────────── ·
     ¥0 ├────────────────────────────────── ●───────────────────── rate %
        │                           P90 IRR  ●(P50 IRR = 8.2%)
 -¥100M │                         = 7.6%
        └─────────────────────────────────────────────────────────
          3%     5%    7%(WACC)   9%    11%    13%    15%
                       ↑ WACC ref
```

**Fan chart elements:**
- **Median line (P50)**: solid blue line; thicker weight. Live-updated as WACC override slider moves.
- **P25–P75 band**: medium-opacity shaded area (blue, ~30% opacity); "most likely" band — 50% of scenarios fall within it.
- **P10–P90 band**: low-opacity shaded area (blue, ~15% opacity); "uncertainty envelope" — 80% of scenarios fall within it.
- **P50 IRR marker**: circle at P50 IRR x-intercept + label `"P50 IRR 8.2%"`.
- **P90 IRR marker**: smaller circle at P90 IRR x-intercept + label `"P90 7.6%"` (both together form the bankability pair axis-markers).
- **Current WACC**: vertical dotted reference line.
- **Hover tooltip**: shows P10/P50/P90 NPV simultaneously at the cursor rate.

**Rate-slider interactivity:** when M cached cash-flow series are held client-side, adjusting the WACC override slider re-discounts all M series instantly (< 50 ms) — the fan animates live. This is the same Class B instant re-discount path as the single-curve version; no server call required.

**M = 1 graceful fallback:** when M = 1 (point estimate), the chart renders as the original single-curve NpvCurveChart (no bands, single line). The component detects M from the result payload and renders accordingly.

---

## 14. TornadoChart

```
Sensitivity: ±ΔNPV for ±10% change in each input.

  Ranking (most sensitive → least):
  Revenue escalation   ████████████████████░░░░░░░░░░  +¥48M / -¥44M
  WACC                 ████████████████░░░░░░░░░░░░░░  +¥35M / -¥39M
  CAPEX                ████████████░░░░░░░░░░░░░░░░░░  +¥32M / -¥32M
  OPEX escalation      ████████░░░░░░░░░░░░░░░░░░░░░░  +¥18M / -¥17M
  Battery replacement  ██████░░░░░░░░░░░░░░░░░░░░░░░░  +¥14M / -¥13M
  ...
```

Tornado chart shows top-8 sensitivity drivers by |ΔNPV|. `[Show all]` expands to show all parameters. Values shown are ±10% shock on each parameter, all else equal. This is a pre-computed sensitivity table from the server; it does not re-run the full simulation per bar.

**Response:** Tornado is computed server-side as part of the initial finance projection (same `POST /api/finance/run` call). It does not update in real-time as the operator adjusts assumptions — that would require re-running N sensitivity scenarios. The tornado updates only when `[Refresh sensitivity]` is clicked or after any Class C parameter change (server-side recalculation).

---

## 15. Eval basis picker

At the very top of the left column (above the assumptions panel), a compact strip shows the selected eval result:

```
┌─ EVAL BASIS ────────────────────────────────────────────────────────────────┐
│  SAC run-a1b2c3 (best ckpt, step 1.8M) · config #a1b2c3  [Change ▼]       │
│  ✓ Eval config matches current wizard config                                │
│                                                                              │
│  (or, when they don't match:)                                                │
│  ℹ  Eval was run against config #a1b2c3; current wizard config is #e5f6a7. │
│     Finance reflects that eval's results. This is expected after config     │
│     changes in Stage ①.                                                     │
└───��───────────────────────────────────────────────────────────���──────────────┘
```

`[Change ▼]` opens a dropdown listing all COMPLETE eval results from Stage ④. Selecting a different result triggers a full server-side finance recalculation from the new operating data (~2–5 s). Assumptions are preserved; only the operating cash-flow inputs change.

**If Stage ⑤ was entered via `[→ Finance]` from Stage ④:** the eval basis is pre-selected and the picker is pre-populated. If the operator entered Stage ⑤ directly (e.g. via WizardBar click), the picker shows the most recent eval result by default but shows a `"Change ▼"` to override.

---

## 16. Footer

```
[← Back to Eval]     [+ Add to Comparison]     [Export results + assumptions ▾]
```

### 16.1 [← Back to Eval]
Always enabled. Navigates to Stage ④ without discarding assumptions (assumptions are persisted server-side as part of the finance config).

### 16.2 [+ Add to Comparison]
Enabled always (Finance stage has results by definition at COMPLETE state). Opens `AddToComparisonModal` with the full `(eval_result_id, policy_id, config_hash, finance_snapshot)` tuple.

If the user has unsaved assumption overrides (has edited something but the server call is in flight), the modal says: `"Computing results… Add to comparison after the current calculation completes?"` with a `[Wait & Add]` option that queues the add.

### 16.3 [Export results + assumptions ▾]
Opens an export dropdown:
```
  Export as CSV (results + assumptions block)
  Export as PDF (formatted — v2)
```

CSV includes: headline metrics, year-by-year cash flows, NPV vs rate table (3%–15%), sensitivity inputs, **and the full current assumptions as a structured block**. The assumptions block is identical in content to the AssumptionsStrip — results without assumptions are not a valid deliverable.

---

## 17. Loading states and optimistic updates

| User action | Response behaviour |
|-------------|-------------------|
| Change r_f / β / ERP / WACC override / View I⇔II / horizon / currency | Instant (<50 ms) — client-side re-discount of **M cached cash-flow series** (all M draws). Fan chart bands re-render live as slider moves. No loading state. |
| Change D/E ratio → WACC recompute | Instant — WACC = (D/V)×Kd×(1−t) + (E/V)×Ke; client-side. |
| Toggle tax shield / debt enable/disable | ~1–3 s — structural cash-flow change. Loading shimmer on headline metrics only. Assumptions panel remains interactive. |
| Change CAPEX / OPEX / lifecycle costs | ~1–3 s — server-side cash-flow series change. Same shimmer. |
| Change eval basis | ~2–5 s — full server-side recalculate from new operating data. Full-results shimmer. AssumptionsStrip updates immediately with new config hash. |

**Optimistic stacking:** the operator can keep adjusting while a server call is in flight. The frontend queues the latest parameter set and fires a new server call when the current one completes. Intermediate calls are debounced (no parallel requests); the spinner on the headline metrics stays visible until the final result arrives.

---

## 18. PENDING state (no eval basis selected)

When the user arrives at Stage ⑤ for the first time with no pre-selected eval result:

```
┌─ EVAL BASIS ────────────────────────────────────────────────────────────────┐
│  No eval result selected.                                                   │
│  [Select eval result ▼]   ← dropdown with all Stage ④ COMPLETE results    │
└──────────────────────────────────────────────────────────────────────────────┘
```

The assumptions panel is shown but all results are blank/pending. Once an eval result is selected, the finance projection runs and the PENDING state resolves.

---

## 19. Accessibility notes

- Assumptions panel sections: each section is a `<details>/<summary>` pattern (native expand/collapse with `aria-expanded`).
- CAPM override slider: `role="slider"` with `aria-valuemin`, `aria-valuemax`, `aria-valuenow`, `aria-label="WACC override"`.
- `[↺ Reset section]` buttons: `aria-label="Reset Discount Rate section to defaults"` (section name included).
- Loading states: `aria-busy="true"` on the results panel while server calls are in flight; an `aria-live="polite"` region announces when results update.
- TornadoChart: summary table accessible via `[View as table]` toggle on the chart (shows the same data as the chart in a plain `<table>`).
- CashFlowChart: `[View as table]` toggle available.
- NpvCurveChart: hover tooltip also activates on keyboard focus (arrow keys navigate along the curve).
- Color-not-only: positive NPV → green + `▲` symbol; negative → red + `▼`; not color alone.

---

## 20. Component checklist

| Component | Role |
|-----------|------|
| `WizardBar` | Shared |
| `StageShell` | Shared |
| `FinanceAssumptionsPanel` | New: six collapsible sections, provenance badges, ↺ reset; the full assumptions editor |
| `CAPMBuilder` | New (within DISCOUNT RATE section): r_f/β/ERP → WACC build-up, tenor picker, override slider, Restore CAPM |
| `AssumptionField` | New primitive: editable control + provenance badge + ↺ reset; used throughout |
| `AssumptionsStrip` | New: sticky one-liner summary on results side; reproduced on every export |
| `CashFlowChart` | New: year-by-year bar/waterfall with replacement markers + percentile selector + P25-P75 range overlay |
| `NpvFanChart` | New: NPV vs discount rate fan chart — median line + P25-P75 + P10-P90 bands + dual IRR markers (P50/P90); degrades to single-curve when M=1 |
| `MetricDistributionPopover` | New: expandable percentile table (P50/P75/P90/P99) + histogram sparkline; used inside each headline metric card |
| `EnsembleSizeIndicator` | New primitive: `M = N` badge + convergence hint; shown in headline area |
| `TornadoChart` | New: sensitivity bar chart ±ΔNPV, ranked |
| `AddToComparisonModal` | Shared (from comparison_workbench.md §6) |
| `StageSaveButton` | Shared primitive (used as [Export] button in this stage) |

---

## 21. Open questions

**Q1 — LCOS in View I:** Should LCOS (¥/MWh, battery specific) appear in View I results? It's a battery-specific metric; View II (battery-incremental) is the natural home. For v1: show LCOS in both views but label it clearly as "battery only" in View I. Flag in contract.

**Q2 — Post-tax NPV vs pre-tax NPV:** The Accounting section has a `Pre-tax / Post-tax` toggle. When post-tax is selected, IRR and NPV change significantly. Should post-tax require the Capital Structure section to be expanded? Current design: yes — enabling post-tax checks that tax rate field in Capital Structure is set; if it's at the default, shows a notice: "Using default tax rate 25% — edit in Capital Structure if needed." Flag in contract.

**Q3 — Sensitivity tornado refresh:** The tornado does not auto-refresh on every assumption change (that would require N server calls). Should there be a `[Refresh sensitivity]` button, or should the tornado update only after Class C changes (which already trigger a server call)? Current design: tornado updates after any Class C change (since the server is already called); no manual refresh button needed for Class B changes (assumption is that tornado is relatively insensitive to discount-rate changes). Flag in contract.

**Q4 — Finance config persistence:** Are the assumptions saved automatically (on every change) or only on explicit save? Current design: assumptions auto-save to the server on every server-side call (Class C). Class B changes are in-memory only until the user navigates away or exports — at which point a `POST /api/finance/assumptions` saves the final state. Flag in serving contract.

**Q5 — §13 field-name alignment:** finance-expert is drafting §13 (project-finance REBUILD_SPEC section, task #72). Before the frontend contract is written, the metric field names in this doc (IRR, MIRR, NPV, LCOE, LCOS, P50/P90 labels, percentile payload keys) must be reconciled with §13's numerical spec. **This reconciliation is a gate on the frontend contract** — the contract must reference §13 field names, not informal labels from this design doc.

**Q6 — Convergence-hint thresholds:** What P10–P90 spread width triggers the "wide CI" convergence hint? Suggested: ≥ 2 pp for IRR, ≥ 20% of P50-NPV magnitude for NPV. finance-expert should lock these values in §13 or the finance contract so they are not hardcoded in the frontend.

**Q7 — Client-side M-series memory:** With M = 50 weather draws, the client holds M full year-by-year cash-flow series for instant Class B re-discounting. At 20 years × 50 draws × ~6 metrics per year, this is ~6 000 floats ≈ trivial. At M = 500, still ≤ 60 000 floats. Document the upper bound in the serving contract response schema so the frontend can size its memory budget.

---

*docs/design/ux/stage_5_finance.md — ui-designer, task #65 — v0.1 2026-06-12 (initial per-screen layout: two-column assumptions+results, all six assumption sections, AssumptionsStrip, headline metrics, CashFlowChart, NpvCurveChart, TornadoChart, eval basis picker, loading states, export, a11y notes, component checklist, 4 open questions) · v0.2 2026-06-12 (USER directive: distribution-aware results — P50/P90 bankability pair headline, expandable percentile table + histogram, NpvCurveChart → NpvFanChart (median + P25-P75 + P10-P90 bands), CashFlowChart + percentile selector + P25-P75 range overlay, ensemble-size M= indicator, convergence-hint affordance, instant M-series client-side re-discount clarified, AssumptionsStrip shows M=N, 3 new open questions, §13 alignment gate)*
