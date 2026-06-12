# Review record — `design_system` (PR #98)

**Reviewer:** frontend-reviewer · **Stage:** contract + tests gate (contract-first-dev step 3)
**Date:** 2026-06-12 · **Head reviewed:** `c860a96` · **Verdict:** REQUEST_CHANGES

## Verified
- **Hex cross-check (prime directive) — PASS.** Every hex in all four source files maps to a
  contract token with the EXACT value; none dropped (style.css 16, touColors.ts 12, SocTimeline
  4, MetricCurves 8). Centralization preserves the palette exactly.
- **Contrast helper math — correct WCAG 2.1.** Computed all 8 pairs exactly; every pair passes
  its asserted threshold: body-on-app 15.31, body-on-surface 12.46, muted-on-app 7.36,
  muted-on-nav 6.40, faint-on-surface 3.23, active-link-on-nav 6.46, error-text 9.00,
  error-border 6.17.
- Pre-existing fixes at this head: `c860a96` added the missing `beforeAll` import (real bug);
  `c1286f4` corrected the faint comment from ~2.87 to ~3.44 (still off — true 3.227 — and still
  asserts the large-text exemption; see finding #1).

## Findings
1. **[MUST-FIX] Card-title pair misclassified as "large text".** `--text-faint #64748b` on
   `--bg-surface #1e2533` is `.card__title` at 0.75rem=12px / weight 600 = NORMAL text (WCAG
   large = >=24px or >=18.66px bold). It computes 3.23:1 — meets 3:1 but FAILS AA-normal 4.5:1.
   §7's blanket "meets WCAG AA" claim + the suite-4 "large/uppercase" comment rely on a
   large-text exemption that doesn't apply. No-redesign PR, so the color stays — but the contract
   must DOCUMENT this as a known sub-AA-normal pair (future a11y pass), not claim AA for it.
2. **[SHOULD-FIX] Contract prose doesn't specify the exports the tests require.** Suite 6 needs
   `MetricCurves` to export `PANELS: {key,color}[]`; suite 7 needs `SocTimeline` to export
   `SOC_LINE_COLOR`/`SOC_BOUNDS_COLOR`/`SOC_BAND_BG`. §8 only says "replace inline hex." Amend
   §6/§8 to specify these exports + the PANELS shape (answers the PANELS/SocTimeline question).
3. **[SHOULD-FIX] §7 approximations + remaining suite-4 comments inaccurate.** body-on-surface
   ~9.1 vs true 12.46; faint comment ~3.44 vs true 3.227; etc. Correct to the exact values above.
4. **[MINOR] §3.4 `--accent-blue` usage lists "SOC line"** — the SOC line is `--chart-soc
   #3b82f6`, not accent-blue. Remove.
5. **[MINOR] `--accent-grey #4b5563` has no current source usage** (forward-looking, wizard
   LOCKED state from wizard_flow §10) — note it's forward, not codified-from-source.
6. **[MINOR] Suite-5 style.css no-bare-hex doesn't strip CSS `/* */` comments** (the .ts cases
   do) — a hex in a CSS comment would false-fail.

## Reviewer tests added (`// reviewer:`)
- exact-contrast pinning of all 8 ratios + the card-title sub-AA-normal assertion (>=3:1, <4.5:1).
- pre-refactor source-hex coverage (31-hex set must all survive in TOKEN).
- style.css no-bare-hex with CSS-comment stripping.

**Verdict: REQUEST_CHANGES** — resolve #1 (honest a11y classification) + #2 (specify required
exports); apply #3 and the minors. Hex values + test structure otherwise excellent.
