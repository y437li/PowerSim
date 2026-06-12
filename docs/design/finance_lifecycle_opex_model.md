<!--
  Finance lifecycle-events & asset-management cost model — design note by finance-expert.
  Formalizes the USER directive (2026-06-11, via team-lead): mandatory lifecycle asset events
  (battery replacement ~yr10, electrolyzer stack overhaul, etc.), standard asset-management cost
  lines ("其他行业管理"), and COST-side completeness across ALL FOUR scenarios ("场景最好都考虑到").
  Bound for §13 (project-finance SPEC), the C/D contracts, and the device_models.yaml v1.1.0
  econ-block amendment (task #57). DESIGN ONLY. ¥ (CNY), nominal, real-year-1 dispatch basis (D31/F1).
-->

# Finance lifecycle-events & asset-management cost model

> **Status:** DESIGN — bound for §13 / C-D contracts / `device_models.yaml` v1.1.0 (task #57). Default *values* are citable starting points to confirm at the USER gate; the **structure** is the deliverable. **Horizon (USER-confirmed):** 20-yr primary, 10-yr variant.

## 1. Lifecycle events — generalizing replacement (INV-DEG) into a full schedule

The §5 model already books **battery replacement CAPEX** as the cash leg of INV-DEG. The USER directive makes lifecycle events **mandatory and broader**: every device carries a schedule of **replacement** and **overhaul** events. Generalized shape:

```
lifecycle_event = {
  kind:        replacement | overhaul | subsystem_replacement,
  trigger:     { calendar_years: <int>  AND/OR  usage: cycle_life|throughput|op_hours },   # first-to-fire (§2)
  recurrence:  one_time | periodic(interval_years),
  cost_type:   capex | opex,
  cost:        fraction_of_capex | absolute_yuan,
  param_reset: full (replacement) | partial (overhaul) | none                              # what physics restores
}
```

- **replacement** = whole device swap → resets degraded physics (capacity/SOH), books replacement CAPEX.
- **subsystem_replacement** = the wear subsystem only (PV **inverter**, electrolyzer **stack**) → partial CAPEX, partial param restore.
- **overhaul** = periodic major maintenance (wind gearbox/blade, smelter reline) → OPEX (or partial CAPEX), optional partial restore.

These compose into the §5.5 cash flow: each event books its cost in the **year incurred** (lumpy), and replacement resets the device's degradation for the next interval (so a 20-yr horizon runs e.g. battery unit-1 yrs 1–10, unit-2 yrs 10–20, each with its own residual at yr 20).

## 2. Calendar-vs-throughput trigger — the reconciliation rule

The USER's "battery replacement at ~year 10" is the **calendar** prior; my INV-DEG design triggers on **throughput/cycle-life**. **Both coexist — a device is replaced at the FIRST trigger to fire:**

```
t_replace = min( lifetime_years ,  first year cumulative_throughput ≥ cycle_life · usable_energy )
```

- A **hard-cycling** policy hits cycle-life **before** year 10 → earlier replacement (preserves INV-DEG's policy-discrimination: harder cycling → worse NPV).
- A **gentle** policy → the calendar bound (year 10) governs.

This **reconciles the USER's calendar figure with the throughput design — neither is dropped.** Default battery: `lifetime_years=10` (calendar) + `cycle_life_full_equiv` (usage); first-to-fire. Same first-to-fire logic applies to subsystem/overhaul intervals where both a calendar and a usage trigger exist (else just the calendar interval).

## 3. Per-device lifecycle schedules — all four scenarios (cost-side complete)

Per the USER's "场景最好都考虑到," the **cost/lifecycle structure covers all four scenarios at design level**, even though v1 *dispatch* stays power-only. Each device's lifecycle economics live in its `device_models.yaml` econ block (task #57). Proposed defaults (overridable; confirm/cite at gate):

| Device | Scenario | Lifecycle event(s) | Proposed default | Basis (confirm) |
|---|---|---|---|---|
| **Wind turbine** | power (all) | major-component **overhaul** (gearbox/blades/generator), periodic | overhaul reserve ~1.5–2%/yr of CAPEX, or a mid-life event ~yr 10–15; calendar life ~25 yr | NREL wind O&M / ATB |
| **Solar PV** | power (all) | **inverter subsystem_replacement** ~yr 10–12; module calendar life ~25–30 yr | inverter CAPEX ≈ 10–15% of PV CAPEX, replaced once in 20 yr; `degradation_pct_per_year`≈0.5 | NREL PV / ATB inverter-replacement convention |
| **Battery** | power (all) | **replacement** at min(10 yr calendar, cycle-life) | `lifetime_years=10` + cycle-life; `replacement_capex_fraction`<1 (cost decline) | NREL storage / augmentation |
| **Grid / PCC** | power (all) | long life; transformer maintenance reserve | ~30–40 yr; small annual reserve | utility T&D norms |
| **Electrolyzer** | hydrogen | **stack subsystem_replacement / overhaul** at stack-life interval | PEM stack ~7–10 yr (≈60–90k op-h); stack ≈ 40–50% of system CAPEX; BoP lasts project | IEA/IRENA electrolyzer stack life |
| **Smelter (Al)** | aluminum | **pot reline** (periodic) | pot life ~5–8 yr → reline CAPEX at interval | Al smelting pot-life literature |
| **Datacenter IT** | datacenter-tokens | **IT-equipment refresh** (periodic, dominant) | server/accelerator refresh ~4–5 yr → recurring CAPEX | DC IT refresh-cycle norms |

v1 wires only the **power** devices (wind/PV/battery/grid); hydrogen/aluminum/datacenter device lifecycle fields are **schema-present, design-proven, not built** — exactly mirroring the §5.3 revenue-stream scope guard, now on the **cost** side too. So the cost structure is scenario-complete by config, matching the revenue structure.

## 4. Standard asset-management cost lines ("其他行业管理")

Beyond device events, the standard project cost lines. Each a **named, overridable field**; none silently dropped (USER directive) — small-but-included ones noted:

| Cost line | Level | Basis / unit | Proposed China default | v1 materiality |
|---|---|---|---|---|
| O&M — fixed | device | ¥/MW·yr | `opex_fixed_yuan_per_mw_year` (exists) | material |
| O&M — variable | device | ¥/MWh | `opex_var_yuan_per_mwh` (exists) | material |
| **Insurance** | project | %/yr of CAPEX | ~0.25–0.5%/yr | **material — include** |
| **Grid connection / transmission fee** | project | ¥/MWh exported (or ¥/yr) | per provincial tariff | **material on export volume — include** |
| Land lease | site | ¥/yr (or ¥/MW·yr) | site-specific; Gansu desert ≈ low | small but **include** (named, low default) |
| Asset-management / admin fee | project | % of revenue or ¥/yr | ~0.5–1% of revenue | small but **include** |
| **Decommissioning / salvage** | project | ¥ at EOL (net of residual) | `decommissioning_yuan`/`residual_value_fraction` (exists) | terminal — include |

**Materiality judgment (per the directive — flagged, not dropped):** insurance and grid/transmission fees are material and **included**; land lease and admin fees are typically small for a Gansu desert site but are **included as named fields with low defaults** (so a different site can raise them) rather than dropped. Nothing judged immaterial-enough to omit.

These project/site-level lines live in a **D-owned finance/scenario config** (not per-device — they're plant-wide), distinct from the per-device econ blocks.

## 5. Schema home — device-level (task #57) vs project-level (D config)

**Device-level → `device_models.yaml` econ block (task #57 v1.1.0 amendment):**
```yaml
economics:
  # ... existing capex/opex/replacement/residual fields ...
  lifecycle:
    replacement:           { trigger_calendar_years: 10, trigger_usage: cycle_life, capex_fraction: 0.6 }
    subsystem_replacement: { name: inverter, interval_years: 11, capex_fraction: 0.12 }   # PV; or stack for electrolyzer
    overhaul:              { interval_years: 12, cost_type: opex, cost_fraction_per_event: 0.05 }   # wind/smelter
```
(Only the events relevant to a device type are populated; first-to-fire on combined triggers per §2.)

**Project/site-level → D's finance/scenario config (not per-device):**
```yaml
finance_asset_management:
  insurance_pct_capex_per_year:   0.0035
  grid_connection_fee_yuan_per_mwh: <provincial>
  land_lease_yuan_per_year:       <site>
  asset_mgmt_fee_pct_revenue:     0.0075
  # decommissioning/residual already per-device
```

**Coordination ask → task #57:** the device-level `lifecycle:` sub-block widens task #57's v1.1.0 econ amendment (already adding wear/lifetime physics fields). Doing it in **one** version bump (physics wear params + econ lifecycle events together) avoids multiple bumps — flagged to rl-architect/jax-env so #57's scope covers both.

## 6. Cash-flow integration & invariants (unchanged principles)

- Lifecycle events slot into the §5.5/§5.8 cash flow as dated CAPEX (replacement, subsystem, datacenter refresh, smelter reline) or OPEX (overhaul, asset-management lines) in the year incurred; discounted per §5.8.
- **INV-DEG preserved & sharpened:** battery wear is monetized **once** — as the §2 first-to-fire replacement CAPEX — never as both the hourly proxy and the replacement (the proxy stays D13 memo-only). Overhaul OPEX for *other* devices is a genuine separate cash line (not a wear double-count), since it's maintenance, not the throughput-degradation channel.
- **Real-year-1 basis (D31/F1):** all lifecycle/asset-management costs are entered in **real year-1 ¥**; escalation (incl. any cost-specific escalation) is applied in the finance layer post-hoc, never in dispatch.
- All amounts ¥; intervals in years; rates %/yr — units explicit.

## 7. Open items

- **CAPEX/econ default *values*** (incl. these lifecycle/overhaul costs) are the USER's open decision §9-4 (ship Chinese 2024/25 benchmarks vs blank-configurable) — the **fields** are fixed here; the **numbers** confirm at gate.
- **v1 revenue streams** = `grid_export` only is still-implied-yes (cost-side scenario-completeness is design-level, matching the revenue-side scope guard) — team-lead getting explicit USER confirmation.
- The §13 SPEC formalizes §1–§6; the **C/D contracts** implement the lifecycle scheduler (C applies param resets at replacement years; D books the cash) — rl-architect reviews.
