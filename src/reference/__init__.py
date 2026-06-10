"""
reference — pure-Python / NumPy reference implementation of the Gansu Energy GO environment.

This package is the ground-truth fixture against which the JAX core validates parity (D11).
It is NOT used for training.

Public API:
    from reference.gansu_params import GansuParams
    from reference.tariff import get_price
    from reference.gansu_env import (
        EnvState, StepResult,
        wind_power, solar_power, compute_sell_price,
        battery_step, env_step, generate_year, get_obs,
        MONTH_OF_STEP,
    )
"""
