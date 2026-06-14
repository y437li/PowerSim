// src/components/wizard/ScenarioComposer.tsx
// Contract: contracts/frontend/stage_config.md §4.5
// v1: read-only; base scenario is always active and non-interactive.

import React from "react";
import { TOKEN } from "../../styles/tokenValues";

interface ScenarioComposerProps {
  scenarioBasePowerActive: boolean;
}

export function ScenarioComposer({ scenarioBasePowerActive }: ScenarioComposerProps) {
  return (
    <section style={{ marginBottom: "16px" }}>
      <h3 style={{ color: TOKEN.textMuted, fontSize: "12px", fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "8px" }}>
        Scenarios
      </h3>
      {/* T-SCENARIO-1: base scenario always checked + non-interactive in v1 */}
      <div
        data-testid="scenario-base-power"
        role="checkbox"
        aria-checked="true"
        aria-disabled="true"
        style={{
          display:       "flex",
          alignItems:    "center",
          gap:           "10px",
          padding:       "8px 12px",
          borderRadius:  "6px",
          background:    TOKEN.bgSurface,
          border:        `1px solid ${TOKEN.borderDefault}`,
          cursor:        "default",
          userSelect:    "none",
        }}
      >
        <span style={{ color: TOKEN.accentGreen, fontSize: "16px" }}>✓</span>
        <span style={{ color: TOKEN.textPrimary, fontWeight: 500 }}>Power supply</span>
        <span style={{ color: TOKEN.textFaint, fontSize: "12px" }}>base — always active</span>
      </div>
    </section>
  );
}
