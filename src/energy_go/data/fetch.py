"""energy_go.data.fetch — Open-Meteo fetch + deterministic local cache.

Contract: contracts/harness/weather_pipeline.md §2.3, §4.1, §12.1

ATTRIBUTION (carry-forward, contract §1 blocker):
    Open-Meteo is licensed CC BY 4.0 (https://open-meteo.com).
    Underlying ERA5 reanalysis data is from Copernicus Climate Change Service.
    Local research caching is clearly permitted.
    Required attribution: "Weather data by Open-Meteo.com (CC BY 4.0);
    powered by ERA5 data from the Copernicus Climate Change Service."
    Redistributing cached or derived arrays in a public package requires
    explicit confirmation of redistribution terms — coordinate with maintainers
    before any bundling. (Contract §1 open item; resolved before merge.)

Pure Python — never called inside jit.  Produces a Parquet cache file read by
transform.build_multi_year_array().
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Union

import numpy as np


# ---------------------------------------------------------------------------
# Cache-path helper
# ---------------------------------------------------------------------------

def make_cache_path(
    source: str,
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
    cache_dir: Union[str, Path] = "data/weather_cache",
) -> Path:
    """Return the deterministic Parquet cache path for a (source, lat, lon, years) key.

    Format: <cache_dir>/<source>_<lat5>_<lon5>_<start_year>_<end_year>.parquet

    lat5 / lon5 are the coordinates rounded to 5 decimal places to ensure
    a stable, collision-resistant cache key that matches Open-Meteo's grid snap.

    Returns:
        Path (file may or may not yet exist)
    """
    cache_dir = Path(cache_dir)
    lat5 = f"{float(lat):.5f}"
    lon5 = f"{float(lon):.5f}"
    fname = f"{source}_{lat5}_{lon5}_{start_year}_{end_year}.parquet"
    return cache_dir / fname


# ---------------------------------------------------------------------------
# Fetch (requires `requests` + `pandas`; lazily imported to avoid hard dep)
# ---------------------------------------------------------------------------

_OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_DEFAULT_VARIABLES = (
    "wind_speed_10m",
    "wind_speed_100m",
    "shortwave_radiation",
    "temperature_2m",
)


def fetch_weather_history(
    lat: float,
    lon: float,
    years: list,
    cache_dir: Union[str, Path] = "data/weather_cache",
    source: str = "open_meteo",
    variables: tuple = _DEFAULT_VARIABLES,
) -> Path:
    """Fetch multi-year hourly weather from Open-Meteo; cache to Parquet.

    Climate nonstationarity: the fetched record is EMPIRICAL — no detrending,
    no bias correction, no weighting.  The decade-as-observed is the target
    distribution.  (task #69 input #4; contract §3.5)

    Args:
        lat:       Site latitude (decimal degrees N positive).
        lon:       Site longitude (decimal degrees E positive).
        years:     List of calendar years to fetch (e.g. list(range(2014, 2024))).
        cache_dir: Local cache root; file is written on cache miss.
        source:    Data source identifier; only "open_meteo" is supported in v1.
        variables: Open-Meteo hourly variables to request.

    Returns:
        Path to the merged multi-year Parquet cache file.  On cache hit the file
        already exists and no network call is made.

    Raises:
        ValueError:   if source is not "open_meteo".
        RuntimeError: if the HTTP request fails and no cache exists.
    """
    if source != "open_meteo":
        raise ValueError(
            f"Unsupported source '{source}'; only 'open_meteo' is supported in v1."
        )

    try:
        import pandas as pd
        import requests
    except ImportError as e:
        raise ImportError(
            "fetch_weather_history requires 'requests' and 'pandas'. "
            "Install them with: pip install requests pandas pyarrow"
        ) from e

    years = sorted(years)
    start_year = years[0]
    end_year   = years[-1]
    cache_dir  = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = make_cache_path(source, lat, lon, start_year, end_year, cache_dir)

    if cache_path.exists():
        return cache_path

    # Fetch year by year and merge
    all_frames = []
    for year in years:
        start_date = f"{year}-01-01"
        end_date   = f"{year}-12-31"

        params = {
            "latitude":  lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date":   end_date,
            "hourly":    ",".join(variables),
            "timezone":  "UTC",
            "wind_speed_unit": "ms",  # metres per second
        }

        # Retry once with a brief backoff on transient failures
        for attempt in range(2):
            try:
                resp = requests.get(_OPEN_METEO_ARCHIVE_URL, params=params, timeout=60)
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 0:
                    time.sleep(5)
                    continue
                raise RuntimeError(
                    f"Open-Meteo fetch failed for year {year}: {exc}"
                ) from exc

        data = resp.json()
        hourly = data["hourly"]

        frame = pd.DataFrame({
            "time": pd.to_datetime(hourly["time"]),
            **{v: np.array(hourly[v], dtype=np.float32) for v in variables},
        })
        all_frames.append(frame)

    merged = pd.concat(all_frames, ignore_index=True)
    merged = merged.sort_values("time").reset_index(drop=True)
    merged.to_parquet(cache_path, index=False)
    return cache_path
