## 1. What the system is
> **Owner:** rl-architect

An RL agent (SAC) controls a grid-connected **wind + solar + battery** plant (modeled on Gansu/Jiuquan, China) to minimize total electricity cost:

```
minimize  Σ_t [ Energy_Cost + Demand_Charge + Battery_Degradation + Penalties ]
```

via **time-of-use arbitrage** (charge at ¥0.25 valley, discharge at ¥0.78 critical peak), **peak shaving** (demand charge ¥32/kW·month on monthly max grid import), and **renewable routing** (self-consume vs. sell vs. store).

**Site totals (Gansu config):** Wind 615 MW, Solar 330 MW, Battery 294.5 MWh / 98.16 MW, Load 50–100 MW, PCC export limit 945 MW (200 MW in the YAML grid section), import limit 400 MW.

---

