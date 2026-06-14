"""energy_go.serving.geo_site_api — Workstream A serving surface (wizard stage ①).

Contract: contracts/serving/geo_site_api.md v1.0.0
         contracts/serving/site_assemble.md v1.0.0 (D37)
Reviewer-approved tests: tests/serving/test_serving_geo_site_api.py
                         tests/serving/test_serving_site_assemble.py

Endpoints:
  POST /api/site/validate              — config validation passthrough (D32(i)/D18)
  POST /api/site/assemble              — wizard-form → site_config assembly (D37)
  GET  /api/tariff/regions             — tariff region list
  GET  /api/tariff/regions/{id}        — full region detail + monthly TariffBands
  GET  /api/tariff/bands/{id}?month=N  — single-month TariffBand slice
  POST /api/site/weather/fetch         — start weather fetch job
  GET  /api/site/weather/jobs/{id}     — poll job status
  GET  /api/site/weather-coverage      — lat/lon coverage indicator
  GET  /api/devices/models             — active device catalogue (ACTIVE_DEVICE_TYPES only)
  GET  /api/devices/models/{id}        — single active device model
  GET  /api/devices/search?q=          — autocomplete search (active types only)

Units: MW (generator power), MWh (battery energy), ¥/MWh (prices),
       ¥/MW·month (demand rate), ¥/kW / ¥/kWh (economics), m/s (wind), m (height),
       °C (temperature), W/m² (irradiance).

D32(i) / D18 single-source rule: validate() is called directly from
energy_go.env.config_validation — no rule re-implementation here.

D38: device-feed endpoints surface ACTIVE_DEVICE_TYPES only (resolver-live categories).
ACTIVE_DEVICE_TYPES is imported from energy_go.env.resolver — NOT redefined here (D18).
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from energy_go.env.resolver import ACTIVE_DEVICE_TYPES  # D38 — single-source (D18)
from energy_go.serving.tariff_bands import derive_bands

router = APIRouter()

# ---------------------------------------------------------------------------
# Config paths (resolved relative to cwd, same convention as rest_api.py)
# ---------------------------------------------------------------------------

def _config_dir() -> Path:
    return Path.cwd() / "config"


def _tariff_schema_path() -> Path:
    return _config_dir() / "tariff_model_schema.yaml"


def _device_models_path() -> Path:
    return _config_dir() / "device_models.yaml"


# ---------------------------------------------------------------------------
# Lazy-loaded singletons — loaded once per process; no reload in v1
# ---------------------------------------------------------------------------

_tariff_schema_cache: dict | None = None
_tariff_schema_lock = threading.Lock()

_device_models_cache: dict | None = None
_device_models_lock = threading.Lock()


def _get_tariff_schema() -> dict:
    """Return the loaded tariff schema (dict with 'schema_version' and 'regions')."""
    global _tariff_schema_cache
    if _tariff_schema_cache is None:
        with _tariff_schema_lock:
            if _tariff_schema_cache is None:
                from energy_go.env.tariff_model_schema import load_tariff_schema
                _tariff_schema_cache = load_tariff_schema(_tariff_schema_path())
    return _tariff_schema_cache


def _get_device_models() -> dict:
    """Return the raw device_models.yaml dict (schema_version + models dict)."""
    global _device_models_cache
    if _device_models_cache is None:
        with _device_models_lock:
            if _device_models_cache is None:
                with open(_device_models_path(), "r", encoding="utf-8") as f:
                    _device_models_cache = yaml.safe_load(f)
    return _device_models_cache


# ---------------------------------------------------------------------------
# Weather job registry (in-process, not persisted)
# ---------------------------------------------------------------------------

class _JobState:
    __slots__ = ("job_id", "status", "progress_pct", "result", "error_message",
                 "lat", "lon", "years")

    def __init__(self, job_id: str, lat: float, lon: float, years: list[int]):
        self.job_id = job_id
        self.status = "queued"
        self.progress_pct: int = 0
        self.result: dict | None = None
        self.error_message: str | None = None
        self.lat = lat
        self.lon = lon
        self.years = years


_jobs: dict[str, _JobState] = {}
_jobs_lock = threading.Lock()


def _new_job(lat: float, lon: float, years: list[int]) -> _JobState:
    job_id = "wf_" + uuid.uuid4().hex[:8]
    job = _JobState(job_id, lat, lon, years)
    with _jobs_lock:
        _jobs[job_id] = job
    return job


def _get_job(job_id: str) -> _JobState | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _run_weather_fetch(job_id: str) -> None:
    """Background task: call fetch_weather_history and update job state."""
    job = _get_job(job_id)
    if job is None:
        return

    job.status = "running"
    try:
        from energy_go.data.fetch import fetch_weather_history  # type: ignore

        cache_dir = Path.cwd() / "data" / "weather_cache"
        total = len(job.years)
        fetched_years: list[int] = []

        # Fetch year-by-year so we can update progress
        for i, year in enumerate(job.years):
            fetch_weather_history(
                lat=job.lat,
                lon=job.lon,
                years=[year],
                cache_dir=cache_dir,
                source="open_meteo",
            )
            fetched_years.append(year)
            job.progress_pct = int(100 * (i + 1) / total)

        # Final merged fetch to get the combined cache file path and stats
        merged_path = fetch_weather_history(
            lat=job.lat,
            lon=job.lon,
            years=job.years,
            cache_dir=cache_dir,
            source="open_meteo",
        )

        # Compute summary stats from the merged Parquet
        import numpy as np

        try:
            import pandas as pd
            df = pd.read_parquet(merged_path)
            wind_mean = float(np.mean(df["wind_speed_100m"].dropna()))
            irr_mean  = float(np.mean(df["shortwave_radiation"].dropna()))
            temp_mean = float(np.mean(df["temperature_2m"].dropna()))
            row_count = int(len(df))
        except Exception:
            wind_mean = irr_mean = temp_mean = 0.0
            row_count = 0

        job.result = {
            "cache_path":    str(merged_path),
            "years_cached":  fetched_years,
            "row_count":     row_count,
            "wind_mps_mean": wind_mean,   # m/s (raw wind_speed_100m, no shear transform)
            "irr_wm2_mean":  irr_mean,    # W/m²
            "temp_c_mean":   temp_mean,   # °C
        }
        job.status = "done"
        job.progress_pct = 100

    except Exception as exc:  # network failure, cache error, etc.
        job.status = "error"
        job.error_message = str(exc)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class _ValidateRequest(BaseModel):
    site_config: Any       # required; validated to be dict in endpoint
    device_models: Any = None


class _WeatherFetchRequest(BaseModel):
    lat: float
    lon: float
    years: list[int]
    # NOTE: range validation is done in the endpoint (not here) so we can emit
    # code: "WEATHER_PARAM_INVALID" instead of the app-level REQUEST_VALIDATION_ERROR.


# --- site_assemble request models (site_assemble.md v1.0.0) ---

class _FleetEntry(BaseModel):
    model_id: str
    # count: accepted as float|None (not strict int) so that fractional values
    # like 2.5 arrive here and we can emit 400 FLEET_COUNT_INVALID (not 422).
    # The endpoint validates integerness explicitly. (Reviewer note, §5.)
    count: float | None = None
    fleet_capacity_mw: float | None = None


class _CostsOverride(BaseModel):
    c_deg_yuan_per_mwh: float | None = None
    voll_yuan_per_mwh: float | None = None
    curtail_yuan_per_mwh: float | None = None
    soc_penalty_yuan_per_mwh: float | None = None
    reward_scale: float | None = None


class _ForecastOverride(BaseModel):
    sigma_max: float | None = None


class _SiteMetaInput(BaseModel):
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    province: str | None = None
    weather_mode: str | None = None


class _AssembleRequest(BaseModel):
    fleet: list[_FleetEntry] | None = None
    tariff_region: str | None = None
    site_meta: _SiteMetaInput | None = None
    costs: _CostsOverride | None = None
    forecast: _ForecastOverride | None = None


# ---------------------------------------------------------------------------
# §3.1  POST /api/site/validate
# ---------------------------------------------------------------------------

@router.post("/api/site/validate")
def site_validate(body: _ValidateRequest) -> JSONResponse:
    """D32(i)/D18: pure passthrough of energy_go.env.config_validation.validate().

    Returns HTTP 200 with errors/warnings in body regardless of validation outcome.
    HTTP 400 only for malformed request (site_config missing or not a dict).
    Never re-implements any validation rule here.
    """
    if not isinstance(body.site_config, dict):
        return JSONResponse(
            status_code=400,
            content={"detail": "site_config must be a dict", "code": "SITE_CONFIG_NOT_DICT"},
        )

    from energy_go.env.config_validation import validate  # type: ignore

    result = validate(body.site_config, body.device_models)

    def _issue(vi) -> dict:
        return {
            "rule_id":    vi.rule_id,
            "field":      vi.field,
            "message":    vi.message,
            "constraint": vi.constraint,
            # NOTE: no 'severity' field — severity is implicit per LOCKED contract §2
        }

    return JSONResponse(content={
        "errors":   [_issue(e) for e in result.errors],
        "warnings": [_issue(w) for w in result.warnings],
    })


# ---------------------------------------------------------------------------
# POST /api/site/assemble  (site_assemble.md v1.0.0 / D37)
# ---------------------------------------------------------------------------

@router.post("/api/site/assemble")
def site_assemble(body: _AssembleRequest) -> JSONResponse:
    """D37: wizard form → canonical site_config dict + immediate validation.

    Returns HTTP 200 with {site_config, errors, warnings} always.
    HTTP 400 on structural/input errors (unknown model_id, missing required
    field, invalid count, etc.) — NOT on physics validation errors.
    HTTP 422 on unparseable JSON (FastAPI default).

    Validation order (contract §5):
      1. FLEET_EMPTY
      2. TARIFF_REGION_REQUIRED
      3. DEVICE_MODEL_NOT_FOUND   (collect all missing before erroring)
      4. TARIFF_REGION_NOT_FOUND
      5. FLEET_COUNT_INVALID      (zero / negative / non-integer)
      6. PV_FLEET_CAPACITY_REQUIRED
      7. FLEET_MIXED_MODEL
    Then assemble_site_config() + config_validation.validate().
    """
    from energy_go.serving.site_assembly import assemble_site_config
    from energy_go.env.config_validation import validate as _validate  # type: ignore

    # 1. FLEET_EMPTY -------------------------------------------------------
    if not body.fleet:
        return JSONResponse(
            status_code=400,
            content={"detail": "fleet must not be empty", "code": "FLEET_EMPTY"},
        )

    # 2. TARIFF_REGION_REQUIRED --------------------------------------------
    if not body.tariff_region or not body.tariff_region.strip():
        return JSONResponse(
            status_code=400,
            content={
                "detail": "tariff_region is required",
                "code": "TARIFF_REGION_REQUIRED",
            },
        )

    tariff_region_id = body.tariff_region.strip()
    raw_dm = _get_device_models()
    models_dict = raw_dm.get("models", {})

    # 3. DEVICE_MODEL_NOT_FOUND --------------------------------------------
    missing_ids = [
        e.model_id for e in body.fleet
        if e.model_id not in models_dict
    ]
    if missing_ids:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"device model(s) not found: {missing_ids}",
                "code": "DEVICE_MODEL_NOT_FOUND",
                "missing_ids": missing_ids,
            },
        )

    # 4. TARIFF_REGION_NOT_FOUND -------------------------------------------
    tariff_schema = _get_tariff_schema()
    if tariff_region_id not in tariff_schema["regions"]:
        available = sorted(tariff_schema["regions"].keys())
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"tariff_region '{tariff_region_id}' not found",
                "code": "TARIFF_REGION_NOT_FOUND",
                "available_regions": available,
            },
        )

    # 5. FLEET_COUNT_INVALID -----------------------------------------------
    # Validate per-entry count for wind_turbine and battery:
    #   - count must be present (not None)
    #   - count must be a whole number (no 2.5 — accepted as float to catch this)
    #   - count must be ≥ 1
    # Also validates fleet_capacity_mw > 0 for pv_panel (≤ 0 → FLEET_COUNT_INVALID).
    for entry in body.fleet:
        dtype = models_dict[entry.model_id]["type"]
        if dtype in ("wind_turbine", "battery"):
            if entry.count is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            f"fleet entry '{entry.model_id}' (type: {dtype}) "
                            f"requires count"
                        ),
                        "code": "FLEET_COUNT_INVALID",
                    },
                )
            # Non-integer check (e.g. 2.5): accepted as float above; validate here.
            if entry.count != int(entry.count):
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            f"fleet entry '{entry.model_id}': count must be an integer, "
                            f"got {entry.count}"
                        ),
                        "code": "FLEET_COUNT_INVALID",
                    },
                )
            if int(entry.count) < 1:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            f"fleet entry '{entry.model_id}': count must be ≥ 1, "
                            f"got {int(entry.count)}"
                        ),
                        "code": "FLEET_COUNT_INVALID",
                    },
                )

        elif dtype == "pv_panel":
            # fleet_capacity_mw ≤ 0 treated as FLEET_COUNT_INVALID per contract §3.1.1
            if entry.fleet_capacity_mw is not None and entry.fleet_capacity_mw <= 0.0:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            f"fleet entry '{entry.model_id}': fleet_capacity_mw "
                            f"must be > 0 MW, got {entry.fleet_capacity_mw}"
                        ),
                        "code": "FLEET_COUNT_INVALID",
                    },
                )

    # 6. PV_FLEET_CAPACITY_REQUIRED ----------------------------------------
    for entry in body.fleet:
        dtype = models_dict[entry.model_id]["type"]
        if dtype == "pv_panel":
            phy = models_dict[entry.model_id].get("physics", {})
            has_per_unit = "panel_mw_per_unit" in phy
            if entry.fleet_capacity_mw is None and not has_per_unit:
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            f"fleet entry '{entry.model_id}' (pv_panel): "
                            f"fleet_capacity_mw is required (device model has no "
                            f"panel_mw_per_unit)"
                        ),
                        "code": "PV_FLEET_CAPACITY_REQUIRED",
                    },
                )

    # 7. FLEET_MIXED_MODEL -------------------------------------------------
    # After all model_ids are known-valid, check that each device type has
    # at most one distinct model_id across entries.
    type_to_models: dict[str, set[str]] = {}
    for entry in body.fleet:
        dtype = models_dict[entry.model_id]["type"]
        type_to_models.setdefault(dtype, set()).add(entry.model_id)
    for dtype, mids in type_to_models.items():
        if len(mids) > 1:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        f"fleet has {len(mids)} distinct models for device type "
                        f"'{dtype}': {sorted(mids)} — only one model per type allowed"
                    ),
                    "code": "FLEET_MIXED_MODEL",
                    "conflicting_type": dtype,
                    "conflicting_models": sorted(mids),
                },
            )

    # ------------------------------------------------------------------
    # All 400 checks passed — assemble and validate
    # ------------------------------------------------------------------

    # Prepare fleet list with integer counts for assembly
    fleet_for_assembly = [
        {
            "model_id": e.model_id,
            **({} if e.count is None else {"count": int(e.count)}),
            **({} if e.fleet_capacity_mw is None else
               {"fleet_capacity_mw": e.fleet_capacity_mw}),
        }
        for e in body.fleet
    ]

    costs_dict = body.costs.model_dump(exclude_none=True) if body.costs else None
    forecast_dict = body.forecast.model_dump(exclude_none=True) if body.forecast else None
    site_meta_dict = body.site_meta.model_dump(exclude_none=True) if body.site_meta else None

    site_config = assemble_site_config(
        fleet=fleet_for_assembly,
        tariff_region_id=tariff_region_id,
        tariff_schema=tariff_schema,
        device_models=raw_dm,
        costs_overrides=costs_dict,
        forecast_overrides=forecast_dict,
        site_meta=site_meta_dict if site_meta_dict else None,
    )

    # Validate with device_models (non-optional here — D32(i)/D18 single source)
    result = _validate(site_config, raw_dm)

    def _issue(vi) -> dict:
        return {
            "rule_id":    vi.rule_id,
            "field":      vi.field,
            "message":    vi.message,
            "constraint": vi.constraint,
        }

    return JSONResponse(content={
        "site_config": site_config,
        "errors":      [_issue(e) for e in result.errors],
        "warnings":    [_issue(w) for w in result.warnings],
    })


# ---------------------------------------------------------------------------
# §3.2  GET /api/tariff/regions
# ---------------------------------------------------------------------------

@router.get("/api/tariff/regions")
def list_tariff_regions() -> JSONResponse:
    """List all tariff region IDs with summary (price range, demand rate, provenance)."""
    schema = _get_tariff_schema()
    regions_list = []
    for region_id, region in schema["regions"].items():
        table = region.price_table_yuan_per_mwh  # shape (12, 24) ndarray
        price_min = float(table.min())
        price_max = float(table.max())
        regions_list.append({
            "region_id":                     region_id,
            "currency":                      region.currency,
            "price_min_yuan_per_mwh":        price_min,
            "price_max_yuan_per_mwh":        price_max,
            "demand_rate_yuan_per_mw_month": float(region.demand_rate_yuan_per_mw_month),
            "provenance":                    region.provenance,
        })
    return JSONResponse(content={
        "schema_version": schema.get("schema_version", "1.0.0"),
        "regions": regions_list,
    })


# ---------------------------------------------------------------------------
# §3.3  GET /api/tariff/regions/{region_id}
# ---------------------------------------------------------------------------

@router.get("/api/tariff/regions/{region_id}")
def get_tariff_region(region_id: str) -> JSONResponse:
    """Full region detail: (12,24) price table + monthly TariffBand lists."""
    schema = _get_tariff_schema()
    region = schema["regions"].get(region_id)
    if region is None:
        return JSONResponse(
            status_code=400,
            content={"detail": f"region '{region_id}' not found",
                     "code": "TARIFF_REGION_NOT_FOUND"},
        )

    table = region.price_table_yuan_per_mwh  # (12, 24) ndarray float32
    # Build monthly_bands — derive TariffBands for each of the 12 months
    monthly_bands = []
    for month_idx in range(12):
        row = table[month_idx].tolist()
        bands = derive_bands(row)
        monthly_bands.append({
            "month": month_idx,
            "bands": [
                {
                    "name":               b.name,
                    "start_hour":         b.start_hour,
                    "end_hour":           b.end_hour,
                    "price_yuan_per_mwh": b.price_yuan_per_mwh,
                }
                for b in bands
            ],
        })

    return JSONResponse(content={
        "region_id":  region_id,
        "currency":   region.currency,
        "provenance": region.provenance,
        "price_table_yuan_per_mwh": [
            [float(v) for v in table[m].tolist()]
            for m in range(12)
        ],
        "demand_rate_yuan_per_mw_month": float(region.demand_rate_yuan_per_mw_month),
        "sell_clamp": {
            "spread_yuan_per_mwh":           float(region.sell_clamp.spread_yuan_per_mwh),
            "spread_noise_std_yuan_per_mwh": float(region.sell_clamp.spread_noise_std_yuan_per_mwh),
        },
        "monthly_bands": monthly_bands,
    })


# ---------------------------------------------------------------------------
# §3.4  GET /api/tariff/bands/{region_id}?month=N
# ---------------------------------------------------------------------------

@router.get("/api/tariff/bands/{region_id}")
def get_tariff_bands(
    region_id: str,
    month: int = Query(..., description="Month index 0–11 (0=Jan, 11=Dec)"),
) -> JSONResponse:
    """Single-month TariffBand list (run-length encoded from the price table row)."""
    if not (0 <= month <= 11):
        return JSONResponse(
            status_code=400,
            content={"detail": f"month={month} outside [0, 11]",
                     "code": "TARIFF_MONTH_OUT_OF_RANGE"},
        )

    schema = _get_tariff_schema()
    region = schema["regions"].get(region_id)
    if region is None:
        return JSONResponse(
            status_code=400,
            content={"detail": f"region '{region_id}' not found",
                     "code": "TARIFF_REGION_NOT_FOUND"},
        )

    row = region.price_table_yuan_per_mwh[month].tolist()
    bands = derive_bands(row)

    return JSONResponse(content={
        "region_id": region_id,
        "month":     month,
        "bands": [
            {
                "name":               b.name,
                "start_hour":         b.start_hour,
                "end_hour":           b.end_hour,
                "price_yuan_per_mwh": b.price_yuan_per_mwh,
            }
            for b in bands
        ],
    })


# ---------------------------------------------------------------------------
# §3.5  POST /api/site/weather/fetch
# ---------------------------------------------------------------------------

@router.post("/api/site/weather/fetch")
def start_weather_fetch(
    body: _WeatherFetchRequest,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Start a weather fetch job; returns job_id immediately (non-blocking).

    Background task calls energy_go.data.fetch.fetch_weather_history().
    On cache hit, the job completes without network I/O.
    """
    # Validate lat/lon/years here (not in Pydantic) to emit WEATHER_PARAM_INVALID.
    errors: list[str] = []
    if not (-90.0 <= body.lat <= 90.0):
        errors.append(f"lat={body.lat} outside [-90, 90]")
    if not (-180.0 <= body.lon <= 180.0):
        errors.append(f"lon={body.lon} outside [-180, 180]")
    if len(body.years) == 0:
        errors.append("years list must not be empty")
    elif len(body.years) > 20:
        errors.append(f"years list too long: {len(body.years)} > 20")
    else:
        bad_years = [yr for yr in body.years if not (1940 <= yr <= 2024)]
        if bad_years:
            errors.append(f"years outside [1940, 2024]: {bad_years}")
    if errors:
        return JSONResponse(
            status_code=400,
            content={"detail": "; ".join(errors), "code": "WEATHER_PARAM_INVALID"},
        )

    job = _new_job(body.lat, body.lon, body.years)
    background_tasks.add_task(_run_weather_fetch, job.job_id)
    return JSONResponse(content={
        "job_id": job.job_id,
        "status": "queued",
        "lat":    body.lat,
        "lon":    body.lon,
        "years":  body.years,
    })



