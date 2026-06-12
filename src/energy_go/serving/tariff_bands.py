"""energy_go.serving.tariff_bands — server-side TariffBand derivation.

Contract: contracts/serving/geo_site_api.md §3.3, §3.4, §6.3
Consumed by: geo_site_api.py

Derivation rule (tariff_model_schema §7.1):
  Run-length encoding of a 24-element hourly price row → list of TariffBand.
  Band name lookup: price value → name (Gansu initial).
  Unknown price values fall back to "tier_{price:.0f}".

Units: price_yuan_per_mwh is ¥/MWh (float); start_hour / end_hour are int [0, 24).
"""
from __future__ import annotations

from typing import NamedTuple


# ---------------------------------------------------------------------------
# Band name lookup — Gansu initial (tariff_model_schema §7.1)
# ---------------------------------------------------------------------------

# Keys: float price in ¥/MWh; values: canonical band name.
# Unknown prices fall back to "tier_{price:.0f}".
_BAND_NAME: dict[float, str] = {
    250.0: "valley",
    450.0: "mid",
    620.0: "peak",
    780.0: "critical_peak",
}


class TariffBandDTO(NamedTuple):
    """Serialisable TariffBand for the REST response.

    start_hour : int  — inclusive, 0–23
    end_hour   : int  — exclusive, 1–24
    name       : str  — e.g. "valley", "mid", "peak", "critical_peak"
    price_yuan_per_mwh : float — ¥/MWh, uniform within band
    """
    name: str
    start_hour: int
    end_hour: int
    price_yuan_per_mwh: float


def _band_name(price: float) -> str:
    """Look up canonical band name or fall back to "tier_{price:.0f}"."""
    # normalise float32 NaN/Inf to "tier_nan" / "tier_inf" gracefully
    name = _BAND_NAME.get(float(price))
    if name is not None:
        return name
    try:
        return f"tier_{price:.0f}"
    except (ValueError, OverflowError):
        return "tier_unknown"


def derive_bands(price_row: list[float] | "np.ndarray") -> list[TariffBandDTO]:  # type: ignore[name-defined]
    """Run-length encode a 24-element hourly price row into TariffBand list.

    Each contiguous run of equal prices becomes one TariffBand.
    Bands are ordered by start_hour ascending; together they cover [0, 24).

    Parameters
    ----------
    price_row :
        24-element iterable of float prices (¥/MWh).  Equality is tested by
        rounding to 2 decimal places to handle float32 precision.

    Returns
    -------
    list[TariffBandDTO]
        Non-empty; first start_hour == 0; last end_hour == 24.

    Raises
    ------
    ValueError
        If ``price_row`` does not have exactly 24 elements.
    """
    prices = [float(p) for p in price_row]
    if len(prices) != 24:
        raise ValueError(f"price_row must have exactly 24 elements; got {len(prices)}")

    bands: list[TariffBandDTO] = []
    run_start = 0
    run_price = prices[0]

    for h in range(1, 24):
        if round(prices[h], 2) != round(run_price, 2):
            bands.append(TariffBandDTO(
                name=_band_name(run_price),
                start_hour=run_start,
                end_hour=h,
                price_yuan_per_mwh=float(run_price),
            ))
            run_start = h
            run_price = prices[h]

    # flush final run
    bands.append(TariffBandDTO(
        name=_band_name(run_price),
        start_hour=run_start,
        end_hour=24,
        price_yuan_per_mwh=float(run_price),
    ))

    return bands
