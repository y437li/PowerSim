// src/components/wizard/StageSaveButton.tsx
// Contract: contracts/frontend/stage_config.md §4.6
// Uses aria-disabled (not HTML disabled) to stay focusable per T-A11Y-5.

import React from "react";
import type { StageOneState } from "../../types/stageConfig";
import { TOKEN } from "../../styles/tokenValues";

interface StageSaveButtonProps {
  stageState:     StageOneState;
  saveInProgress: boolean;
  onClick:        () => void;
}

function isEnabled(stageState: StageOneState, saveInProgress: boolean): boolean {
  if (saveInProgress) return false;
  return stageState === "COMPLETE" || stageState === "STALE";
}

function getLabel(stageState: StageOneState, saveInProgress: boolean): string {
  if (saveInProgress) return "Saving… ⟳";
  if (stageState === "STALE") return "Save & Update →";
  if (stageState === "COMPLETE") return "Save & Continue →";
  return "Save & Continue →";
}

export function StageSaveButton({ stageState, saveInProgress, onClick }: StageSaveButtonProps) {
  const enabled = isEnabled(stageState, saveInProgress);
  const label   = getLabel(stageState, saveInProgress);

  function handleClick(e: React.MouseEvent) {
    if (!enabled) { e.preventDefault(); return; }
    onClick();
  }

  return (
    <button
      data-testid="stage-save-btn"
      aria-disabled={enabled ? "false" : "true"}
      onClick={handleClick}
      style={{
        padding:       "8px 20px",
        borderRadius:  "6px",
        fontWeight:    600,
        cursor:        enabled ? "pointer" : "default",
        background:    enabled ? TOKEN.accentBlue : TOKEN.accentGrey,
        color:         TOKEN.textPrimary,
        border:        "none",
        opacity:       enabled ? 1 : 0.5,
      }}
    >
      {label}
    </button>
  );
}