# ---------------------------------------------------------------------------
# §3.6  GET /api/site/weather/jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/api/site/weather/jobs/{job_id}")
def get_weather_job(job_id: str) -> JSONResponse:
    """Poll the status of a weather fetch job.

    404 if job_id is unknown (created-resource semantics — see contract §2).
    """
    job = _get_job(job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"job '{job_id}' not found", "code": "JOB_NOT_FOUND"},
        )

    payload: dict = {
        "job_id":       job.job_id,
        "status":       job.status,
        "progress_pct": job.progress_pct,
    }
    if job.status == "done" and job.result is not None:
        payload["result"] = job.result
    if job.status == "error" and job.error_message is not None:
        payload["error_message"] = job.error_message

    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# §3.7  GET /api/site/weather-coverage
# ---------------------------------------------------------------------------

@router.get("/api/site/weather-coverage")
def weather_coverage(
    lat: float = Query(..., description="Latitude in decimal degrees N/S"),
    lon: float = Query(..., description="Longitude in decimal degrees E/W"),
) -> JSONResponse:
    """Lightweight coverage check — no network call, no cache write.

    v1: Open-Meteo ERA5 has global coverage; historical_available=True for all valid
    lat/lon. year_range defaults to [2014, 2023] (default 10-year oracle window).
    """
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return JSONResponse(
            status_code=400,
            content={"detail": f"lat={lat}, lon={lon} outside valid range",
                     "code": "COVERAGE_PARAM_INVALID"},
        )

    # v1: global coverage for all valid coordinates
    start_year = 2014
    end_year = 2023
    year_count = end_year - start_year + 1  # = 10

    return JSONResponse(content={
        "lat":                   lat,
        "lon":                   lon,
        "historical_available":  True,
        "available_year_count":  year_count,
        "year_range":            [start_year, end_year],
        "bootstrap_available":   True,
        "source":                "open_meteo",
    })


