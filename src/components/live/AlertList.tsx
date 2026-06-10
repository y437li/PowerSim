import React from "react";
import type { AlertEvent } from "../../utils/deriveAlerts";
import { formatYuan } from "../../utils/units";

interface AlertListProps {
  alerts: AlertEvent[];
}

export function AlertList({ alerts }: AlertListProps): JSX.Element {
  if (alerts.length === 0) {
    return (
      <div data-testid="alert-list" className="card alert-list alert-list--empty">
        <div className="card__title">Alerts</div>
        <div className="card__body">No alerts</div>
      </div>
    );
  }
  return (
    <div data-testid="alert-list" className="card alert-list">
      <div className="card__title">Alerts</div>
      <div className="card__body">
        {alerts.map((alert, i) => (
          <div
            key={`${alert.kind}-${alert.stepIndex}-${i}`}
            data-testid={`alert-${alert.kind}`}
            className={`alert-row alert-row--${alert.kind}`}
          >
            <span className="alert-step">Step {alert.stepIndex}</span>
            <span className="alert-detail">{alert.detail}</span>
            <span className="alert-penalty">{formatYuan(alert.penaltyYuan, 0)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
