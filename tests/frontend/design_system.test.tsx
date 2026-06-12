/**
 * Tests for contracts/frontend/design_system.md
 *
 * These tests verify:
 *  1. TOKEN export completeness and value correctness (§3 + §6)
 *  2. tokens.css / tokenValues.ts sync (§6, last rule)
 *  3. touColors.ts uses TOKEN values exclusively (§6)
 *  4. WCAG AA contrast minimums for every critical pair (§7)
 *  5. Structural: no bare hex literals in refactored source files (§5)
 *  6. MetricCurves PANELS use TOKEN chart-series values (§3.6)
 *  7. SocTimeline inline props use TOKEN values (§3.6)
 *
 * Tests FAIL until implementation is complete — that is correct at contract+tests stage.
 */
import { describe, it, expect, beforeAll } from "vitest";
import * as fs from "fs";
import * as path from "path";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Parse a hex string (#rrggbb or #rgb) → { r, g, b } in 0–255. */
function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace("#", "");
  if (h.length === 3) {
    return {
      r: parseInt(h[0] + h[0], 16),
      g: parseInt(h[1] + h[1], 16),
      b: parseInt(h[2] + h[2], 16),
    };
  }
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}

/** sRGB linearisation per WCAG 2.1 formula. */
function linearise(c8: number): number {
  const c = c8 / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** WCAG relative luminance. */
function luminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const R = linearise(r);
  const G = linearise(g);
  const B = linearise(b);
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

/** WCAG contrast ratio (≥ 1). */
function contrast(fg: string, bg: string): number {
  const L1 = luminance(fg);
  const L2 = luminance(bg);
  const lighter = Math.max(L1, L2);
  const darker  = Math.min(L1, L2);
  return (lighter + 0.05) / (darker + 0.05);
}

/** Read a source file relative to repo root; trim + return content. */
function readSrc(relPath: string): string {
  const abs = path.resolve(__dirname, "../../", relPath);
  return fs.readFileSync(abs, "utf8");
}

/** Parse all `--token: value;` declarations from a CSS string. Returns { name: value }. */
function parseCssTokens(css: string): Record<string, string> {
  const tokens: Record<string, string> = {};
  const re = /(--[\w-]+)\s*:\s*([^;]+);/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css)) !== null) {
    tokens[m[1].trim()] = m[2].trim();
  }
  return tokens;
}