# ---------------------------------------------------------------------------
# §3.8  GET /api/devices/models
# ---------------------------------------------------------------------------

def _model_entry(model_id: str, model_data: dict) -> dict:
    """Build a single-model response dict from the raw YAML entry."""
    return {
        "model_id":  model_id,
        "type":      model_data.get("type", ""),
        "physics":   dict(model_data.get("physics", {})),
        "economics": dict(model_data.get("economics", {})),
    }


@router.get("/api/devices/models")
def list_device_models() -> JSONResponse:
    """Return active device models from config/device_models.yaml.

    D38: only models whose type is in ACTIVE_DEVICE_TYPES are returned.
    INERT/gated catalog entries (electrolyzer, future gated families per D35)
    are excluded until their env-logic activates.
    """
    raw = _get_device_models()
    models = {
        mid: _model_entry(mid, mdata)
        for mid, mdata in raw.get("models", {}).items()
        if mdata.get("type") in ACTIVE_DEVICE_TYPES  # D38 filter
    }
    return JSONResponse(content={
        "schema_version": raw.get("schema_version", ""),
        "models": models,
    })


# ---------------------------------------------------------------------------
# §3.9  GET /api/devices/models/{model_id}
# ---------------------------------------------------------------------------

@router.get("/api/devices/models/{model_id}")
def get_device_model(model_id: str) -> JSONResponse:
    """Single active device model detail.

    D38: returns 400 DEVICE_MODEL_NOT_FOUND for INERT/gated types even when
    the model_id exists in device_models.yaml, treating them as absent from
    the feed (consistent with the list endpoint).
    """
    raw = _get_device_models()
    mdata = raw.get("models", {}).get(model_id)
    if mdata is None or mdata.get("type") not in ACTIVE_DEVICE_TYPES:  # D38 filter
        return JSONResponse(
            status_code=400,
            content={"detail": f"device model '{model_id}' not found",
                     "code": "DEVICE_MODEL_NOT_FOUND"},
        )
    return JSONResponse(content=_model_entry(model_id, mdata))


