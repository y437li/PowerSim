// src/styles/tokenValues.ts
// TypeScript mirror of tokens.css — DO NOT hand-edit hex values here.
// If you change a color, change it in tokens.css first, then update this file to match.
// The token-sync test (tests/frontend/design_system.test.tsx suite 2) enforces parity.

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
