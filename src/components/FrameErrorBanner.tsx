/**
 * FrameErrorBanner — surfaces wsClient validation failures to the operator.
 *
 * Contract: contracts/frontend/telemetry_validator.md §13.3
 *
 * Reads telemetryStore.frameErrors (most-recent-first ring buffer, cap 10).
 * Each entry is rendered with data-testid="frame-error-<index>" (0-based).
 * Renders nothing when frameErrors is empty.
 *
 * Placement: adjacent to AlertList in the operator dashboard panel.
 */

import { useTelemetryStore } from "../stores/telemetryStore";

export function FrameErrorBanner() {
  // No-selector form: consistent with LiveDashboard and other consumers.
  // `?? []` defensive fallback guards against incomplete test mocks.
  const { frameErrors = [] } = useTelemetryStore();

  if (frameErrors.length === 0) return null;

  return (
    <div className="frame-error-banner" role="alert" aria-label="Frame validation errors">
      {frameErrors.map((err, i) => (
        <div
          key={`${err.kind}-${err.seq}-${i}`}
          data-testid={`frame-error-${i}`}
          className="frame-error-entry"
        >
          <span className="frame-error-kind">{err.kind}</span>
          {" "}
          <span className="frame-error-seq">seq={err.seq}</span>
          {" "}
          <span className="frame-error-codes">[{err.errors.join(", ")}]</span>
        </div>
      ))}
    </div>
  );
}
