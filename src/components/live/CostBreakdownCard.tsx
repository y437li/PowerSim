import React from "react";
import type { PerStepCosts, CumulativeCosts } from "../../types/telemetry";
import { formatYuan } from "../../utils/units";

interface CostBreakdownCardProps {
  costs: PerStepCosts;
  costCum: CumulativeCosts;
}

export function CostBreakdownCard({ costs, costCum }: CostBreakdownCardProps): JSX.Element {
  const isRevenue = costs.c_energy_yuan < 0;
  return (
    <div data-testid="cost-breakdown-card" className="card cost-breakdown-card">
      <div className="card__title">Cost Breakdown</div>
      <div className="card__body">
        <div className="cost-headline">
          Cumulative Cost:{" "}
          <span className="cost-total-cum">
            {formatYuan(costCum.cost_total_real_yuan_cum, 0)}
          </span>
        </div>
        <div className="cost-section-label">Per-step breakdown (real money — §3.4 D13):</div>
        <table className="cost-table">
          <tbody>
            <tr data-field="c_energy_yuan">
              <td>Energy</td>
              <td className={isRevenue ? "cost-value cost-value--revenue" : "cost-value"}>
                {formatYuan(costs.c_energy_yuan, 0)}
              </td>
            </tr>
            <tr data-field="c_import_yuan" data-role="decomposition">
              <td className="cost-label--sub">↳ Import</td>
              <td className="cost-value">{formatYuan(costs.c_import_yuan, 0)}</td>
            </tr>
            <tr data-field="r_export_yuan" data-role="decomposition">
              <td className="cost-label--sub">↳ Export</td>
              <td className="cost-value">{formatYuan(-costs.r_export_yuan, 0)}</td>
            </tr>
            <tr data-field="c_demand_charge_yuan">
              <td>Demand charge</td>
              <td className="cost-value">{formatYuan(costs.c_demand_charge_yuan, 0)}</td>
            </tr>
            <tr data-field="c_degradation_yuan">
              <td>Degradation</td>
              <td className="cost-value">{formatYuan(costs.c_degradation_yuan, 0)}</td>
            </tr>
            <tr data-field="c_curtail_yuan">
              <td>Curtailment</td>
              <td className="cost-value">{formatYuan(costs.c_curtail_yuan, 0)}</td>
            </tr>
            <tr data-field="c_voll_yuan">
              <td>VOLL</td>
              <td className="cost-value">{formatYuan(costs.c_voll_yuan, 0)}</td>
            </tr>
            <tr>
              <td colSpan={2}><hr /></td>
            </tr>
            <tr data-field="cost_total_real_yuan">
              <td><strong>Step total</strong></td>
              <td className="cost-value cost-value--total">
                {formatYuan(costs.cost_total_real_yuan, 0)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
