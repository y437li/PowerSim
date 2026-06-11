import React from "react";
import { formatYuan, formatPower } from "../../utils/units";

interface MonthPeakCardProps {
  monthPeakMw: number;
  demandRateYuanPerMwMonth: number;
}

export function MonthPeakCard({ monthPeakMw, demandRateYuanPerMwMonth }: MonthPeakCardProps): JSX.Element {
  const exposure = monthPeakMw * demandRateYuanPerMwMonth;
  return (
    <div data-testid="month-peak-card" className="card month-peak-card">
      <div className="card__title">Monthly Peak Demand</div>
      <div className="card__body">
        <table className="peak-table">
          <tbody>
            <tr>
              <td>Current peak:</td>
              <td data-testid="month-peak-mw" className="peak-value">{formatPower(monthPeakMw)}</td>
            </tr>
            <tr>
              <td>Rate:</td>
              <td className="peak-value">{formatYuan(demandRateYuanPerMwMonth, 0)}/MW·month</td>
            </tr>
            <tr>
              <td>Exposure:</td>
              <td data-testid="demand-exposure" className="peak-value peak-value--highlight">
                {formatYuan(exposure, 0)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
