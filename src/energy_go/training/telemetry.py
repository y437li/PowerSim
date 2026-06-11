"""Telemetry producers — §9 of training_pipeline contract.

build_train_metrics and build_eval_compare emit LOCKED-schema-compliant dicts
(contracts/shared/telemetry_schema.md v1.0.0, D18).

All emitted messages MUST pass energy_go.telemetry.validate(msg) with zero errors.
"""

from __future__ import annotations

import time
import itertools
from typing import Any

from energy_go.training.eval import PolicyEvalResult

# Per-run sequence counters (monotonically increasing per (run_id, kind))
_seq_counters: dict[str, itertools.count] = {}


def _next_seq(run_id: str, kind: str) -> int:
    key = f"{run_id}:{kind}"
    if key not in _seq_counters:
        _seq_counters[key] = itertools.count(0)
    return next(_seq_counters[key])


def _ts_utc() -> str:
    """ISO-8601 UTC timestamp string (seconds precision, Z suffix)."""
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _policy_dict(result: PolicyEvalResult) -> dict:
    """Serialise a PolicyEvalResult to the LOCKED schema policy sub-object."""
    return {
        "energy_cost_yuan":   result.energy_cost_yuan,
        "demand_charge_yuan": result.demand_charge_yuan,
        "degradation_yuan":   result.degradation_yuan,
        "curtailment_yuan":   result.curtailment_yuan,
        "voll_yuan":          result.voll_yuan,
        "total_cost_yuan":    result.total_cost_yuan,
        "soc_violations_count": result.soc_violations_count,
        "soc_violation_mwh":  result.soc_violation_mwh,
        "penalty_yuan":       result.penalty_yuan,
    }


def build_train_metrics(
    global_step: int,
    wall_seconds: float,
    env_steps_per_sec: float,
    actor_loss: float,
    critic_loss: float,
    ent_coef: float,
    reward_scaled_mean: float,
    reward_norm_mean: float | None,
    cost_total_real_mean_yuan: float,
    is_eval_checkpoint: bool,
    checkpoint_id: str | None,
    run_id: str,
) -> dict:
    """Build a telemetry envelope with kind='train_metrics' — §9.

    Returns a dict conforming to telemetry_schema.md envelope + train_metrics payload.
    Does NOT emit (caller decides transport). Validates against LOCKED schema before returning.

    Args:
        global_step:              Environment steps consumed.
        wall_seconds:             Wall-clock seconds elapsed since run start.
        env_steps_per_sec:        Throughput.
        actor_loss:               Current actor loss.
        critic_loss:              Current critic loss (mean of twin critics).
        ent_coef:                 Current entropy coefficient value.
        reward_scaled_mean:       Mean of ×1e-5 scaled env reward over the log window.
        reward_norm_mean:         VecNormalize-normalised reward mean; None at eval checkpoints.
        cost_total_real_mean_yuan: Mean per-episode real-money cost over the log window.
        is_eval_checkpoint:       True when emitting at an eval checkpoint.
        checkpoint_id:            UUID string when is_eval_checkpoint; None otherwise.
        run_id:                   Training run identifier.
    """
    msg = {
        "schema_version": "1.0.0",
        "kind":           "train_metrics",
        "ts_utc":         _ts_utc(),
        "run_id":         run_id,
        "seq":            _next_seq(run_id, "train_metrics"),
        "payload": {
            "global_step":               global_step,
            "wall_seconds":              wall_seconds,
            "env_steps_per_sec":         env_steps_per_sec,
            "actor_loss":                actor_loss,
            "critic_loss":               critic_loss,
            "ent_coef":                  ent_coef,
            "reward_scaled_mean":        reward_scaled_mean,
            "reward_norm_mean":          reward_norm_mean,
            "cost_total_real_mean_yuan": cost_total_real_mean_yuan,
            "is_eval_checkpoint":        is_eval_checkpoint,
            "checkpoint_id":             checkpoint_id,
        },
    }
    # Validate against LOCKED schema (§9.2 acceptance gate)
    from energy_go.telemetry.validate import validate
    errors = validate(msg)
    if errors:
        raise ValueError(
            f"build_train_metrics produced invalid telemetry: {errors}"
        )
    return msg


def build_eval_compare(
    eval_horizon_steps: int,
    checkpoint_id: str,
    rl: PolicyEvalResult,
    no_battery: PolicyEvalResult,
    rule_based_tou: PolicyEvalResult,
    run_id: str,
) -> dict:
    """Build a telemetry envelope with kind='eval_compare' — §9.

    cost_basis is 'real_money' per LOCKED schema.
    Additive identity for each policy is asserted before returning:
        total_cost_yuan == energy_cost + demand_charge + degradation + curtailment + voll

    Raises AssertionError if the identity fails (producer fault, not consumer fault).
    """
    _ADDITIVE_ATOL = 1.0  # ¥ tolerance for floating-point accumulation

    for name, result in [("rl", rl), ("no_battery", no_battery), ("rule_based_tou", rule_based_tou)]:
        expected = (
            result.energy_cost_yuan + result.demand_charge_yuan + result.degradation_yuan
            + result.curtailment_yuan + result.voll_yuan
        )
        assert abs(result.total_cost_yuan - expected) < _ADDITIVE_ATOL, (
            f"build_eval_compare: additive identity failed for policy '{name}': "
            f"total_cost_yuan={result.total_cost_yuan:.3f} != sum={expected:.3f} "
            f"(diff={abs(result.total_cost_yuan - expected):.3f} ¥)"
        )

    msg = {
        "schema_version": "1.0.0",
        "kind":           "eval_compare",
        "ts_utc":         _ts_utc(),
        "run_id":         run_id,
        "seq":            _next_seq(run_id, "eval_compare"),
        "payload": {
            "eval_horizon_steps": eval_horizon_steps,
            "checkpoint_id":      checkpoint_id,
            "cost_basis":         "real_money",
            "policies": {
                "rl":            _policy_dict(rl),
                "no_battery":    _policy_dict(no_battery),
                "rule_based_tou": _policy_dict(rule_based_tou),
            },
        },
    }
    # Validate against LOCKED schema (§9.2 acceptance gate)
    from energy_go.telemetry.validate import validate
    errors = validate(msg)
    if errors:
        raise ValueError(
            f"build_eval_compare produced invalid telemetry: {errors}"
        )
    return msg
