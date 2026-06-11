"""energy_go.serving.rest_api — REST endpoint implementations.

Contract: contracts/serving/rest_api.md
Reviewer-approved tests: tests/serving/test_serving_rest_api.py

Units: power = MW, energy = MWh, prices = ¥/MWh, costs = ¥.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _work_dir() -> Path:
    """Return the server's working directory (set at startup via os.chdir or launch)."""
    return Path.cwd()


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    """Always 200.  Monitoring probes depend on this never erroring."""
    from energy_go.serving.inference_stream import _policy_cache  # type: ignore

    loaded_id: str | None = None
    if _policy_cache:
        loaded_id = next(iter(_policy_cache))

    return {
        "status": "ok",
        "version": "1.0.0",
        "policy_loaded": bool(_policy_cache),
        "run_id": loaded_id,
    }


# ---------------------------------------------------------------------------
# GET /config/sites
# ---------------------------------------------------------------------------

@router.get("/config/sites")
def list_sites() -> dict:
    config = _work_dir() / "config"
    if not config.is_dir():
        return {"sites": []}

    sites = []
    for p in sorted(config.glob("site_*.yaml")):
        site_id = p.stem[len("site_"):]
        try:
            data = _load_yaml(p)
            name = data.get("site", {}).get("name", site_id)
        except Exception:
            name = site_id
        sites.append({"id": site_id, "name": name, "path": str(p.relative_to(_work_dir()))})

    return {"sites": sites}


# ---------------------------------------------------------------------------
# GET /config/sites/{site_id}
# ---------------------------------------------------------------------------

@router.get("/config/sites/{site_id}")
def get_site(site_id: str) -> dict:
    path = _work_dir() / "config" / f"site_{site_id}.yaml"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "site not found", "detail": f"no config/site_{site_id}.yaml"},
        )
    data = _load_yaml(path)
    return {
        **data,
        "units": {
            "battery.capacity_mwh": "MWh",
            "battery.max_charge_mw": "MW",
            "battery.max_discharge_mw": "MW",
            "grid_connection.max_export_mw": "MW",
            "grid_connection.max_import_mw": "MW",
        },
    }


# ---------------------------------------------------------------------------
# GET /config/assets/{category}
# ---------------------------------------------------------------------------

_ASSET_GLOBS: dict[str, tuple[str, dict]] = {
    "turbines": (
        "turbine_*.yaml",
        {"rated_power_mw": "MW", "hub_height_m": "m", "rotor_diameter_m": "m"},
    ),
    "pv": (
        "pv_*.yaml",
        {"rated_power_mwp": "MWp"},
    ),
    "batteries": (
        "battery_*.yaml",
        {"capacity_mwh": "MWh", "max_charge_mw": "MW", "max_discharge_mw": "MW"},
    ),
}


@router.get("/config/assets/{category}")
def list_assets(category: str) -> dict:
    if category not in _ASSET_GLOBS:
        raise HTTPException(status_code=404, detail={"error": f"unknown category: {category!r}"})

    glob_pattern, units = _ASSET_GLOBS[category]
    config = _work_dir() / "config"
    items = []
    if config.is_dir():
        for p in sorted(config.glob(glob_pattern)):
            prefix = glob_pattern.split("_")[0] + "_"
            item_id = p.stem[len(prefix):]
            try:
                raw = _load_yaml(p)
                # Flatten one level of nesting (e.g. {"turbine": {...}} → {...})
                if len(raw) == 1:
                    inner = next(iter(raw.values()))
                    if isinstance(inner, dict):
                        raw = inner
                item = {"id": item_id, **raw}
            except Exception:
                item = {"id": item_id}
            items.append(item)

    return {"category": category, "items": items, "units": units}


# ---------------------------------------------------------------------------
# Helpers for run metadata
# ---------------------------------------------------------------------------

