import React from "react";
import { useTelemetryStore } from "../stores/telemetryStore";
import { StreamStatusBanner } from "../components/training/StreamStatusBanner";
import { CostBreakdownCard } from "../components/live/CostBreakdownCard";
import { SocTimeline } from "../components/live/SocTimeline";
import { PriceTimeline } from "../components/live/PriceTimeline";
import { MonthPeakCard } from "../components/live/MonthPeakCard";
import { AlertList } from "../components/live/AlertList";
import { PowerFlowsTable } from "../components/live/PowerFlowsTable";
import { deriveAlerts } from "../utils/deriveAlerts";

/**
 * LiveDashboard — live operations panel at the / route (SiteView).
 * Consumes useTelemetryStore() only — no direct REST or WS client.
 * All sub-components receive plain props extracted from the store state.
 */
export function LiveDashboard(): JSX.Element {
  const { envStep, history, wsStatus, seqGap } = useTelemetryStore();
  const alerts = deriveAlerts(history);

  // Empty + disconnected → blank (StreamStatusBanner is the signal; no "Waiting" text)
  if (wsStatus === "disconnected" && !envStep) {
    return (
      <div data-testid="live-dashboard" className="live-dashboard live-dashboard--disconnected">
        <StreamStatusBanner wsStatus={wsStatus} lastMessageTsUtc={null} seqGap={seqGap} />
      </div>
    );
  }

  // Empty + connected/connecting → "Waiting for live data…" spinner
  if (!envStep) {
    return (
      <div data-testid="live-dashboard" className="live-dashboard live-dashboard--waiting">
        <StreamStatusBanner wsStatus={wsStatus} lastMessageTsUtc={null} seqGap={seqGap} />
        <div className="live-dashboard__spinner" role="status">
          Waiting for live data…
        </div>
      </div>
    );
  }

  return (
    <div data-testid="live-dashboard" className="live-dashboard">
      <StreamStatusBanner wsStatus={wsStatus} lastMessageTsUtc={null} seqGap={seqGap} />
      <div className="live-dashboard__grid">
        <CostBreakdownCard costs={envStep.costs} costCum={envStep.cost_cum} />
        <MonthPeakCard
          monthPeakMw={envStep.month_peak_mw}
          demandRateYuanPerMwMonth={envStep.costs.demand_rate_yuan_per_mw_month}
        />
        <AlertList alerts={alerts} />
        <PowerFlowsTable flows={envStep.flows} generation={envStep.generation} />
        <SocTimeline history={history} />
        <PriceTimeline history={history} />
      </div>
    </div>
  );
}