// ---------------------------------------------------------------------------
// 1. TOKEN export — completeness and value correctness
// ---------------------------------------------------------------------------
describe("TOKEN export (src/styles/tokenValues.ts)", () => {
  let TOKEN: Record<string, string>;

  // Dynamically import at test time (fails until file exists — correct).
  beforeAll(async () => {
    const mod = await import("../../src/styles/tokenValues");
    TOKEN = mod.TOKEN as Record<string, string>;
  });

  // §3.1 background tokens
  it("bgApp = #0f1117", () => expect(TOKEN.bgApp).toBe("#0f1117"));
  it("bgSurface = #1e2533", () => expect(TOKEN.bgSurface).toBe("#1e2533"));
  it("bgNav = #1a1f2e", () => expect(TOKEN.bgNav).toBe("#1a1f2e"));
  it("bgError = #2d1515", () => expect(TOKEN.bgError).toBe("#2d1515"));

  // §3.2 border token
  it("borderDefault = #2d3748", () => expect(TOKEN.borderDefault).toBe("#2d3748"));

  // §3.3 text tokens
  it("textPrimary = #e2e8f0", () => expect(TOKEN.textPrimary).toBe("#e2e8f0"));
  it("textMuted = #94a3b8", () => expect(TOKEN.textMuted).toBe("#94a3b8"));
  it("textFaint = #64748b", () => expect(TOKEN.textFaint).toBe("#64748b"));

  // §3.4 accent tokens
  it("accentBlue = #60a5fa", () => expect(TOKEN.accentBlue).toBe("#60a5fa"));
  it("accentGreen = #22c55e", () => expect(TOKEN.accentGreen).toBe("#22c55e"));
  it("accentAmber = #f59e0b", () => expect(TOKEN.accentAmber).toBe("#f59e0b"));
  it("accentRed = #f87171", () => expect(TOKEN.accentRed).toBe("#f87171"));
  it("accentErrorText = #fca5a5", () => expect(TOKEN.accentErrorText).toBe("#fca5a5"));
  it("accentGrey = #4b5563", () => expect(TOKEN.accentGrey).toBe("#4b5563"));

  // §3.5 TOU tier tokens
  it("touCriticalPeakBg = #fee2e2", () => expect(TOKEN.touCriticalPeakBg).toBe("#fee2e2"));
  it("touCriticalPeakText = #991b1b", () => expect(TOKEN.touCriticalPeakText).toBe("#991b1b"));
  it("touCriticalPeakBorder = #f87171", () => expect(TOKEN.touCriticalPeakBorder).toBe("#f87171"));
  it("touPeakBg = #fef3c7", () => expect(TOKEN.touPeakBg).toBe("#fef3c7"));
  it("touPeakText = #92400e", () => expect(TOKEN.touPeakText).toBe("#92400e"));
  it("touPeakBorder = #fcd34d", () => expect(TOKEN.touPeakBorder).toBe("#fcd34d"));
  it("touMidBg = #dbeafe", () => expect(TOKEN.touMidBg).toBe("#dbeafe"));
  it("touMidText = #1e40af", () => expect(TOKEN.touMidText).toBe("#1e40af"));
  it("touMidBorder = #93c5fd", () => expect(TOKEN.touMidBorder).toBe("#93c5fd"));
  it("touValleyBg = #dcfce7", () => expect(TOKEN.touValleyBg).toBe("#dcfce7"));
  it("touValleyText = #166534", () => expect(TOKEN.touValleyText).toBe("#166534"));
  it("touValleyBorder = #86efac", () => expect(TOKEN.touValleyBorder).toBe("#86efac"));

  // §3.6 chart palette tokens
  it("chartActor = #6366f1", () => expect(TOKEN.chartActor).toBe("#6366f1"));
  it("chartCritic = #f59e0b", () => expect(TOKEN.chartCritic).toBe("#f59e0b"));
  it("chartEntropy = #10b981", () => expect(TOKEN.chartEntropy).toBe("#10b981"));
  it("chartReward = #3b82f6", () => expect(TOKEN.chartReward).toBe("#3b82f6"));
  it("chartCost = #ef4444", () => expect(TOKEN.chartCost).toBe("#ef4444"));
  it("chartSoc = #3b82f6", () => expect(TOKEN.chartSoc).toBe("#3b82f6"));
  it("chartGrid = #e5e7eb", () => expect(TOKEN.chartGrid).toBe("#e5e7eb"));
  it("chartAxis = #9ca3af", () => expect(TOKEN.chartAxis).toBe("#9ca3af"));
  it("chartAxisLabel = #6b7280", () => expect(TOKEN.chartAxisLabel).toBe("#6b7280"));

  // No bare hex values may exist as non-token values in TOKEN (all values must be hex strings
  // matching the catalogue — ensures nothing was added with a wrong value type).
  it("all TOKEN values are valid #rrggbb or #rgb hex strings", () => {
    for (const [key, val] of Object.entries(TOKEN)) {
      expect(
        /^#[0-9a-fA-F]{3}$|^#[0-9a-fA-F]{6}$/.test(val),
        `TOKEN.${key} = "${val}" is not a valid hex color`
      ).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// 2. tokens.css / tokenValues.ts sync
// ---------------------------------------------------------------------------
describe("tokens.css ↔ tokenValues.ts sync (§6)", () => {
  it("every CSS custom property in tokens.css has a matching TOKEN key", async () => {
    const css = readSrc("src/styles/tokens.css");
    const cssTokens = parseCssTokens(css);

    const mod = await import("../../src/styles/tokenValues");
    const TOKEN = mod.TOKEN as Record<string, string>;

    // Build a camelCase map from CSS --token-name → tokenName
    function cssNameToCamel(cssName: string): string {
      // Remove leading --
      return cssName.replace(/^--/, "").replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    }

    for (const cssName of Object.keys(cssTokens)) {
      const camel = cssNameToCamel(cssName);
      expect(TOKEN, `CSS token ${cssName} has no TOKEN.${camel}`).toHaveProperty(camel);
    }
  });

  it("every TOKEN key maps to a CSS custom property in tokens.css", async () => {
    const css = readSrc("src/styles/tokens.css");
    const cssTokens = parseCssTokens(css);

    const mod = await import("../../src/styles/tokenValues");
    const TOKEN = mod.TOKEN as Record<string, string>;

    function camelToCssName(camel: string): string {
      return "--" + camel.replace(/([A-Z])/g, (c) => "-" + c.toLowerCase());
    }

    for (const key of Object.keys(TOKEN)) {
      const cssName = camelToCssName(key);
      expect(cssTokens, `TOKEN.${key} has no matching CSS property ${cssName}`).toHaveProperty(cssName);
    }
  });

  it("CSS token values match TOKEN values (no drift)", async () => {
    const css = readSrc("src/styles/tokens.css");
    const cssTokens = parseCssTokens(css);

    const mod = await import("../../src/styles/tokenValues");
    const TOKEN = mod.TOKEN as Record<string, string>;

    function cssNameToCamel(cssName: string): string {
      return cssName.replace(/^--/, "").replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    }

    for (const [cssName, cssValue] of Object.entries(cssTokens)) {
      const camel = cssNameToCamel(cssName);
      if (camel in TOKEN) {
        expect(TOKEN[camel].toLowerCase()).toBe(
          cssValue.toLowerCase(),
          `Token drift: CSS ${cssName}=${cssValue} but TOKEN.${camel}=${TOKEN[camel]}`
        );
      }
    }
  });
});

// ---------------------------------------------------------------------------
// 3. touColors.ts uses TOKEN values exclusively
// ---------------------------------------------------------------------------
describe("touColors.ts — uses TOKEN values, no independent hex (§6)", () => {
  it("critical_peak bg comes from TOKEN.touCriticalPeakBg", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.critical_peak.bg).toBe(TOKEN.touCriticalPeakBg);
  });

  it("critical_peak text comes from TOKEN.touCriticalPeakText", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.critical_peak.text).toBe(TOKEN.touCriticalPeakText);
  });

  it("critical_peak border comes from TOKEN.touCriticalPeakBorder", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.critical_peak.border).toBe(TOKEN.touCriticalPeakBorder);
  });

  it("peak bg comes from TOKEN.touPeakBg", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.peak.bg).toBe(TOKEN.touPeakBg);
  });

  it("peak text comes from TOKEN.touPeakText", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.peak.text).toBe(TOKEN.touPeakText);
  });

  it("peak border comes from TOKEN.touPeakBorder", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.peak.border).toBe(TOKEN.touPeakBorder);
  });

  it("mid bg comes from TOKEN.touMidBg", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.mid.bg).toBe(TOKEN.touMidBg);
  });

  it("mid text comes from TOKEN.touMidText", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.mid.text).toBe(TOKEN.touMidText);
  });

  it("mid border comes from TOKEN.touMidBorder", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.mid.border).toBe(TOKEN.touMidBorder);
  });

  it("valley bg comes from TOKEN.touValleyBg", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.valley.bg).toBe(TOKEN.touValleyBg);
  });

  it("valley text comes from TOKEN.touValleyText", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.valley.text).toBe(TOKEN.touValleyText);
  });

  it("valley border comes from TOKEN.touValleyBorder", async () => {
    const { TOU_COLORS } = await import("../../src/utils/touColors");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    expect(TOU_COLORS.valley.border).toBe(TOKEN.touValleyBorder);
  });

  // getTouColor is just TOU_COLORS lookup — no independent logic to test separately
  it("getTouColor returns the same object as TOU_COLORS for each tier", async () => {
    const { TOU_COLORS, getTouColor } = await import("../../src/utils/touColors");
    for (const tier of ["critical_peak", "peak", "mid", "valley"] as const) {
      expect(getTouColor(tier)).toBe(TOU_COLORS[tier]);
    }
  });
});

