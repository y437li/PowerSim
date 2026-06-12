# Contract: `design_system` — Design Tokens & Style Guide

**Area:** `frontend`
**Feature file:** `contracts/frontend/design_system.md`
**Branch:** `feat/frontend-design-system`
**Task:** #59
**Status:** DRAFT — awaiting frontend-reviewer approval

---

## 1. Purpose

Codify the **existing** Energy GO dark engineering-dashboard aesthetic as a formal design system.
The contract does NOT redesign anything — it documents and centralises what already exists in
`src/style.css` (140 lines), `src/utils/touColors.ts`, and scattered inline style props, then
migrates those values to CSS custom properties (`src/styles/tokens.css`) so that:

1. Every consumer (dashboard, 3D scene HUD, future wizard UI) reads from one canonical source.
2. Adding a new component never re-invents a hex color.
3. Contrast ratios are documented and enforced in tests.

**Design authority post-merge:** `ui-designer` becomes the maintainer of this contract.
Visual-evolution proposals from `ui-designer` (gradients, slider ranges, etc.) are **OUT OF SCOPE**
for this contract and must land in a separate PR with USER review.

---

## 2. Deliverables

| File | Action | Note |
|---|---|---|
| `contracts/frontend/design_system.md` | NEW (this file) | The contract |
| `tests/frontend/design_system.test.tsx` | NEW | Test suite (fails until impl) |
| `src/styles/tokens.css` | NEW | CSS custom properties — the single source of truth |
| `src/style.css` | REFACTOR | Replace all hex literals with `var(--token)` — **no visual change** |
| `src/utils/touColors.ts` | REFACTOR | Map values to token constants — **no visual change** |
| `src/components/live/SocTimeline.tsx` | REFACTOR | Replace inline hex with token constants — **no visual change** |
| `src/components/training/MetricCurves.tsx` | REFACTOR | Replace inline hex with token constants — **no visual change** |

---

## 3. Token Catalogue

### 3.1 Background tokens

| CSS custom property | Value | Usage |
|---|---|---|
| `--bg-app` | `#0f1117` | `body` background, outermost shell |
| `--bg-surface` | `#1e2533` | Card / panel background (`.card`) |
| `--bg-nav` | `#1a1f2e` | Top nav bar, wizard bar |
| `--bg-error` | `#2d1515` | Error boundary fallback background |

### 3.2 Border tokens

| CSS custom property | Value | Usage |
|---|---|---|
| `--border-default` | `#2d3748` | Card borders, table rules, nav bottom |

### 3.3 Text tokens

| CSS custom property | Value | Usage |
|---|---|---|
| `--text-primary` | `#e2e8f0` | Body text (default `color`) |
| `--text-muted` | `#94a3b8` | Secondary labels, inactive nav links, time axis |
| `--text-faint` | `#64748b` | Card titles (`.card__title`), placeholders, 404 page |

### 3.4 Accent / status tokens

| CSS custom property | Value | Usage |
|---|---|---|
| `--accent-blue` | `#60a5fa` | Active nav links, PENDING wizard state, SOC line |
| `--accent-green` | `#22c55e` | COMPLETE wizard state, SOC bounds lines |
| `--accent-amber` | `#f59e0b` | STALE/IN_PROGRESS wizard state, warnings, critic-loss chart line |
| `--accent-red` | `#f87171` | Hard errors — border; also error boundary border |
| `--accent-error-text` | `#fca5a5` | Error boundary text, error message color |
| `--accent-grey` | `#4b5563` | LOCKED wizard state |

### 3.5 TOU tier tokens

Each TOU tier has three sub-tokens: `bg`, `text`, `border`.

| CSS custom property | Value | Tier | Role |
|---|---|---|---|
| `--tou-critical-peak-bg` | `#fee2e2` | critical_peak | Background |
| `--tou-critical-peak-text` | `#991b1b` | critical_peak | Text |
| `--tou-critical-peak-border` | `#f87171` | critical_peak | Border |
| `--tou-peak-bg` | `#fef3c7` | peak | Background |
| `--tou-peak-text` | `#92400e` | peak | Text |
| `--tou-peak-border` | `#fcd34d` | peak | Border |
| `--tou-mid-bg` | `#dbeafe` | mid | Background |
| `--tou-mid-text` | `#1e40af` | mid | Text |
| `--tou-mid-border` | `#93c5fd` | mid | Border |
| `--tou-valley-bg` | `#dcfce7` | valley | Background |
| `--tou-valley-text` | `#166534` | valley | Text |
| `--tou-valley-border` | `#86efac` | valley | Border |

### 3.6 Recharts series palette

Used exclusively for training-metric chart lines (one color per series). These are tokens, not
inline hex. Each series name is a semantic label; the underlying color is the value.

