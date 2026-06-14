// src/components/wizard/StageTwoAlgorithm.tsx
// Wizard Stage ② — Algorithm & Baseline selection
// Contract: contracts/frontend/stage_algorithm.md (v1 simplified scope)
//
// v1 scope:
//   - Baseline selector: GET /api/baselines on unlock; static fallback on failure
//   - SAC card: non-submitting coming-soon stub (Option B: secondary/de-emphasized)
//   - Confirm & Continue: local stageState → COMPLETE; NO POST (DV-6)

import React, { useEffect } from "react";
import {
  useStageAlgorithmStore,
  isConfirmEnabled,
} from "../../stores/stageAlgorithmStore";
import { TOKEN } from "../../styles/tokenValues";

// ── §5 Locked SAC constants (read-only display) ───────────────────────────────
// Source: training_pipeline.md §3 RunConfig. gamma LOCKED per §3.1.
// DO NOT ADD editable inputs here — these are read-only constants (DV-4, C2).

// Explicit type so all entries share a uniform shape — `as const` would create a
// heterogeneous union where only the gamma entry has `locked`, causing TS2339 on tsc.
const SAC_CONSTANTS: ReadonlyArray<{
  key: string;
  label: string;
  value: string;
  locked?: boolean;
}> = [
  { key: "lr",               label: "Learning rate (lr)",      value: "1e-4" },
  { key: "gamma",            label: "Discount factor (γ)",     value: "0.999", locked: true },
  { key: "batch_size",       label: "Batch size",              value: "512" },
  { key: "total_env_steps",  label: "Total env steps",         value: "500,000" },
  { key: "buffer_size",      label: "Replay buffer size",      value: "1,000,000" },
  { key: "n_envs",           label: "Parallel envs",           value: "4" },
  { key: "hidden_sizes",     label: "Hidden layer sizes",      value: "[256, 256]" },
  { key: "tau",              label: "Soft update (τ)",         value: "0.005" },
  { key: "ent_coef",         label: "Entropy coefficient",     value: '"auto"' },
];

// ── Component ─────────────────────────────────────────────────────────────────

interface StageTwoAlgorithmProps {
  /** Must be true for stage-② form to be accessible; driven by stage-① stageState. */
  stageOneComplete: boolean;
  onBack: () => void;
  onContinue: () => void;
}

