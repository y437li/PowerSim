## 4. Synthetic data generators
> **Owner:** jax-env-engineer

All stochastic processes use a seeded RNG; one synthetic year (8760 h) is generated once, episodes are random 7-day slices (built-in domain randomization).

### 4.1 Weather

```
wind(t)  = μ_w + A_d·sin(2π(t/24 − 0.25)) + 2·cos(2πt/8760) + AR1(ρ=0.95)·σ_w
           μ_w=6, σ_w=2, A_d=2;  clip to [0, 25] m/s

solar(t) : sunrise = 6 − 2cos(2πd/365), sunset = 18 + 2cos(2πd/365)
           base = G_peak·(1 − ((h−mid)/(daylen/2))²)         # parabolic day profile
           × seasonal (0.7 + 0.3cos(2π(d−172)/365))
           × cloud: with p=0.3, factor ~ U(0.2, 0.8), else 1

temp(t)  = 20 + 8·sin(2π(h−9)/24) + 15·cos(2π(d−200)/365) + N(0,2)

AR1 noise: x_t = ρ·x_{t−1} + sqrt(1−ρ²)·N(0,1)
```

### 4.2 Load (CDD/HDD model)

```
L_t = base·hour_profile[h]·dow_factor[d] + α·CDD(T) + β·HDD(T) + AR1(ρ=0.8, σ=50)
CDD = max(T − 18, 0);  HDD = max(18 − T, 0)
base = 750 kW, α = 45 kW/°C, β = 37.5 kW/°C
dow = (1,1,1,1,1, 0.7, 0.6);  hour_profile: 0.5 nights → 1.0 work hours
```

---

