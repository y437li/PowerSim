"""energy_go.telemetry.validate — importable telemetry validator.

Validates Energy GO telemetry messages against the LOCKED schema v1.0.0
(contracts/shared/telemetry_schema.md) plus the D13 cost identities, per-source
energy conservation, and finiteness checks.

Contract: contracts/shared/telemetry_validate.md
Schema:   bundled at energy_go/telemetry/data/telemetry_schema.json
          (copy of contracts/shared/telemetry_schema.json)

Deliberate deviations from scripts/validate_telemetry.py:
  F1: _approx uses 1e-6 relative coefficient (float32-safe; old script used 1e-9).
  F3: validate() rejects schema_version with major != 1.
  F4: check_env_step/check_eval_compare are defensive — skip checks on absent fields.
"""
from __future__ import annotations

import importlib.resources
import json
import math
from pathlib import Path

SCHEMA_VERSION: str = "1.0.0"
TOL: float = 1e-6  # absolute tolerance for numeric identities


# ---------------------------------------------------------------------------
# Schema loading (module-level; shared across all validate() calls)
# ---------------------------------------------------------------------------

def _load_schema() -> dict:
    """Load telemetry_schema.json from package data (importlib.resources) with repo fallback."""
    try:
        pkg = importlib.resources.files("energy_go.telemetry").joinpath("data/telemetry_schema.json")
        return json.loads(pkg.read_text(encoding="utf-8"))
    except Exception:
        # Fallback: repo-root path for tests run without an editable install
        fallback = Path(__file__).resolve().parents[3] / "contracts" / "shared" / "telemetry_schema.json"
        return json.loads(fallback.read_text(encoding="utf-8"))


try:
    from jsonschema import Draft202012Validator as _Validator
except ImportError as _e:
    raise ImportError(
        "jsonschema is required by energy_go.telemetry.validate. "
        "Install it with: pip install 'energy-go[dev]' or pip install jsonschema>=4.0"
    ) from _e

_SCHEMA = _load_schema()
_Draft202012Validator = _Validator
_VALIDATOR = _Draft202012Validator(_SCHEMA)


# ---------------------------------------------------------------------------
# Tolerance helper (F1: 1e-6 relative, float32-safe)
# ---------------------------------------------------------------------------

def _approx(a: float, b: float) -> bool:
    """True iff |a-b| <= TOL + 1e-6·max(|a|,|b|).

    1e-6 relative coefficient is float32-safe: at 3×10⁶ ¥ site-scale totals,
    float32 rounding error reaches ~0.36 ¥ — larger than the old 1e-9 threshold
    (0.003 ¥) but well inside this threshold (3 ¥). Unit-scale errors (kW/MW)
    are ~1000× the threshold and are still caught.
    """
    return abs(a - b) <= TOL + 1e-6 * max(abs(a), abs(b))


# ---------------------------------------------------------------------------
# Finiteness check
# ---------------------------------------------------------------------------