def _list_runs_raw() -> list[dict]:
    checkpoints = _work_dir() / "checkpoints"
    if not checkpoints.is_dir():
        return []
    runs = []
    for d in sorted(checkpoints.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                pass
        # Task #38 fix: check canonical checkpoint_*.npz (training PR #40 format),
        # not the legacy policy.npz / policy.onnx which were never produced.
        has_policy = any("_step" in p.stem for p in d.glob("checkpoint_*.npz"))
        runs.append({
            "id": d.name,
            "created_at": meta.get("created_at"),
            "episodes_trained": meta.get("episodes_trained", 0),
            "latest_eval_reward": meta.get("latest_eval_reward"),
            "has_policy": has_policy,
            **{k: v for k, v in meta.items() if k not in
               ("created_at", "episodes_trained", "latest_eval_reward")},
        })
    return runs


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------

@router.get("/runs")
def list_runs() -> dict:
    return {"runs": _list_runs_raw()}


# ---------------------------------------------------------------------------
# GET /runs/latest
# ---------------------------------------------------------------------------

@router.get("/runs/latest")
def get_latest_run() -> dict:
    runs = _list_runs_raw()
    if not runs:
        raise HTTPException(status_code=404, detail={"error": "no runs found", "detail": None})
    # Sort by created_at descending; fall back to directory name order
    def _key(r: dict) -> str:
        return r.get("created_at") or ""
    latest = max(runs, key=_key)
    return _get_run_detail(latest["id"])


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

def _get_run_detail(run_id: str) -> dict:
    run_dir = _work_dir() / "checkpoints" / run_id
    if not run_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"error": "run not found", "detail": f"no checkpoints/{run_id}"},
        )
    meta_path = run_dir / "metadata.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            pass

    # Task #38 fix: canonical checkpoint_*.npz discovery (matches inference_stream._load_checkpoint_for_run)
    has_policy = any("_step" in p.stem for p in run_dir.glob("checkpoint_*.npz"))

    # Load normalization arrays if present
    normalization: dict | None = None
    norm_path = run_dir / "normalization.npz"
    if norm_path.exists():
        try:
            import numpy as np
            npz = np.load(norm_path)
            normalization = {
                "obs_mean": npz["obs_mean"].tolist(),
                "obs_std": npz["obs_std"].tolist(),
            }
        except Exception:
            pass

    return {
        "id": run_id,
        "has_policy": has_policy,
        "normalization": normalization,
        **meta,
        "units": {
            "normalization.obs_mean": "same units as obs vector (mixed; see telemetry schema)",
            "latest_eval_reward": (
                "dimensionless (reward = -(cost_total_reward_basis_yuan + penalty)*1e-5)"
            ),
        },
    }


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _get_run_detail(run_id)


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/eval
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/eval")
def get_eval(run_id: str) -> dict:
    run_dir = _work_dir() / "checkpoints" / run_id
    if not run_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"error": "run not found", "detail": f"no checkpoints/{run_id}"},
        )
    eval_path = run_dir / "eval_results.json"
    if not eval_path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "eval results not found", "detail": f"no checkpoints/{run_id}/eval_results.json"},
        )
    try:
        payload: dict = json.loads(eval_path.read_text())
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": "failed to parse eval_results.json"}) from exc

    # Pass through verbatim; append serving-added units key
    return {
        **payload,
        "units": {
            "*.total_cost_yuan": "¥",
            "*.energy_cost_yuan": "¥",
            "*.demand_charge_yuan": "¥",
            "*.degradation_yuan": "¥",
            "*.curtailment_yuan": "¥",
            "*.voll_yuan": "¥",
            "*.soc_violation_mwh": "MWh",
            "*.penalty_yuan": "¥",
            "eval_horizon_steps": "steps (1 step = 1 h per D3)",
        },
    }


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/train_curve
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/train_curve")
def get_train_curve(run_id: str) -> dict:
    run_dir = _work_dir() / "checkpoints" / run_id
    if not run_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"error": "run not found", "detail": f"no checkpoints/{run_id}"},
        )

    curve_path = run_dir / "train_curve.jsonl"
    empty: dict = {
        "steps": [], "episodes": [], "mean_reward": [], "eval_reward": [],
        "actor_loss": [], "critic_loss": [],
        "units": {
            "mean_reward": "dimensionless (reward = -(cost_total_reward_basis_yuan + penalty)*1e-5)",
            "eval_reward": "dimensionless (same scale as mean_reward)",
            "actor_loss": "dimensionless",
            "critic_loss": "dimensionless",
        },
    }

    if not curve_path.exists():
        return empty

    steps, episodes, mean_reward, eval_reward, actor_loss, critic_loss = [], [], [], [], [], []
    try:
        for line in curve_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            steps.append(rec.get("step"))
            episodes.append(rec.get("episode"))
            mean_reward.append(rec.get("mean_reward"))
            eval_reward.append(rec.get("eval_reward"))
            actor_loss.append(rec.get("actor_loss"))
            critic_loss.append(rec.get("critic_loss"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": "failed to parse train_curve.jsonl"}) from exc

    return {
        "steps": steps,
        "episodes": episodes,
        "mean_reward": mean_reward,
        "eval_reward": eval_reward,
        "actor_loss": actor_loss,
        "critic_loss": critic_loss,
        "units": empty["units"],
    }


# ---------------------------------------------------------------------------
# Global 404 override for clean error schema
# ---------------------------------------------------------------------------

def _error_response(status: int, error: str, detail: str | None = None):
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})
