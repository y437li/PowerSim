"""Gansu TOU tariff — get_price(hour, minute) → ¥/MWh.

Implements §3.7 with D8 minute-accuracy fix.
Priority order (highest wins): critical_peak → peak → mid → valley.

Tier table:
    Critical peak (780 ¥/MWh):
        10:30–11:30  (h==10 and m>=30) or (h==11 and m<30)
        19:00–21:00  h in {19, 20}
    Peak (620 ¥/MWh):
        08:00–10:30  (8 <= h < 10) or (h==10 and m<30)
        18:00–19:00  h == 18
        21:00–23:00  21 <= h < 23
    Mid (450 ¥/MWh):
        07:00–08:00  h == 7
        11:30–18:00  (h==11 and m>=30) or (12 <= h < 18)
    Valley (250 ¥/MWh):
        23:00–07:00  (23 <= h < 24) or (0 <= h < 7)

At Δt=1 h all steps land on :00 (minute=0), so minute is always 0 in practice;
the function remains correct and future-proof for sub-hourly Δt.
"""

_CRITICAL_PEAK = 780.0
_PEAK          = 620.0
_MID           = 450.0
_VALLEY        = 250.0


def get_price(hour: int, minute: int = 0) -> float:
    """Return Gansu TOU buy price in ¥/MWh for the given (hour, minute).

    Parameters
    ----------
    hour:   0–23 (integer hour of day)
    minute: 0–59 (integer minute within the hour; default 0)

    Returns
    -------
    Buy price in ¥/MWh ∈ {250, 450, 620, 780}.
    """
    # --- Critical peak ---
    # 10:30–11:30
    if (hour == 10 and minute >= 30) or (hour == 11 and minute < 30):
        return _CRITICAL_PEAK
    # 19:00–21:00
    if hour in (19, 20):
        return _CRITICAL_PEAK

    # --- Peak ---
    # 08:00–10:30
    if (8 <= hour < 10) or (hour == 10 and minute < 30):
        return _PEAK
    # 18:00–19:00
    if hour == 18:
        return _PEAK
    # 21:00–23:00
    if 21 <= hour < 23:
        return _PEAK

    # --- Mid ---
    # 07:00–08:00
    if hour == 7:
        return _MID
    # 11:30–18:00
    if (hour == 11 and minute >= 30) or (12 <= hour < 18):
        return _MID

    # --- Valley (default: 23:00–07:00) ---
    return _VALLEY
