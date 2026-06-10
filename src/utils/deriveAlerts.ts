import type { EnvStepPayload } from "../types/telemetry";

export interface AlertEvent {
  kind: "curtailment" | "voll" | "soc_violation";
  stepIndex: number;
  penaltyYuan: number;
  detail: string;
}

// Sub-tolerance guard: JAX float curtailment can produce ~1e-6 MW noise.
// Only raise an alert when the value meaningfully exceeds zero.
const ALERT_EPSILON = 0.001; // MW (and MWh for SOC violation)

export function deriveAlerts(history: EnvStepPayload[]): AlertEvent[] {
  const alerts: AlertEvent[] = [];
  for (const step of history) {
    const curtailed = step.flows.solar_curtailed_mw
                    + step.flows.wind_curtailed_mw
                    + step.flows.bat_curtailed_mw;
    if (curtailed > ALERT_EPSILON) {
      alerts.push({
        kind: "curtailment",
        stepIndex: step.step,
        penaltyYuan: step.costs.c_curtail_yuan,
        detail: `${curtailed.toFixed(1)} MW curtailed`,
      });
    }
    if (step.flows.load_unserved_mw > ALERT_EPSILON) {
      alerts.push({
        kind: "voll",
        stepIndex: step.step,
        penaltyYuan: step.costs.c_voll_yuan,
        detail: `${step.flows.load_unserved_mw.toFixed(1)} MW unserved`,
      });
    }
    if (step.battery.soc_violation_mwh > ALERT_EPSILON) {
      alerts.push({
        kind: "soc_violation",
        stepIndex: step.step,
        penaltyYuan: step.costs.penalty_yuan,
        detail: `${step.battery.soc_violation_mwh.toFixed(2)} MWh overshoot`,
      });
    }
  }
  // Newest-first: highest stepIndex at top (live lists show most recent first).
  return alerts.reverse();
}
