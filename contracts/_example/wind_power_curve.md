# Contract: Wind Power Curve (WORKED EXAMPLE)

> This is the project's reference example of a contract + test-case pair.
> Copy this structure for real features. The matching test file is
> `contracts/_example/test_env_wind_power_curve.py` (kept here, NOT in `tests/`,
> so pytest doesn't collect it in real runs); a real feature's tests go in
> `tests/env/test_env_<feature>.py`.

- **Status:** locked v1 (example)
- **Spec:** REBUILD_SPEC.md §3.1 (wind), §3.6 row 11 (operating range)
- **Owner:** jax-env-engineer · **Reviewer:** backend-reviewer

## Interface

```python
def wind_power(v_10m: Array, params: WindParams) -> Array:
    """Fleet power output in MW from 10 m wind speed in m/s. Jittable, vmappable."""

class WindParams(NamedTuple):
    p_rated_mw: float   # 4.2 (Vestas V150-4.2MW reference)
    v_cutin: float      # 3.0 m/s
    v_rated: float      # 12.0 m/s
    v_cutout: float     # 25.0 m/s
    hub_height_m: float # 105.0
```

## Behavior

```
v_hub = v_10m · (hub_height_m / 10)^0.14          # power-law shear, open terrain
P = 0                                              if v_hub < v_cutin  or v_hub ≥ v_cutout
P = p_rated · ((v_hub − v_cutin)/(v_rated − v_cutin))³   if v_cutin ≤ v_hub < v_rated
P = p_rated                                        if v_rated ≤ v_hub < v_cutout
```

## Units & ranges
- Input `v_10m`: m/s, expected [0, 25] (generator clips upstream, but this function must be safe for any v ≥ 0).
- Output: **MW** (not kW), range [0, p_rated].

## Edge behavior (testable commitments)
- `v_hub == v_cutin` → 0 MW (cubic term is exactly 0).
- `v_hub == v_cutout` → 0 MW (cut-out is **inclusive**: `v ≥ v_cutout`).
- `v_hub == v_rated` → exactly p_rated.
- Negative or NaN input: out of contract; upstream generator guarantees v ≥ 0.

## Deliberate deviations from old code
- None — this formula is ported as-is.

## Out of scope
- Air-density correction, wake losses, turbine availability (REBUILD_SPEC.md §3.6 "Not modeled").
