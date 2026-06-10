## 2. MDP specification
> **Owner:** rl-architect

| Element | Value |
|---|---|
| Timestep `Δt` | 1 hour in `EnergyStorageEnvV2` (15-min in design docs / data pipeline — pick one and be consistent) |
| Episode | Training: 7 days (168 steps), random start in synthetic year. Eval: 365 days (8760 steps) |
| Discount γ | 0.999 |
| Observation | 11 base dims + 24×4 forecast dims = **107** |
| Action | **6-dim continuous** (see §4) |

### 2.1 Observation vector

Base (11):
```
[ wind_speed_mps, irradiance_wm2, temperature_c, load_MW,
  SOC, current_price, month_peak/500,
  sin(2πh/24), cos(2πh/24), sin(2πm/12), cos(2πm/12) ]
```

Forecast (24 steps × 4 vars, 1-hour resolution over next 24 h), normalized:
```
[ wind/20, irradiance/1000, load_kw/100000, price ]  × 24
```
Forecast noise grows linearly with horizon (config: 10% at max horizon) — agent must plan under uncertainty.

Observations are further normalized at training time by `VecNormalize` (running mean/std, clip ±10).

### 2.2 Action vector (explicit flow control, "Energy Router")

```
a[0] = a_bat            ∈ [-1, 1]   battery: + charge, − discharge (× max power)
a[1] = f_solar→load     ∈ [0, 1]
a[2] = f_solar→bat      ∈ [0, 1]
a[3] = f_wind→load      ∈ [0, 1]
a[4] = f_wind→bat       ∈ [0, 1]
a[5] = f_bat→load       ∈ [0, 1]   (remainder of discharge goes to grid)
```
If `f_x→load + f_x→bat > 1`, renormalize to sum 1. Unallocated renewable goes to grid.

---