def _walk_numbers(obj, path: str = ""):
    """Yield (path, value) for every numeric (non-bool) leaf in obj."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_numbers(v, f"{path}[{i}]")


def check_finite(msg: dict) -> list[str]:
    """Return errors for every non-finite (NaN or Inf) float in msg.

    Walks the entire message tree recursively (dicts + lists).
    Booleans are not treated as numbers. Integer values are not checked for finiteness.
    Error format: "non-finite numeric at <dot-path>: <value>"
    """
    errs = []
    for path, val in _walk_numbers(msg):
        if isinstance(val, float) and not math.isfinite(val):
            errs.append(f"non-finite numeric at {path}: {val}")
    return errs


# ---------------------------------------------------------------------------
# env_step identity checks (D13 + conservation)
# ---------------------------------------------------------------------------

def check_env_step(payload: dict) -> list[str]:
    """Return errors for D13 cost identities, reward formula, and solar/wind conservation.

    Checks (tolerance: _approx with 1e-6 abs + 1e-6 rel):
      1. Real-money identity:
            cost_total_real_yuan == c_energy + c_demand_charge + c_degradation + c_curtail + c_voll
      2. Reward-basis identity:
            cost_total_reward_basis_yuan == c_energy + 2·c_demand_shape + c_degradation + c_curtail + c_voll
      3. c_energy decomposition:
            c_energy_yuan == c_import_yuan - r_export_yuan
      4. Reward formula (§3.5):
            reward == -(cost_total_reward_basis_yuan + penalty_yuan) * 1e-5
      5. Solar conservation:
            solar_to_load + solar_to_bat + solar_to_grid + solar_curtailed == gross_solar_mw
      6. Wind conservation:
            wind_to_load + wind_to_bat + wind_to_grid + wind_curtailed == gross_wind_mw

    Defensive: each check is silently skipped if its required fields are absent.
    Never raises; callers detect missing fields via schema errors.
    """
    errs: list[str] = []

    # Cost identity checks (D13)
    c = payload.get("costs")
    if isinstance(c, dict):
        _COST_KEYS_REAL = ("c_energy_yuan", "c_demand_charge_yuan", "c_degradation_yuan",
                           "c_curtail_yuan", "c_voll_yuan", "cost_total_real_yuan")
        _COST_KEYS_RB = ("c_energy_yuan", "c_demand_shape_yuan", "c_degradation_yuan",
                         "c_curtail_yuan", "c_voll_yuan", "cost_total_reward_basis_yuan")
        _COST_KEYS_ENERGY = ("c_energy_yuan", "c_import_yuan", "r_export_yuan")
        _REWARD_KEYS = ("cost_total_reward_basis_yuan", "penalty_yuan")

        if all(k in c for k in _COST_KEYS_REAL):
            real = (c["c_energy_yuan"] + c["c_demand_charge_yuan"]
                    + c["c_degradation_yuan"] + c["c_curtail_yuan"] + c["c_voll_yuan"])
            if not _approx(real, c["cost_total_real_yuan"]):
                errs.append(
                    f"D13 real identity: expected {real}, got cost_total_real_yuan={c['cost_total_real_yuan']}"
                )

        if all(k in c for k in _COST_KEYS_RB):
            rb = (c["c_energy_yuan"] + 2.0 * c["c_demand_shape_yuan"]
                  + c["c_degradation_yuan"] + c["c_curtail_yuan"] + c["c_voll_yuan"])
            if not _approx(rb, c["cost_total_reward_basis_yuan"]):
                errs.append(
                    f"D13 reward-basis identity: expected {rb}, "
                    f"got cost_total_reward_basis_yuan={c['cost_total_reward_basis_yuan']}"
                )

        if all(k in c for k in _COST_KEYS_ENERGY):
            if not _approx(c["c_energy_yuan"], c["c_import_yuan"] - c["r_export_yuan"]):
                errs.append("D13: c_energy_yuan != c_import_yuan - r_export_yuan")

        if all(k in c for k in _REWARD_KEYS) and "reward" in payload:
            rew = -(c["cost_total_reward_basis_yuan"] + c["penalty_yuan"]) * 1e-5
            if not _approx(rew, payload["reward"]):
                errs.append(
                    f"reward identity: expected {rew}, got reward={payload['reward']}"
                )

    # Per-source energy conservation
    f = payload.get("flows")
    g = payload.get("generation")
    if isinstance(f, dict) and isinstance(g, dict):
        _SOLAR_FLOW = ("solar_to_load_mw", "solar_to_bat_mw", "solar_to_grid_mw", "solar_curtailed_mw")
        _WIND_FLOW = ("wind_to_load_mw", "wind_to_bat_mw", "wind_to_grid_mw", "wind_curtailed_mw")

        if all(k in f for k in _SOLAR_FLOW) and "gross_solar_mw" in g:
            solar = sum(f[k] for k in _SOLAR_FLOW)
            if not _approx(solar, g["gross_solar_mw"]):
                errs.append(
                    f"solar conservation: parts sum {solar} != gross_solar_mw {g['gross_solar_mw']}"
                )

        if all(k in f for k in _WIND_FLOW) and "gross_wind_mw" in g:
            wind = sum(f[k] for k in _WIND_FLOW)
            if not _approx(wind, g["gross_wind_mw"]):
                errs.append(
                    f"wind conservation: parts sum {wind} != gross_wind_mw {g['gross_wind_mw']}"
                )

    return errs


# ---------------------------------------------------------------------------
# eval_compare identity check
# ---------------------------------------------------------------------------

def check_eval_compare(payload: dict) -> list[str]:
    """Return errors for eval_compare total_cost identities.

    For each policy entry in payload["policies"]:
        total_cost_yuan == energy_cost + demand_charge + degradation + curtailment + voll

    Defensive: skipped entirely if payload["policies"] is absent.  Per-policy checks
    are skipped when any of the six required fields is absent from that policy dict.
    """
    errs: list[str] = []
    policies = payload.get("policies")
    if not isinstance(policies, dict):
        return errs

    _POLICY_KEYS = ("energy_cost_yuan", "demand_charge_yuan", "degradation_yuan",
                    "curtailment_yuan", "voll_yuan", "total_cost_yuan")

    for name, pc in policies.items():
        if not isinstance(pc, dict):
            continue
        if not all(k in pc for k in _POLICY_KEYS):
            continue
        total = (pc["energy_cost_yuan"] + pc["demand_charge_yuan"] + pc["degradation_yuan"]
                 + pc["curtailment_yuan"] + pc["voll_yuan"])
        if not _approx(total, pc["total_cost_yuan"]):
            errs.append(
                f"{name}: components sum {total} != total_cost_yuan {pc['total_cost_yuan']}"
            )

    return errs


# ---------------------------------------------------------------------------
# Major-version guard (F3)
# ---------------------------------------------------------------------------

def _version_guard(msg: dict) -> list[str]:
    """Return a version-mismatch error if schema_version major != 1.

    Returns [] if schema_version is absent or not a valid semver string
    (schema validator will report those issues through the normal path).
    """
    sv = msg.get("schema_version")
    if not isinstance(sv, str):
        return []
    parts = sv.split(".")
    if len(parts) < 1:
        return []
    try:
        major = int(parts[0])
    except ValueError:
        return []
    if major != 1:
        return [f"version mismatch: expected major 1, got {major} (schema_version={sv!r})"]
    return []


# ---------------------------------------------------------------------------
# Top-level validate()
# ---------------------------------------------------------------------------

def validate(message: dict | str | bytes) -> list[str]:
    """Validate a telemetry message against the LOCKED schema v1.0.0.

    Args:
        message: A telemetry message as a dict, a JSON-encoded str, or UTF-8 bytes.

    Returns:
        An empty list if the message is fully valid.
        A non-empty list of human-readable error strings (one per violation) if invalid.
        Errors are ordered: version guard → schema → finiteness → kind-specific identities.

    Raises:
        TypeError  — if message is not dict | str | bytes.
        ValueError — if message is str/bytes that is not valid JSON.
    """
    if isinstance(message, (str, bytes)):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
    elif isinstance(message, dict):
        msg = message
    else:
        raise TypeError(
            f"validate() expects dict | str | bytes, got {type(message).__name__!r}"
        )

    errs: list[str] = []

    # 1. Major-version guard (F3) — before schema errors
    errs += _version_guard(msg)

    # 2. JSON-Schema conformance
    errs += [
        f"schema: {e.message} (at {'/'.join(str(x) for x in e.absolute_path)})"
        for e in sorted(_VALIDATOR.iter_errors(msg), key=lambda e: e.absolute_path)
    ]

    # 3. Finiteness
    errs += check_finite(msg)

    # 4. Kind-specific checks
    kind = msg.get("kind")
    payload = msg.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    if kind == "env_step":
        errs += check_env_step(payload)
    elif kind == "eval_compare":
        errs += check_eval_compare(payload)
    # train_metrics: no additional checks

    return errs