export default function StageTwoAlgorithm({
  stageOneComplete,
  onBack,
  onContinue,
}: StageTwoAlgorithmProps): JSX.Element {
  const stageState       = useStageAlgorithmStore((s) => s.stageState);
  const algorithmType    = useStageAlgorithmStore((s) => s.algorithmType);
  const selectedBaselines = useStageAlgorithmStore((s) => s.selectedBaselines);
  const availableBaselines = useStageAlgorithmStore((s) => s.availableBaselines);
  const baselinesError   = useStageAlgorithmStore((s) => s.baselinesError);

  const {
    setAlgorithmType,
    toggleBaseline,
    confirm,
    loadBaselines,
    lockStage,
    unlockStage,
  } = useStageAlgorithmStore.getState();

  // ── Sync stageOneComplete prop → store lock/unlock + baselines fetch ──────
  useEffect(() => {
    if (stageOneComplete) {
      unlockStage();
      void loadBaselines();
    } else {
      lockStage();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stageOneComplete]);

  // ── Derived ───────────────────────────────────────────────────────────────
  const enabled = isConfirmEnabled({ selectedBaselines });

  // ── Event handlers ────────────────────────────────────────────────────────

  function handleConfirm() {
    if (!enabled) return; // aria-disabled intercept (T-CONFIRM-4, T-A11Y-7)
    if (stageState === "COMPLETE") return; // double-submit guard (T-CONFIRM-5)
    confirm();
    onContinue();
  }

  function handleAlgoKeyDown(
    e: React.KeyboardEvent,
    type: "baseline_only" | "sac",
  ) {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      setAlgorithmType(type);
    }
  }

  // ── Back button (shared between locked and unlocked — DV-1: span not button) ─

  const BackButton = (
    <span
      data-testid="stage-two-back"
      role="button"
      tabIndex={0}
      onClick={onBack}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onBack();
      }}
      style={{ cursor: "pointer" }}
    >
      ← Back
    </span>
  );

  // ── LOCKED view (stageOneComplete = false) ────────────────────────────────
  // Content section absent from DOM entirely (T-LOCK-1/2, T-A11Y-6).

  if (!stageOneComplete) {
    return (
      <div data-testid="stage-two-algorithm">
        <div data-testid="stage-two-locked">
          <p>Stage ① (site configuration) must be complete before selecting an algorithm.</p>
          <span
            data-testid="stage-two-locked-go-config"
            role="button"
            tabIndex={0}
            onClick={onBack}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onBack();
            }}
            style={{ cursor: "pointer" }}
          >
            ← Go to Config
          </span>
        </div>
        {BackButton}
      </div>
    );
  }

  // ── UNLOCKED view ─────────────────────────────────────────────────────────

  return (
    <div data-testid="stage-two-algorithm">
      <div data-testid="stage-two-content">

        {/* ── Algorithm selection (radiogroup) ───────────────────────────── */}
        <div role="radiogroup" aria-label="Training algorithm">

          {/* Baseline-only card — primary (Option B: default-selected, prominent)
               §5.2 token styling: accentBlue border when selected, default border otherwise */}
          <div
            data-testid="algo-card-baseline-only"
            role="radio"
            aria-checked={algorithmType === "baseline_only" ? "true" : "false"}
            tabIndex={0}
            onClick={() => setAlgorithmType("baseline_only")}
            onKeyDown={(e) => handleAlgoKeyDown(e, "baseline_only")}
            style={{
              cursor: "pointer",
              border: `2px solid ${algorithmType === "baseline_only" ? TOKEN.accentBlue : TOKEN.borderDefault}`,
              borderRadius: "6px",
              padding: "12px 16px",
              background: TOKEN.bgSurface,
              color: TOKEN.textPrimary,
            }}
          >
            <strong>Baseline Only</strong>
            <p style={{ color: TOKEN.textMuted, margin: "4px 0 0" }}>
              Compare pre-built rule-based agents. Recommended starting point.
            </p>
          </div>

          {/* SAC card — secondary / de-emphasized (Option B: "Future" badge)
               §5.2 token styling: always TOKEN.borderDefault (greyed); lower opacity */}
          <div
            data-testid="algo-card-sac"
            role="radio"
            aria-checked={algorithmType === "sac" ? "true" : "false"}
            tabIndex={0}
            onClick={() => setAlgorithmType("sac")}
            onKeyDown={(e) => handleAlgoKeyDown(e, "sac")}
            style={{
              cursor: "pointer",
              border: `2px solid ${TOKEN.borderDefault}`,
              borderRadius: "6px",
              padding: "12px 16px",
              background: TOKEN.bgSurface,
              color: TOKEN.textMuted,
              opacity: 0.8,
            }}
          >
            <span>SAC (Soft Actor-Critic)</span>
            {/* Option B: secondary badge — always visible on the SAC card */}
            <span
              data-testid="algo-card-sac-future-badge"
              style={{
                marginLeft: "8px",
                fontSize: "0.7em",
                color: TOKEN.textFaint,
                border: `1px solid ${TOKEN.accentGrey}`,
                borderRadius: "4px",
                padding: "1px 5px",
              }}
            >
              Future
            </span>
          </div>
        </div>

        {/* ── Algorithm-specific content ──────────────────────────────────── */}

        {algorithmType === "baseline_only" && (
          <div data-testid="algo-baseline-notice">
            <p>
              Baseline agents will be evaluated on the selected site.
              Configure which baselines to run below.
            </p>
          </div>
        )}

        {algorithmType === "sac" && (
          <>
            <div data-testid="algo-sac-coming-soon-notice">
              <p>
                SAC RL training is coming in a future release. Selecting SAC records your
                preference and carries it forward to later wizard stages — no training is
                submitted now.
              </p>
            </div>

            {/* §5 constants — read-only display (DV-4, C2); must contain ZERO inputs */}
            <div data-testid="algo-sac-constants-preview">
              <h4>§5 Locked Training Constants (read-only)</h4>
              <dl>
                {SAC_CONSTANTS.map(({ key, label, value, locked }) => (
                  <div key={key}>
                    <dt>{label}: </dt>
                    <dd>
                      {value}
                      {locked ? " (LOCKED — training_pipeline.md §3.1)" : ""}
                      {" "}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </>
        )}

        {/* ── Baseline selection ──────────────────────────────────────────── */}
        <div
          data-testid="baselines-section"
          role="group"
          aria-label="Baseline agents"
        >
          {/* Error indicator when GET /api/baselines failed (informational; does not block confirm) */}
          {baselinesError !== null && (
            <div data-testid="baselines-load-error" role="status">
              Could not load baselines from server — using defaults.
            </div>
          )}

          {availableBaselines.map((baseline) => (
            <label key={baseline.id} title={baseline.description}>
              <input
                type="checkbox"
                data-testid={`baseline-checkbox-${baseline.id}`}
                checked={selectedBaselines.includes(baseline.id as "do_nothing" | "peak_shave" | "import_minimiser")}
                onChange={() =>
                  toggleBaseline(baseline.id as "do_nothing" | "peak_shave" | "import_minimiser")
                }
              />
              {baseline.label}
            </label>
          ))}

          {/* No-baseline error: role=alert so screen readers announce immediately */}
          {selectedBaselines.length === 0 && (
            <div data-testid="baseline-none-error" role="alert">
              Select at least one baseline agent to continue.
            </div>
          )}

          {/* Confirm disabled reason: shown when button is aria-disabled */}
          {!enabled && (
            <div data-testid="confirm-disabled-reason">
              Please select at least one baseline agent.
            </div>
          )}
        </div>
      </div>

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
        {BackButton}

        {/* Confirm button: aria-disabled (not HTML disabled) per T-A11Y-5 */}
        <button
          data-testid="stage-two-confirm"
          aria-disabled={enabled ? "false" : "true"}
          onClick={handleConfirm}
          type="button"
        >
          Confirm &amp; Continue
        </button>
      </div>
    </div>
  );
}
