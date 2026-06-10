#!/usr/bin/env python3
"""Validate Energy GO telemetry messages against the LOCKED schema (v1.0.0).

Reference validator for `contracts/shared/telemetry_schema.json`. Checks, per the
`validate-telemetry` skill:
  1. JSON-Schema field conformance (names, types, enums, required, bounds).
  2. D13 cost identities (exact, within float tolerance) on env_step.
  3. Per-source energy conservation on env_step.
  4. Finiteness of every numeric field (no NaN/Inf).
  5. eval_compare: total_cost_yuan == sum of the five real-money components.

This is tooling, not the importable producer/consumer validator utilities
(`energy_go.telemetry.validate` / the TS module) — those are delegated tasks that
SHOULD reuse this schema + these golden examples.

Usage:
  scripts/validate_telemetry.py --examples            # validate the canonical examples dir
  scripts/validate_telemetry.py path/to/message.json  # validate one message
Exit 0 = all valid; 1 = a validation failure; 2 = usage/dependency error.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

TOL = 1e-6
ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "contracts" / "shared" / "telemetry_schema.json"
EXAMPLES_DIR = ROOT / "contracts" / "shared" / "telemetry_examples"


def _approx(a: float, b: float) -> bool:
    return abs(a - b) <= TOL + 1e-9 * max(abs(a), abs(b))


def _walk_numbers(obj, path=""):
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


def check_finite(msg) -> list[str]:
    errs = []
    for path, val in _walk_numbers(msg):
        if isinstance(val, float) and not math.isfinite(val):
            errs.append(f"non-finite numeric at {path}: {val}")
    return errs


def check_env_step(p) -> list[str]:
    errs = []
    c = p["costs"]
    real = c["c_energy_yuan"] + c["c_demand_charge_yuan"] + c["c_degradation_yuan"] + c["c_curtail_yuan"] + c["c_voll_yuan"]
    if not _approx(real, c["cost_total_real_yuan"]):
        errs.append(f"D13 real identity: expected {real}, got cost_total_real_yuan={c['cost_total_real_yuan']}")
    rb = c["c_energy_yuan"] + 2.0 * c["c_demand_shape_yuan"] + c["c_degradation_yuan"] + c["c_curtail_yuan"] + c["c_voll_yuan"]
    if not _approx(rb, c["cost_total_reward_basis_yuan"]):
        errs.append(f"D13 reward-basis identity: expected {rb}, got cost_total_reward_basis_yuan={c['cost_total_reward_basis_yuan']}")
    if not _approx(c["c_energy_yuan"], c["c_import_yuan"] - c["r_export_yuan"]):
        errs.append("D13: c_energy_yuan != c_import_yuan - r_export_yuan")
    rew = -(c["cost_total_reward_basis_yuan"] + c["penalty_yuan"]) * 1e-5
    if not _approx(rew, p["reward"]):
        errs.append(f"reward identity: expected {rew}, got reward={p['reward']}")

    f, g = p["flows"], p["generation"]
    solar = f["solar_to_load_mw"] + f["solar_to_bat_mw"] + f["solar_to_grid_mw"] + f["solar_curtailed_mw"]
    if not _approx(solar, g["gross_solar_mw"]):
        errs.append(f"solar conservation: parts sum {solar} != gross_solar_mw {g['gross_solar_mw']}")
    wind = f["wind_to_load_mw"] + f["wind_to_bat_mw"] + f["wind_to_grid_mw"] + f["wind_curtailed_mw"]
    if not _approx(wind, g["gross_wind_mw"]):
        errs.append(f"wind conservation: parts sum {wind} != gross_wind_mw {g['gross_wind_mw']}")
    return errs


def check_eval_compare(p) -> list[str]:
    errs = []
    for name, pc in p["policies"].items():
        total = pc["energy_cost_yuan"] + pc["demand_charge_yuan"] + pc["degradation_yuan"] + pc["curtailment_yuan"] + pc["voll_yuan"]
        if not _approx(total, pc["total_cost_yuan"]):
            errs.append(f"{name}: components sum {total} != total_cost_yuan {pc['total_cost_yuan']}")
    return errs


def validate_message(msg, validator) -> list[str]:
    errs = [f"schema: {e.message} (at {'/'.join(str(x) for x in e.absolute_path)})"
            for e in sorted(validator.iter_errors(msg), key=lambda e: e.absolute_path)]
    errs += check_finite(msg)
    kind = msg.get("kind")
    if kind == "env_step":
        errs += check_env_step(msg["payload"])
    elif kind == "eval_compare":
        errs += check_eval_compare(msg["payload"])
    return errs


def main(argv: list[str]) -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("ERROR: jsonschema not installed (pip install 'energy-go[dev]').", file=sys.stderr)
        return 2

    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    if not argv:
        print(__doc__.splitlines()[0])
        print("usage: validate_telemetry.py --examples | <message.json>", file=sys.stderr)
        return 2

    if argv[0] == "--examples":
        files = sorted(EXAMPLES_DIR.glob("*.json"))
        if not files:
            print(f"ERROR: no example files in {EXAMPLES_DIR}", file=sys.stderr)
            return 2
    else:
        files = [Path(argv[0])]

    failed = 0
    for fp in files:
        msg = json.loads(fp.read_text())
        errs = validate_message(msg, validator)
        if errs:
            failed += 1
            print(f"FAIL  {fp.name}")
            for e in errs:
                print(f"        - {e}")
        else:
            print(f"OK    {fp.name}  (kind={msg.get('kind')})")

    print()
    if failed:
        print(f"VALIDATION FAILED: {failed}/{len(files)} message(s) invalid.")
        return 1
    print(f"VALIDATION PASSED: {len(files)}/{len(files)} message(s) valid against telemetry_schema.json v1.0.0.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
