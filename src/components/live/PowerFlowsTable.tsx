import React from "react";
import type { PowerFlows, GenerationBlock } from "../../types/telemetry";
import { formatPower } from "../../utils/units";

interface PowerFlowsTableProps {
  flows: PowerFlows;
  generation: GenerationBlock;
}

const FLOW_ROWS: Array<{ label: string; field: keyof PowerFlows }> = [
  { label: "Solar → Load",          field: "solar_to_load_mw" },
  { label: "Solar → Battery",       field: "solar_to_bat_mw" },
  { label: "Solar → Grid",          field: "solar_to_grid_mw" },
  { label: "Wind → Load",           field: "wind_to_load_mw" },
  { label: "Wind → Battery",        field: "wind_to_bat_mw" },
  { label: "Wind → Grid",           field: "wind_to_grid_mw" },
  { label: "Battery → Load",        field: "bat_to_load_mw" },
  { label: "Battery → Grid",        field: "bat_to_grid_mw" },
  { label: "Grid → Load",           field: "grid_to_load_mw" },
  { label: "Grid → Battery",        field: "grid_to_bat_mw" },
  { label: "Solar curtailed",       field: "solar_curtailed_mw" },
  { label: "Wind curtailed",        field: "wind_curtailed_mw" },
  { label: "Battery curtailed",     field: "bat_curtailed_mw" },
  { label: "Unserved load (VOLL)",  field: "load_unserved_mw" },
];

export function PowerFlowsTable({ flows, generation }: PowerFlowsTableProps): JSX.Element {
  return (
    <div data-testid="power-flows-table" className="card power-flows-table">
      <div className="card__title">Power Flows</div>
      <div className="card__body">
        <table className="flows-table">
          <thead>
            <tr>
              <th>Flow</th>
              <th className="flows-table__value">MW</th>
            </tr>
          </thead>
          <tbody>
            {FLOW_ROWS.map(({ label, field }) => {
              const mw = flows[field];
              return (
                <tr
                  key={field}
                  data-field={field}
                  className={mw > 0 ? "flows-row flows-row--nonzero" : "flows-row flows-row--zero"}
                >
                  <td>{label}</td>
                  <td className="flows-table__value">{formatPower(mw)}</td>
                </tr>
              );
            })}
            <tr
              data-field="gross_solar_mw"
              className={generation.gross_solar_mw > 0 ? "flows-row flows-row--nonzero" : "flows-row flows-row--zero"}
            >
              <td>Gross solar</td>
              <td className="flows-table__value">{formatPower(generation.gross_solar_mw)}</td>
            </tr>
            <tr
              data-field="gross_wind_mw"
              className={generation.gross_wind_mw > 0 ? "flows-row flows-row--nonzero" : "flows-row flows-row--zero"}
            >
              <td>Gross wind</td>
              <td className="flows-table__value">{formatPower(generation.gross_wind_mw)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