# ---------------------------------------------------------------------------
# §3.10  GET /api/devices/search
# ---------------------------------------------------------------------------

def _model_label(model_id: str, model_data: dict) -> str:
    """Build the autocomplete label string for a device model."""
    dtype = model_data.get("type", "")
    phy = model_data.get("physics", {})
    if dtype == "wind_turbine":
        mw = phy.get("rated_mw_per_unit", "?")
        hub = phy.get("hub_height_m", "?")
        return f"Wind turbine · {mw} MW · {hub}m hub"
    elif dtype == "pv_panel":
        eta = phy.get("eta_inverter", 0)
        deg = phy.get("degradation_yr1", 0)
        return f"PV panel · {deg * 100:.0f}% yr-1 · {eta * 100:.0f}% inverter"
    elif dtype == "battery":
        cap = phy.get("capacity_mwh_per_unit", "?")
        pwr = phy.get("power_mw_per_unit", "?")
        return f"Battery · {cap} MWh / {pwr} MW"
    elif dtype == "grid_connection":
        exp = phy.get("max_export_mw", "?")
        imp = phy.get("max_import_mw", "?")
        return f"Grid · {exp} MW export / {imp} MW import"
    return model_id


def _rated_output(dtype: str, phy: dict) -> dict | None:
    """Build the rated_output field for a device type."""
    if dtype == "wind_turbine":
        return {"value": float(phy.get("rated_mw_per_unit", 0)), "unit": "MW"}
    elif dtype == "battery":
        return {"value": float(phy.get("capacity_mwh_per_unit", 0)), "unit": "MWh"}
    elif dtype == "grid_connection":
        return {"value": float(phy.get("max_export_mw", 0)), "unit": "MW"}
    return None  # pv_panel: no simple single-unit rated output in v1


