/**
 * SessionControlStrip — minimal session control UI for the live inference view.
 * Contract: contracts/frontend/inference_session.md §6
 *
 * Reads from inferenceSessionStore and renders state-conditional controls:
 * - idle/connecting: "Connecting…"
 * - ready: "Starting session…" (auto-start in-flight)
 * - running: step + episode counter, Pause button, speed selector
 * - paused: step + episode counter, Resume button
 * - error: error message, Retry button
 * - stopped: "Session stopped"
 */

import { useInferenceSessionStore, inferenceSessionStore } from "../stores/inferenceSessionStore";

const SPEED_OPTIONS = [
  { value: 0,   label: "Max speed" },
  { value: 0.5, label: "0.5×" },
  { value: 1,   label: "1× (real-time)" },
  { value: 2,   label: "2×" },
  { value: 5,   label: "5×" },
] as const;

export function SessionControlStrip() {
  const serverState = useInferenceSessionStore((s) => s.serverState);
  const step        = useInferenceSessionStore((s) => s.step);
  const episode     = useInferenceSessionStore((s) => s.episode);
  const speed       = useInferenceSessionStore((s) => s.speed);
  const errorMsg    = useInferenceSessionStore((s) => s.errorMsg);
  const pause       = useInferenceSessionStore((s) => s.pause);
  const resume      = useInferenceSessionStore((s) => s.resume);
  const setSpeed    = useInferenceSessionStore((s) => s.setSpeed);

  function handleRetry() {
    // Reset error state and re-trigger auto-start
    inferenceSessionStore.setState({ serverState: "idle", errorMsg: null });
    // Re-use the ready path: fake a ready status to trigger _autoStart
    inferenceSessionStore.getState().handleServerStatus({
      kind: "status",
      state: "ready",
      session_id: null,
      step: 0,
      episode: 0,
      run_id: null,
      site_id: null,
    });
  }

  return (
    <div data-testid="session-control-strip" className="session-control-strip">
      {serverState === "idle" && (
        <span data-testid="session-status-label" className="session-status">
          Connecting…
        </span>
      )}

      {serverState === "ready" && (
        <span data-testid="session-status-label" className="session-status">
          Starting session…
        </span>
      )}

      {serverState === "running" && (
        <>
          <span data-testid="session-status-label" className="session-status">
            Running — step {step} ep {episode}
          </span>
          <button
            data-testid="session-pause-btn"
            className="session-btn"
            onClick={pause}
          >
            Pause
          </button>
          <select
            data-testid="session-speed-select"
            className="session-speed"
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          >
            {SPEED_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </>
      )}

      {serverState === "paused" && (
        <>
          <span data-testid="session-status-label" className="session-status">
            Paused — step {step} ep {episode}
          </span>
          <button
            data-testid="session-resume-btn"
            className="session-btn"
            onClick={resume}
          >
            Resume
          </button>
        </>
      )}

      {serverState === "stopped" && (
        <span data-testid="session-status-label" className="session-status">
          Session stopped
        </span>
      )}

      {serverState === "error" && (
        <>
          <span
            data-testid="session-status-label"
            className="session-status session-status--error"
          >
            {errorMsg}
          </span>
          <button
            data-testid="session-retry-btn"
            className="session-btn session-btn--retry"
            onClick={handleRetry}
          >
            Retry
          </button>
        </>
      )}
    </div>
  );
}
