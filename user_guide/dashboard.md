# The dashboard

The live dashboard sits on the **Site View** (`/` route, the app's home page), beside the [3D site view](site_view_3d.md). It updates in real time from the inference telemetry stream (`env_step` messages over a websocket). Every value on the wire is in **MW, MWh, ¥, or ¥/MWh**; the dashboard converts only for display.

> All numbers conform to the LOCKED telemetry schema (`contracts/shared/telemetry_schema.md` v1.0.0) and the D13 cost-accounting decision (real-money vs. reward-basis totals).

## When there's no data yet

The dashboard has three states, so a blank panel is never ambiguous:

- **Disconnected, no data** — blank panel; the status banner at the top is the signal.
- **Connected, no data yet** — a "Waiting for live data…" spinner. You'll see this until an [inference session](sessions.md) is running and streaming steps.
- **Streaming** — the full card grid below.

The **status banner** also warns when the stream goes stale or a sequence gap is detected (dropped frames).

## Cards

### Cost Breakdown

The headline is the **cumulative real-money cost** so far (`cost_total_real_yuan_cum`). Below it, the **per-step** breakdown (real money, per D13):

| Row | Meaning |
|---|---|
| **Energy** | Net energy cost; shown as revenue (highlighted) when negative (you earned more from export than you paid to import) |
| ↳ Import / ↳ Export | Display-only decomposition of the Energy row (not separate charges) |
| **Demand charge** | Charge on the monthly peak grid import (booked monthly — see Monthly Peak below) |
| **Degradation** | Battery wear cost for this step |
| **Curtailment** | Penalty for spilled renewable energy |
| **VOLL** | Value-of-lost-load penalty for any unserved demand |
| **Step total** | Sum of the real-money rows for the step |

### Monthly Peak

Tracks the running **monthly peak grid import (MW)** — the quantity the demand charge is billed on (¥/MW·month; `demand_rate_yuan_per_mw_month = 32 000`). Shaving this peak is one of the agent's three levers, so this card shows the headroom against the current month's maximum.

### Power Flows

A per-step table of where energy is going: generation (wind / solar), battery charge/discharge, grid import/export, load served, and any curtailed or unserved power. This is the physical energy balance behind the cost numbers.

### SOC timeline

The battery **state-of-charge** over recent steps, with the operating band drawn in. SOC is bounded to **[0.2, 0.9]** (decision D4); the agent charges in cheap hours and discharges into expensive ones without leaving the band.

### Price timeline

The buy price over recent steps with the **time-of-use (TOU) bands** shaded — valley (≈¥0.25/kWh), peak, and critical-peak (≈¥0.78/kWh). Reading the SOC and price timelines together shows the arbitrage: charge low, discharge high.

### Alerts

A newest-first list of **constraint events** as they happen, each with the ¥ penalty it incurred:

- **Curtailment** — renewable energy spilled (`X MW curtailed`).
- **VOLL** — load went unserved (`X MW unserved`).
- **SOC violation** — battery pushed past its SOC bound (`X MWh overshoot`).

A healthy, well-trained policy produces few or no alerts.

## Eval comparison (`/eval`)

The **Eval** tab compares the trained RL policy against two baselines on a full-year evaluation:

| Policy | What it is |
|---|---|
| `rl` | The trained SAC policy |
| `no_battery` | Battery never used (pass-through baseline) |
| `rule_based_tou` | Simple time-of-use rule (charge in valley, discharge in peak) |

Columns: **Energy cost, Demand charge, Degradation, Curtailment, VOLL, Total cost** — all in ¥, real-money basis. The table appears once an evaluation has been run (until then: "No eval run yet."). The same comparison also appears at the bottom of the [training panel](training.md) when an eval result is available for the selected run.
