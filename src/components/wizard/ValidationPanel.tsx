// src/components/wizard/ValidationPanel.tsx
// Contract: contracts/frontend/stage_config.md §4.4

import React, { useEffect, useState } from "react";
import type { ValidationResult } from "../../types/stageConfig";
import { TOKEN } from "../../styles/tokenValues";

interface ValidationPanelProps {
  result:               ValidationResult | null;
  pending:              boolean;
  acknowledgedWarnings: string[];
  onAcknowledge:        (ruleId: string) => void;
  apiError:             string | null;
  onRetry:              () => void;
  tariffRequired?:      boolean;
}

export function ValidationPanel({
  result,
  pending,
  acknowledgedWarnings,
  onAcknowledge,
  apiError,
  onRetry,
  tariffRequired,
}: ValidationPanelProps) {
  // T-VAL-8: "Still checking…" appears after 2000ms of pending
  const [showStillChecking, setShowStillChecking] = useState(false);
  useEffect(() => {
    if (!pending) { setShowStillChecking(false); return; }
    const t = setTimeout(() => setShowStillChecking(true), 2000);
    return () => clearTimeout(t);
  }, [pending]);

  // T-VAL-TARIFF-REQ: tariff required state takes priority over all other states
  if (tariffRequired && !pending && !apiError) {
    return (
      <div style={{ padding: "12px" }}>
        <div data-testid="validation-tariff-required" style={{ color: TOKEN.textMuted, fontSize: "13px" }}>
          Select a tariff region to validate your fleet
        </div>
      </div>
    );
  }

  // API error state
  if (apiError && !pending) {
    return (
      <div style={{ padding: "12px" }}>
        <div
          data-testid="validation-api-error"
          role="alert"
          style={{ color: TOKEN.accentErrorText, marginBottom: "8px" }}
        >
          Validation unavailable — check connection
        </div>
        <button
          data-testid="validation-retry"
          onClick={onRetry}
          style={{ fontSize: "12px", padding: "4px 10px", cursor: "pointer" }}
        >
          Retry
        </button>
      </div>
    );
  }

  // Pending state
  if (pending) {
    return (
      <div style={{ padding: "12px" }}>
        <div data-testid="validation-loading" style={{ color: TOKEN.textMuted }}>
          Checking...
        </div>
        {showStillChecking && (
          <div data-testid="validation-still-checking" style={{ color: TOKEN.textFaint, fontSize: "12px", marginTop: "4px" }}>
            Still checking…
          </div>
        )}
      </div>
    );
  }

  // No result yet (initial state, no tariff required info needed)
  if (!result) {
    return <div style={{ padding: "12px" }} />;
  }

  // Clean state
  if (result.errors.length === 0 && result.warnings.length === 0) {
    return (
      <div style={{ padding: "12px" }}>
        <div data-testid="validation-clean" style={{ color: TOKEN.accentGreen, fontWeight: 500 }}>
          ✓ Configuration valid
        </div>
      </div>
    );
  }

  // Errors and/or warnings
  return (
    <div style={{ padding: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
      {result.errors.map(err => (
        <div
          key={err.rule_id}
          data-testid={`validation-error-${err.rule_id}`}
          role="alert"
          style={{
            background:   TOKEN.bgError,
            border:       `1px solid ${TOKEN.accentRed}`,
            borderRadius: "4px",
            padding:      "8px 10px",
            color:        TOKEN.accentErrorText,
            fontSize:     "13px",
          }}
        >
          ✗ {err.message}
        </div>
      ))}
      {result.warnings.map(warn => {
        const isAcked = acknowledgedWarnings.includes(warn.rule_id);
        if (isAcked) {
          return (
            <div
              key={warn.rule_id}
              data-testid={`validation-acked-${warn.rule_id}`}
              role="alert"
              style={{
                padding:        "8px 10px",
                color:          TOKEN.textFaint,
                fontSize:       "13px",
                textDecoration: "line-through",
              }}
            >
              ⚠ {warn.message}
            </div>
          );
        }
        return (
          <div
            key={warn.rule_id}
            data-testid={`validation-warning-${warn.rule_id}`}
            role="alert"
            style={{
              background:   "#2d2500",
              border:       `1px solid ${TOKEN.accentAmber}`,
              borderRadius: "4px",
              padding:      "8px 10px",
              display:      "flex",
              alignItems:   "center",
              gap:          "8px",
            }}
          >
            <span style={{ color: TOKEN.accentAmber, fontSize: "13px", flex: 1 }}>
              ⚠ {warn.message}
            </span>
            <button
              data-testid={`validation-ack-${warn.rule_id}`}
              aria-label={`acknowledge warning: ${warn.message}`}
              onClick={() => onAcknowledge(warn.rule_id)}
              style={{
                fontSize:     "11px",
                padding:      "3px 8px",
                cursor:       "pointer",
                borderRadius: "4px",
                background:   TOKEN.accentAmber,
                color:        "#1a1000",
                border:       "none",
                fontWeight:   600,
                whiteSpace:   "nowrap",
              }}
            >
              Acknowledge
            </button>
          </div>
        );
      })}
    </div>
  );
}
