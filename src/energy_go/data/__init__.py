"""energy_go.data — §12 real-weather data pipeline.

Contract: contracts/harness/weather_pipeline.md v1.0.0
Spec: §12 (weather pipeline), §4.1 (episode array format), §4.2 (load D19)
Design: docs/design/section12_historical_weather_design.md (team-lead APPROVED, PR #77)
Decisions: D3, D6, D11, D19, D31/F1; task-69 inputs

Public API:
    from energy_go.data.fetch     import fetch_weather_history, make_cache_path
    from energy_go.data.transform import compute_fitted_shear, extrapolate_to_hub
    from energy_go.data.bootstrap import build_block_pool, sample_bootstrap_year
    from energy_go.data.pipeline  import WeatherPipeline, get_episode_array

Open-Meteo attribution (CC BY 4.0):
    Weather data sourced via Open-Meteo (https://open-meteo.com), licensed under
    CC BY 4.0.  Underlying ERA5 reanalysis data is from Copernicus Climate Change
    Service (Copernicus Licence).  Local research caching is permitted.  Contact
    the project maintainers before redistributing cached or derived arrays.

Pure Python — never called inside jit.  Produces the (8760, 4) float32 device
array that the JAX env consumes; the jitted step is completely unaffected.
"""
