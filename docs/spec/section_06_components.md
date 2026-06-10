## 6. System components (current architecture)
> **Owner:** rl-architect

| Component | Role | Keep in rebuild? |
|---|---|---|
| `gym_energy_router` (pip pkg) | Env + physics + generators | Yes — this is the core |
| `python/env/power_env.py` | `EnergyStorageEnvV2` (107-obs, 6-action) | Yes |
| `python/agents/` | SAC train / eval / baselines | Yes |
| `rust_core` (PyO3) | Battery + sim hot loop in Rust | Superseded if you move to JAX |
| `python/backend_server.py` + routers/managers/services | API: training control, live inference stream, LLM analysis | Yes (serving layer) |
| `energy_go_web` (React+Vite) | Dashboard reading `live_metrics.json` / API | Yes |
| `config/*.yaml` | Asset library (12 turbines, 10 PV, 12 batteries) + site configs | Yes — keep config-driven design |

### Known inconsistencies to fix in the rebuild
- **Timestep:** docs/config say 15 min; `EnergyStorageEnvV2` runs 1 h (`self.dt=1.0`) while forecast indexing uses `step_stride = hours*4` (assumes 15-min rows). Pick **one** Δt and audit every formula.
- **SOC bounds:** docs 10–90%, code 20–90%.
- **Export limit:** `GridParams.max_export_mw=945` vs YAML `grid_connection.max_export_mw=200`.
- Forecast obs price lookup uses `hour` only (drops the minute) — mid-tier boundaries (10:30, 11:30) are wrong in forecasts.
- **Forecast noise is never applied:** `forecast_noise_std` is stored in `__init__` but unused — `_get_obs()` reads the true future. The agent trains with perfect foresight; evaluation results overstate real-world performance. The rebuild must add horizon-scaled noise to forecast features.
- **Forecast stride off by 4×:** `step_stride = forecast_step_hours * 4` assumes 15-min rows, but data is hourly — the "24 h @ 1 h" forecast actually samples t+4h … t+96h. Also wraps around episode start via `% len(episode_data)` near episode end.
- `info['total_demand_charge']` double-counts the final month on the terminal step (already booked at termination).
- Spread noise `30 + N(0,10)` can go negative → sell price above buy price (risk-free arbitrage hole); clamp spread ≥ 0.

---

