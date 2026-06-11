import React, { useEffect, useState, useCallback } from "react";
import type { RestClient } from "../../clients/restClient";
import type { RunInfo } from "../../types/telemetry";

interface RunSelectorProps {
  restClient: RestClient;
}

type LoadState = "loading" | "loaded" | "error";

/**
 * Compact run picker backed by restClient.getRuns().
 * - Loads on mount and on retry.
 * - Run selection is display-only: this component does NOT re-target the WS stream.
 * - States: loading / error-with-retry / empty / loaded.
 */
export function RunSelector({ restClient }: RunSelectorProps): JSX.Element {
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");

  const loadRuns = useCallback(() => {
    setLoadState("loading");
    restClient
      .getRuns()
      .then((data) => {
        setRuns(data);
        setLoadState("loaded");
      })
      .catch(() => {
        setLoadState("error");
      });
  }, [restClient]);

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  if (loadState === "loading") {
    return (
      <div className="run-selector">
        <span className="run-selector__status">Loading runs…</span>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="run-selector">
        <span className="run-selector__status run-selector__status--error">
          Could not load runs
        </span>
        <button
          className="run-selector__retry"
          onClick={loadRuns}
          type="button"
        >
          Retry
        </button>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="run-selector">
        <span className="run-selector__status">No runs available</span>
      </div>
    );
  }

  return (
    <div className="run-selector">
      <label className="run-selector__label" htmlFor="run-select">
        Run
      </label>
      <select id="run-select" className="run-selector__select">
        {runs.map((run) => (
          <option
            key={run.run_id ?? run.id ?? ""}
            value={run.run_id ?? run.id ?? ""}
            data-status={run.status}
          >
            {run.run_id ?? run.id ?? ""}
          </option>
        ))}
      </select>
    </div>
  );
}