@router.get("/api/devices/search")
def search_device_models(
    q: str = Query(..., description="Prefix or substring search against model_id"),
    limit: int = Query(10, ge=1, le=50, description="Max results (default 10, max 50)"),
) -> JSONResponse:
    """Case-insensitive substring search against model_id.

    Ordering: exact-prefix matches first (case-insensitive), then substring matches,
    then alphabetically within each group.
    Empty q returns all models (up to limit).
    """
    raw = _get_device_models()
    q_lower = q.lower()
    all_models = raw.get("models", {})

    # Partition: prefix matches vs substring-only matches
    prefix: list[tuple[str, dict]] = []
    substring: list[tuple[str, dict]] = []

    for mid, mdata in all_models.items():
        if mdata.get("type") not in ACTIVE_DEVICE_TYPES:  # D38 filter
            continue
        if q_lower == "" or q_lower in mid.lower():
            if mid.lower().startswith(q_lower):
                prefix.append((mid, mdata))
            else:
                substring.append((mid, mdata))

    # Sort each group alphabetically then combine
    prefix.sort(key=lambda x: x[0])
    substring.sort(key=lambda x: x[0])
    combined = (prefix + substring)[:limit]

    results = []
    for mid, mdata in combined:
        dtype = mdata.get("type", "")
        phy = mdata.get("physics", {})
        result = {
            "model_id":    mid,
            "type":        dtype,
            "label":       _model_label(mid, mdata),
        }
        ro = _rated_output(dtype, phy)
        if ro is not None:
            result["rated_output"] = ro
        results.append(result)

    return JSONResponse(content={"results": results})
