import React from "react";
import { Card } from "../Card";
import { formatYuan } from "../../utils/units";
import type { EvalComparePayload, PolicyMetrics } from "../../types/telemetry";

// Type alias: policies map is keyed by policy name; the concrete type has fixed keys
// but we need string indexing for runtime iteration over Object.keys().
type PoliciesRecord = Record<string, PolicyMetrics>;

interface EvalCompareTableProps {
  latest: EvalComparePayload | null;
}

/** Display names for known policy keys. Unknown keys get title-cased fallback. */
const POLICY_DISPLAY_NAMES: Record<string, string> = {
  rl:                  "RL Agent",
  no_battery:          "No Battery",
  rule_based_tou:      "Rule-Based TOU",
  greedy:              "Greedy",
  dp_oracle:           "DP Oracle",
  mpc:                 "MPC",
  simulated_annealing: "Sim. Annealing",
  ant_colony:          "Ant Colony",
};

function policyDisplayName(key: string): string {
  return (
    POLICY_DISPLAY_NAMES[key] ??
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/**
 * Comparison table: RL vs all baseline policies.
 * - Iterates Object.keys(policies) — extensible, no hardcoded list.
 * - RL row is always first.
 * - Best-cost row gets data-best="true".
 * - Tie rule: RL wins ties (§5: RL ≤ baselines; equality satisfies ≤).
 * - total_cost_yuan = energy + demand_charge + degradation + curtailment + voll (D13 real money).
 * - SOC violations + penalty excluded from total, reported in separate columns.
 */
export function EvalCompareTable({ latest }: EvalCompareTableProps): JSX.Element {
  if (!latest) {
    return (
      <Card title="Policy Comparison (latest eval)">
        <p className="eval-table__empty">
          No eval run yet — waiting for first 365-day eval
        </p>
      </Card>
    );
  }

  const keys = Object.keys(latest.policies);
  // RL first, remaining sorted by total_cost_yuan ascending
  const otherKeys = keys
    .filter((k) => k !== "rl")
    .sort(
      (a, b) =>
        (latest.policies as PoliciesRecord)[a].total_cost_yuan - (latest.policies as PoliciesRecord)[b].total_cost_yuan
    );
  const orderedKeys = keys.includes("rl") ? ["rl", ...otherKeys] : otherKeys;

  // Determine which key has the best (lowest) total_cost_yuan.
  // Tie-break: rl wins ties.
  const minCost = Math.min(...keys.map((k) => (latest.policies as PoliciesRecord)[k].total_cost_yuan));
  const tiedKeys = keys.filter(
    (k) => (latest.policies as PoliciesRecord)[k].total_cost_yuan === minCost
  );
  const bestKey =
    tiedKeys.includes("rl") ? "rl" : tiedKeys[0];

  return (
    <Card title="Policy Comparison (latest eval)">
      <div className="eval-table-wrapper">
        <table className="eval-table">
          <thead>
            <tr>
              <th>Policy</th>
              <th>Energy Cost</th>
              <th>Demand Charge</th>
              <th>Degradation</th>
              <th>Curtailment</th>
              <th>VOLL</th>
              <th><strong>Total Cost</strong></th>
              <th>SOC Violations</th>
              <th>SOC Penalty (¥) †</th>
            </tr>
          </thead>
          <tbody>
            {orderedKeys.map((key) => {
              const p = (latest.policies as PoliciesRecord)[key];
              const isBest = key === bestKey;
              return (
                <tr
                  key={key}
                  data-best={isBest ? "true" : undefined}
                  className={isBest ? "row-best" : undefined}
                >
                  <td>{policyDisplayName(key)}</td>
                  <td>{formatYuan(p.energy_cost_yuan, 0)}</td>
                  <td>{formatYuan(p.demand_charge_yuan, 0)}</td>
                  <td>{formatYuan(p.degradation_yuan, 0)}</td>
                  <td>{formatYuan(p.curtailment_yuan, 0)}</td>
                  <td>{formatYuan(p.voll_yuan, 0)}</td>
                  <td><strong>{formatYuan(p.total_cost_yuan, 0)}</strong></td>
                  <td>{p.soc_violations_count}</td>
                  <td>{formatYuan(p.penalty_yuan, 0)}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={9} className="eval-table__footnote">
                † SOC penalty excluded from Total Cost (reward-basis safety metric)
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}
