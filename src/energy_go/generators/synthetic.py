"""energy_go.generators.synthetic — pure-JAX synthetic year generator.

Contract: contracts/env/jax_env_core.md §5.1
Spec: §4.1 (weather), §4.2 (load, D19)
"""
from __future__ import annotations
import jax
import jax.numpy as jnp

SyntheticYear = jax.Array  # shape (8760, 4), float32 — [wind_mps, irr_wm2, temp_c, load_mw]


def generate_year(key: jax.Array) -> SyntheticYear:
    """Generate one synthetic year (8760 × 4) float32 following §4.1, §4.2 (D19).

    Columns: [wind_mps, irr_wm2, temp_c, load_mw]
    Fixed key → identical output.
    """
    # Split key into independent subkeys
    k_wind, k_cloud_do, k_cloud_v, k_temp, k_load = jax.random.split(key, 5)

    t_arr = jnp.arange(8760, dtype=jnp.float32)
    d_arr = (t_arr / 24.0).astype(jnp.int32).astype(jnp.float32)  # day of year 0-based
    h_arr = (t_arr % 24.0)                                         # hour of day 0-based

    # ---- Wind AR1 (§4.1) ----
    # η[t] = 0.95·η[t−1] + sqrt(1−0.95²)·z[t], wind scaled by 2
    _rho_w = 0.95
    _sig_w = jnp.sqrt(1.0 - _rho_w ** 2)
    eta_z = jax.random.normal(k_wind, shape=(8760,))

    def wind_ar1_step(carry, z):
        eta = _rho_w * carry + _sig_w * z
        return eta, eta

    _, eta = jax.lax.scan(wind_ar1_step, jnp.float32(0.0), eta_z)

    wind_base = (6.0
                 + 2.0 * jnp.sin(2.0 * jnp.pi * (t_arr / 24.0 - 0.25))
                 + 2.0 * jnp.cos(2.0 * jnp.pi * t_arr / 8760.0)
                 + eta * 2.0)
    wind_mps = jnp.clip(wind_base, 0.0, 25.0)

    # ---- Solar (§4.1) ----
    sunrise = 6.0 - 2.0 * jnp.cos(2.0 * jnp.pi * d_arr / 365.0)
    sunset  = 18.0 + 2.0 * jnp.cos(2.0 * jnp.pi * d_arr / 365.0)
    mid     = (sunrise + sunset) / 2.0
    daylen  = sunset - sunrise

    base = 1000.0 * jnp.maximum(
        0.0, 1.0 - ((h_arr - mid) / (daylen / 2.0 + 1e-9)) ** 2
    )
    # Zero out base when outside [sunrise, sunset)
    in_daylight = (h_arr >= sunrise) & (h_arr < sunset)
    base = jnp.where(in_daylight, base, 0.0)

    seasonal = 0.7 + 0.3 * jnp.cos(2.0 * jnp.pi * (d_arr - 172.0) / 365.0)

    cloud_uniform = jax.random.uniform(k_cloud_do, shape=(8760,))
    cloud_v       = jax.random.uniform(k_cloud_v, shape=(8760,), minval=0.2, maxval=0.8)
    cloud         = jnp.where(cloud_uniform < 0.3, cloud_v, 1.0)

    irr_wm2 = jnp.maximum(0.0, base * seasonal * cloud)

    # ---- Temperature (§4.1) ----
    temp_z = jax.random.normal(k_temp, shape=(8760,))
    temp_c = (20.0
              + 8.0  * jnp.sin(2.0 * jnp.pi * (h_arr - 9.0) / 24.0)
              + 15.0 * jnp.cos(2.0 * jnp.pi * (d_arr - 200.0) / 365.0)
              + 2.0  * temp_z)

    # ---- Load (§4.2, D19: base=75_000 kW, α=4_500, β=3_750, σ=5_000 kW) ----
    # AR1: φ[t] = 0.8·φ[t−1] + sqrt(1−0.8²)·z[t], contribution = φ·5000 kW
    _rho_l = 0.8
    _sig_l = jnp.sqrt(1.0 - _rho_l ** 2)
    phi_z = jax.random.normal(k_load, shape=(8760,))

    def load_ar1_step(carry, z):
        phi = _rho_l * carry + _sig_l * z
        return phi, phi

    _, phi = jax.lax.scan(load_ar1_step, jnp.float32(0.0), phi_z)

    # Hour profile: triangle from 0.5 at midnight to 1.0 at noon, back to 0.5
    hour_profile = 0.5 + 0.5 * (1.0 - jnp.abs(h_arr - 12.0) / 12.0)

    # Day-of-week factor: d%7: Mon=0→1.0 ... Sat=5→0.7, Sun=6→0.6
    d_int = d_arr.astype(jnp.int32)
    dow_table = jnp.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.7, 0.6], dtype=jnp.float32)
    dow_factor = dow_table[d_int % 7]

    cdd = jnp.maximum(0.0, temp_c - 18.0)
    hdd = jnp.maximum(0.0, 18.0 - temp_c)

    L_kw = (75_000.0 * hour_profile * dow_factor
            + 4_500.0 * cdd
            + 3_750.0 * hdd
            + phi * 5_000.0)
    load_mw = jnp.maximum(0.0, L_kw) / 1000.0

    return jnp.stack([wind_mps, irr_wm2, temp_c, load_mw], axis=1).astype(jnp.float32)
