#!/usr/bin/env python3
"""Validate Energy GO telemetry messages against the LOCKED schema (v1.0.0).

Reference validator for `contracts/shared/telemetry_schema.json`. Checks, per the
`validate-telemetry` skill:
  1. JSON-Schema field conformance (names, types, enums, required, bounds).
  2. D13 cost identities (exact, within float tolerance) on env_step.
  3. Per-source energy conservation on env_step.
  4. Finiteness of every numeric field (no NaN/Inf).
  5. eval_compare: total_cost_yuan == sum of the five real-money components.

Check logic lives in `energy_go.telemetry.validate`; this script provides the
CLI entry point (file I/O + output formatting).

Usage:
  scripts/validate_telemetry.py --examples            # validate the canonical examples dir
  scripts/validate_telemetry.py path/to/message.json  # validate one message
Exit 0 = all valid; 1 = a validation failure; 2 = usage/dependency error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Check functions imported from the importable module (not duplicated here).
from energy_go.telemetry.validate import check_finite, check_env_step, check_eval_compare

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "contracts" / "shared" / "telemetry_schema.json"
EXAMPLES_DIR = ROOT / "contracts" / "shared" / "telemetry_examples"


def validate_message(msg, validator) -> list[str]:
    errs = [f"schema: {e.message} (at {'/'.join(str(x) for x in e.absolute_path)})"
            for e in sorted(validator.iter_errors(msg), key=lambda e: e.absolute_path)]
    errs += check_finite(msg)
    kind = msg.get("kind")
    if kind == "env_step":
        errs += check_env_step(msg.get("payload", {}))
    elif kind == "eval_compare":
        errs += check_eval_compare(msg.get("payload", {}))
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