// ---------------------------------------------------------------------------
// 4. WCAG AA contrast ratios (§7)
// ---------------------------------------------------------------------------
describe("WCAG contrast ratios (§7)", () => {
  // body-on-app: #e2e8f0 on #0f1117 — expected ≥ 4.5:1
  // Arithmetic: L(#e2e8f0) ≈ 0.7489, L(#0f1117) ≈ 0.0039 → (0.7489+0.05)/(0.0039+0.05) ≈ 14.5:1
  it("body text (#e2e8f0) on app bg (#0f1117) meets 4.5:1", () => {
    const r = contrast("#e2e8f0", "#0f1117");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  // body-on-surface: #e2e8f0 on #1e2533
  // L(#1e2533) ≈ 0.0138 → (0.7489+0.05)/(0.0138+0.05) ≈ 12.4:1
  it("body text (#e2e8f0) on surface bg (#1e2533) meets 4.5:1", () => {
    const r = contrast("#e2e8f0", "#1e2533");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  // muted-on-app: #94a3b8 on #0f1117
  // L(#94a3b8) ≈ 0.2834, L(#0f1117) ≈ 0.0039 → (0.2834+0.05)/(0.0039+0.05) ≈ 5.9:1
  it("muted text (#94a3b8) on app bg (#0f1117) meets 4.5:1", () => {
    const r = contrast("#94a3b8", "#0f1117");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  // muted-on-nav: #94a3b8 on #1a1f2e
  // L(#1a1f2e) ≈ 0.0085 → (0.2834+0.05)/(0.0085+0.05) ≈ 5.7:1
  it("muted text (#94a3b8) on nav bg (#1a1f2e) meets 4.5:1", () => {
    const r = contrast("#94a3b8", "#1a1f2e");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  // faint-on-surface: #64748b on #1e2533 (large text only — 3:1 minimum)
  // #64748b: r=100, g=116, b=139
  //   R_lin = ((100/255+0.055)/1.055)^2.4 ≈ 0.1275
  //   G_lin = ((116/255+0.055)/1.055)^2.4 ≈ 0.1749
  //   B_lin = ((139/255+0.055)/1.055)^2.4 ≈ 0.2580
  //   L ≈ 0.2126×0.1275 + 0.7152×0.1749 + 0.0722×0.2580 ≈ 0.1708
  // #1e2533: r=30, g=37, b=51
  //   L ≈ 0.2126×0.0138 + 0.7152×0.0161 + 0.0722×0.0333 ≈ 0.0142
  // Contrast: (0.1708+0.05)/(0.0142+0.05) ≈ 3.44:1 — meets 3:1 for large/uppercase
  it("faint text (#64748b) on surface bg (#1e2533) meets 3:1 for large/uppercase text", () => {
    const r = contrast("#64748b", "#1e2533");
    expect(r).toBeGreaterThanOrEqual(3.0);
  });

  // active-link-on-nav: #60a5fa on #1a1f2e (large)
  // L(#60a5fa) ≈ 0.2034, L(#1a1f2e) ≈ 0.0085 → (0.2034+0.05)/(0.0085+0.05) ≈ 4.3:1
  it("active link (#60a5fa) on nav bg (#1a1f2e) meets 3:1 for large text", () => {
    const r = contrast("#60a5fa", "#1a1f2e");
    expect(r).toBeGreaterThanOrEqual(3.0);
  });

  // error-text-on-error-bg: #fca5a5 on #2d1515
  // L(#fca5a5) ≈ 0.3768, L(#2d1515) ≈ 0.0076 → (0.3768+0.05)/(0.0076+0.05) ≈ 7.5:1
  it("error text (#fca5a5) on error bg (#2d1515) meets 4.5:1", () => {
    const r = contrast("#fca5a5", "#2d1515");
    expect(r).toBeGreaterThanOrEqual(4.5);
  });

  // error-border-on-error-bg: #f87171 on #2d1515 (visual boundary — 3:1)
  it("error border (#f87171) on error bg (#2d1515) meets 3:1", () => {
    const r = contrast("#f87171", "#2d1515");
    expect(r).toBeGreaterThanOrEqual(3.0);
  });
});

// ---------------------------------------------------------------------------
// 5. Structural: no bare hex in refactored CSS and TS files (§5)
// ---------------------------------------------------------------------------
describe("no bare hex literals in refactored files (§5)", () => {
  const HEX_RE = /#[0-9a-fA-F]{3,6}\b/g;

  it("src/style.css contains no bare hex after the @import line", () => {
    const raw = readSrc("src/style.css");
    // Allow the @import line (line 1) itself; strip it to test the rest.
    const withoutFirstLine = raw.split("\n").slice(1).join("\n");
    const hits = withoutFirstLine.match(HEX_RE) ?? [];
    expect(hits).toHaveLength(0);
  });

  it("src/utils/touColors.ts contains no bare hex literals", () => {
    const raw = readSrc("src/utils/touColors.ts");
    // Allow hex that only appears inside comments
    const withoutComments = raw.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    const hits = withoutComments.match(HEX_RE) ?? [];
    expect(hits).toHaveLength(0);
  });

  it("src/components/live/SocTimeline.tsx contains no bare hex literals", () => {
    const raw = readSrc("src/components/live/SocTimeline.tsx");
    const withoutComments = raw.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    const hits = withoutComments.match(HEX_RE) ?? [];
    expect(hits).toHaveLength(0);
  });

  it("src/components/training/MetricCurves.tsx contains no bare hex literals", () => {
    const raw = readSrc("src/components/training/MetricCurves.tsx");
    const withoutComments = raw.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    const hits = withoutComments.match(HEX_RE) ?? [];
    expect(hits).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 6. MetricCurves PANELS — chart series colors come from TOKEN (§3.6)
// ---------------------------------------------------------------------------
describe("MetricCurves.tsx PANELS use TOKEN chart-series values (§3.6)", () => {
  it("actor_loss series color = TOKEN.chartActor", async () => {
    // Import PANELS array (must be exported after refactor).
    const { PANELS } = await import("../../src/components/training/MetricCurves");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    const actor = PANELS.find((p) => p.key === "actor_loss");
    expect(actor).toBeDefined();
    expect(actor!.color).toBe(TOKEN.chartActor);
  });

  it("critic_loss series color = TOKEN.chartCritic", async () => {
    const { PANELS } = await import("../../src/components/training/MetricCurves");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    const critic = PANELS.find((p) => p.key === "critic_loss");
    expect(critic).toBeDefined();
    expect(critic!.color).toBe(TOKEN.chartCritic);
  });

  it("ent_coef series color = TOKEN.chartEntropy", async () => {
    const { PANELS } = await import("../../src/components/training/MetricCurves");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    const entropy = PANELS.find((p) => p.key === "ent_coef");
    expect(entropy).toBeDefined();
    expect(entropy!.color).toBe(TOKEN.chartEntropy);
  });

  it("reward_scaled_mean series color = TOKEN.chartReward", async () => {
    const { PANELS } = await import("../../src/components/training/MetricCurves");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    const reward = PANELS.find((p) => p.key === "reward_scaled_mean");
    expect(reward).toBeDefined();
    expect(reward!.color).toBe(TOKEN.chartReward);
  });

  it("cost_total_real_mean_yuan series color = TOKEN.chartCost", async () => {
    const { PANELS } = await import("../../src/components/training/MetricCurves");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    const cost = PANELS.find((p) => p.key === "cost_total_real_mean_yuan");
    expect(cost).toBeDefined();
    expect(cost!.color).toBe(TOKEN.chartCost);
  });
});

// ---------------------------------------------------------------------------
// 7. SocTimeline — inline color props use TOKEN values (§3.6)
// ---------------------------------------------------------------------------
describe("SocTimeline.tsx inline props use TOKEN values (§3.6 + §8)", () => {
  it("SOC_LINE_COLOR export = TOKEN.chartSoc", async () => {
    // After refactor, SocTimeline.tsx must export SOC_LINE_COLOR constant.
    const socMod = await import("../../src/components/live/SocTimeline");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    // @ts-expect-error — SOC_LINE_COLOR export added in refactor
    expect(socMod.SOC_LINE_COLOR).toBe(TOKEN.chartSoc);
  });

  it("SOC_BOUNDS_COLOR export = TOKEN.accentGreen", async () => {
    const socMod = await import("../../src/components/live/SocTimeline");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    // @ts-expect-error — SOC_BOUNDS_COLOR export added in refactor
    expect(socMod.SOC_BOUNDS_COLOR).toBe(TOKEN.accentGreen);
  });

  it("SOC_BAND_BG export = TOKEN.touValleyBg", async () => {
    // The SOC safe-range band uses valley green (#dcfce7) — same as TOU valley tier bg.
    const socMod = await import("../../src/components/live/SocTimeline");
    const { TOKEN } = await import("../../src/styles/tokenValues");
    // @ts-expect-error — SOC_BAND_BG export added in refactor
    expect(socMod.SOC_BAND_BG).toBe(TOKEN.touValleyBg);
  });
});

// ---------------------------------------------------------------------------
// 8. tokens.css is @imported as first statement of style.css
// ---------------------------------------------------------------------------
describe("src/style.css imports tokens.css as first declaration (§5)", () => {
  it("first non-comment line of style.css is @import for tokens.css", () => {
    const raw = readSrc("src/style.css");
    const lines = raw
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0 && !l.startsWith("/*") && !l.startsWith("*") && !l.startsWith("//"));
    expect(lines[0]).toMatch(/@import.*tokens\.css/);
  });
});

// ---------------------------------------------------------------------------
// 9. Token catalogue completeness — TOKEN has exactly the keys in §3
// ---------------------------------------------------------------------------
describe("TOKEN catalogue completeness — no undocumented extra keys (§3)", () => {
  const EXPECTED_KEYS = new Set([
    "bgApp", "bgSurface", "bgNav", "bgError",
    "borderDefault",
    "textPrimary", "textMuted", "textFaint",
    "accentBlue", "accentGreen", "accentAmber", "accentRed", "accentErrorText", "accentGrey",
    "touCriticalPeakBg", "touCriticalPeakText", "touCriticalPeakBorder",
    "touPeakBg", "touPeakText", "touPeakBorder",
    "touMidBg", "touMidText", "touMidBorder",
    "touValleyBg", "touValleyText", "touValleyBorder",
    "chartActor", "chartCritic", "chartEntropy", "chartReward", "chartCost",
    "chartSoc", "chartGrid", "chartAxis", "chartAxisLabel",
  ]);

  it("TOKEN has exactly the keys listed in §3 (no missing, no extra)", async () => {
    const { TOKEN } = await import("../../src/styles/tokenValues");
    const actualKeys = new Set(Object.keys(TOKEN));

    const missing = [...EXPECTED_KEYS].filter((k) => !actualKeys.has(k));
    const extra   = [...actualKeys].filter((k) => !EXPECTED_KEYS.has(k));

    expect(missing, `Missing TOKEN keys: ${missing.join(", ")}`).toHaveLength(0);
    expect(extra, `Extra TOKEN keys not in contract §3: ${extra.join(", ")}`).toHaveLength(0);
  });
});