| CSS custom property | Value | Series |
|---|---|---|
| `--chart-actor` | `#6366f1` | Actor Loss |
| `--chart-critic` | `#f59e0b` | Critic Loss (same as `--accent-amber`) |
| `--chart-entropy` | `#10b981` | Entropy Coefficient |
| `--chart-reward` | `#3b82f6` | Reward (scaled) |
| `--chart-cost` | `#ef4444` | Episode Cost (negative-allowed series) |
| `--chart-soc` | `#3b82f6` | SOC timeline line (same as `--chart-reward`) |
| `--chart-grid` | `#e5e7eb` | Recharts CartesianGrid stroke |
| `--chart-axis` | `#9ca3af` | Recharts axis tick / label stroke |
| `--chart-axis-label` | `#6b7280` | Recharts axis label fill |

### 3.7 Typography scale

Not CSS tokens (Tailwind/system-ui doesn't use them), but documented as the authoritative
reference values.

| Role | `font-size` | `font-weight` | Notes |
|---|---|---|---|
| Body text | `system-ui` default (~16px) | 400 | `body` element |
| Nav links | `0.9rem` | 500 | `.nav-link` |
| Card title | `0.75rem` | 600 | `.card__title`; uppercase + `letter-spacing: 0.08em` |
| Time axis | `0.85rem` | 400 | `.time-axis` |
| TOU badge | `0.75rem` | 600 | `.tou-badge` |
| Small detail | `0.75rem` | 400 | `.error-boundary-fallback__detail` |

### 3.8 Spacing scale

Documented reference values (not converted to tokens in v1 — scope of a future PR).

| Usage | Value |
|---|---|
| Nav padding | `0.75rem 1.5rem` |
| Card padding | `1rem` |
| Card margin-bottom | `1rem` |
| Card border-radius | `8px` |
| App main padding | `1.5rem` |
| Gap between nav items | `1rem` |
| TOU badge padding | `0.25rem 0.5rem` |
| TOU badge gap | `0.25rem` |

---

## 4. File: `src/styles/tokens.css`

Exactly one CSS file declares all custom properties on `:root`.

```css
/* Energy GO — design tokens (single source of truth) */
:root {
  /* Backgrounds */
  --bg-app:        #0f1117;
  --bg-surface:    #1e2533;
  --bg-nav:        #1a1f2e;
  --bg-error:      #2d1515;

  /* Borders */
  --border-default: #2d3748;

  /* Text */
  --text-primary:  #e2e8f0;
  --text-muted:    #94a3b8;
  --text-faint:    #64748b;

  /* Accent / status */
  --accent-blue:        #60a5fa;
  --accent-green:       #22c55e;
  --accent-amber:       #f59e0b;
  --accent-red:         #f87171;
  --accent-error-text:  #fca5a5;
  --accent-grey:        #4b5563;

  /* TOU tiers */
  --tou-critical-peak-bg:     #fee2e2;
  --tou-critical-peak-text:   #991b1b;
  --tou-critical-peak-border: #f87171;
  --tou-peak-bg:              #fef3c7;
  --tou-peak-text:            #92400e;
  --tou-peak-border:          #fcd34d;
  --tou-mid-bg:               #dbeafe;
  --tou-mid-text:             #1e40af;
  --tou-mid-border:           #93c5fd;
  --tou-valley-bg:            #dcfce7;
  --tou-valley-text:          #166534;
  --tou-valley-border:        #86efac;

  /* Recharts series palette */
  --chart-actor:      #6366f1;
  --chart-critic:     #f59e0b;
  --chart-entropy:    #10b981;
  --chart-reward:     #3b82f6;
  --chart-cost:       #ef4444;
  --chart-soc:        #3b82f6;
  --chart-grid:       #e5e7eb;
  --chart-axis:       #9ca3af;
  --chart-axis-label: #6b7280;
}
```

**Rules:**
- This file is `@import`-ed at the top of `src/style.css` (before any other declarations).
- No other file declares `:root` color tokens.
- `src/style.css` replaces all hex literals with `var(--token)` — see §5.
- TypeScript/TSX files that need token values import from `src/styles/tokenValues.ts` — see §6.

---

## 5. Refactored `src/style.css` — contract rules

After the refactor, `src/style.css`:

- `@import`s `./styles/tokens.css` as its first line.
- Contains **zero** bare hex color literals (grep test: `/#[0-9a-fA-F]{3,6}/` must produce 0 hits in
  `style.css` after the import line).
- All colors reference `var(--token-name)`.
- Visual output is **byte-for-byte identical** to pre-refactor (computed values are unchanged).

---

## 6. TypeScript token mirror: `src/styles/tokenValues.ts`

For TypeScript consumers that need token values at runtime (Recharts `stroke=`, inline `style=` in
test environments that don't parse CSS), a typed mirror exports the same values:

```typescript
// src/styles/tokenValues.ts — generated from tokens.css; DO NOT hand-edit hex here.
export const TOKEN = {
  bgApp:       "#0f1117",
  bgSurface:   "#1e2533",
  bgNav:       "#1a1f2e",
  bgError:     "#2d1515",
  borderDefault: "#2d3748",
  textPrimary: "#e2e8f0",
  textMuted:   "#94a3b8",
  textFaint:   "#64748b",
  accentBlue:  "#60a5fa",
  accentGreen: "#22c55e",
  accentAmber: "#f59e0b",
  accentRed:   "#f87171",
  accentErrorText: "#fca5a5",
  accentGrey:  "#4b5563",
  touCriticalPeakBg:     "#fee2e2",
  touCriticalPeakText:   "#991b1b",
  touCriticalPeakBorder: "#f87171",
  touPeakBg:     "#fef3c7",
  touPeakText:   "#92400e",
  touPeakBorder: "#fcd34d",
  touMidBg:      "#dbeafe",
  touMidText:    "#1e40af",
  touMidBorder:  "#93c5fd",
  touValleyBg:   "#dcfce7",
  touValleyText: "#166534",
  touValleyBorder: "#86efac",
  chartActor:      "#6366f1",
  chartCritic:     "#f59e0b",
  chartEntropy:    "#10b981",
  chartReward:     "#3b82f6",
  chartCost:       "#ef4444",
  chartSoc:        "#3b82f6",
  chartGrid:       "#e5e7eb",
  chartAxis:       "#9ca3af",
  chartAxisLabel:  "#6b7280",
} as const;

export type TokenKey = keyof typeof TOKEN;
```

**Rules:**
- `touColors.ts` must import `TOKEN` from this file and return `TOKEN.touXxxYyy` values — no
  independent hex strings in `touColors.ts` after the refactor.
- Recharts `stroke=` / `fill=` props in `MetricCurves.tsx` and `SocTimeline.tsx` must reference
  `TOKEN.chartXxx` — no bare hex.
- `tokenValues.ts` and `tokens.css` must be kept in sync (enforced by the token-sync test — see §7).

---

## 7. Contrast minimums

All text-on-background pairs must meet WCAG AA (4.5:1 for normal text, 3:1 for large text).
The following are the critical pairs; the test suite asserts the computed ratios.

| Foreground | Background | Pair name | Min ratio | Computed approx |
|---|---|---|---|---|
| `--text-primary` `#e2e8f0` | `--bg-app` `#0f1117` | body-on-app | 4.5:1 | ~12.0:1 |
| `--text-primary` `#e2e8f0` | `--bg-surface` `#1e2533` | body-on-surface | 4.5:1 | ~9.1:1 |
| `--text-muted` `#94a3b8` | `--bg-app` `#0f1117` | muted-on-app | 4.5:1 | ~5.6:1 |
| `--text-muted` `#94a3b8` | `--bg-nav` `#1a1f2e` | muted-on-nav | 4.5:1 | ~5.1:1 |
| `--text-faint` `#64748b` | `--bg-surface` `#1e2533` | faint-on-surface | 3:1 (large) | ~3.4:1 |
| `--accent-blue` `#60a5fa` | `--bg-nav` `#1a1f2e` | active-link-on-nav | 3:1 (large) | ~5.0:1 |
| `--accent-red` `#f87171` | `--bg-error` `#2d1515` | error-on-error-bg | 3:1 (large) | ~4.8:1 |

---

## 8. Component inventory

Components that exist and MUST be updated to use tokens (no new components created in this PR):

| Component / file | Tokens used | Change |
|---|---|---|
| `src/style.css` | All layout/structural tokens | Replace hex with `var()` |
| `src/utils/touColors.ts` | `--tou-*` tokens via `TOKEN.*` | Import from `tokenValues.ts` |
| `src/components/live/SocTimeline.tsx` | `--chart-soc`, `--accent-green`, `--tou-valley-bg` | Replace inline hex |
| `src/components/training/MetricCurves.tsx` | `--chart-*` | Replace inline hex |

---

## 9. What's out of scope

- Visual redesign: no color values change — only centralization.
- New components: wizard components (`WizardBar`, `StageShell`, etc.) are NOT in this PR.
- Spacing tokens: spacing/sizing as CSS custom properties are deferred to a follow-on PR.
- Dark-mode toggle: single dark theme only.
- Proposed visual evolution from `ui-designer` (gradient borders, slider markings): OUT until
  separate USER review.
- TOU colors are currently light-background (light tier badges on the dark app). They are carried
  forward as-is; a dark-theme badge variant is out of scope for this PR.

---

## 10. Deliberate deviations

None. This contract introduces no behavioral changes — it is a pure centralization refactor.

---

## 11. Failure modes covered by the test suite

- `tokenValues.ts` and `tokens.css` drift apart (token-sync test).
- A refactored file re-introduces a bare hex literal (structural invariant test).
- `touColors.ts` returns wrong values after refactor (regression test vs. pre-refactor snapshot).
- Contrast ratio falls below minimum (contrast test).
- `TOKEN` export is missing a key that `tokens.css` declares (completeness test).
