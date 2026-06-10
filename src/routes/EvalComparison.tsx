import { useEvalStore } from "../stores/evalStore";
import { Card } from "../components/Card";
import { formatYuan } from "../utils/units";

/**
 * Route: /eval — policy comparison table.
 * Named export so tests can import { EvalComparison } directly.
 */
export function EvalComparison() {
  const latest = useEvalStore((s) => s.latest);

  return (
    <div data-testid="eval-comparison" className="route-eval-comparison">
      <Card title="Policy Evaluation">
        {latest === null ? (
          <p className="eval-comparison__empty">No eval run yet.</p>
        ) : (
          <table className="eval-comparison__table">
            <thead>
              <tr>
                <th>Policy</th>
                <th>Energy Cost</th>
                <th>Demand Charge</th>
                <th>Degradation</th>
                <th>Curtailment</th>
                <th>VOLL</th>
                <th>Total Cost</th>
              </tr>
            </thead>
            <tbody>
              {(["rl", "no_battery", "rule_based_tou"] as const).map((key) => {
                const p = latest.policies[key];
                return (
                  <tr key={key}>
                    <td>{key}</td>
                    <td>{formatYuan(p.energy_cost_yuan)}</td>
                    <td>{formatYuan(p.demand_charge_yuan)}</td>
                    <td>{formatYuan(p.degradation_yuan)}</td>
                    <td>{formatYuan(p.curtailment_yuan)}</td>
                    <td>{formatYuan(p.voll_yuan)}</td>
                    <td>{formatYuan(p.total_cost_yuan)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

export default EvalComparison;
