/**
 * telemetryValidator.ts
 *
 * Pure TypeScript validation module for incoming WebSocket telemetry messages.
 * Contract: contracts/frontend/telemetry_validator.md
 * Schema:   contracts/shared/telemetry_schema.md v1.0.0 (LOCKED, PR #6)
 *
 * 12-step validation pipeline (§4).  Consumers call validate() and only render
 * on ValidationResult.ok === true.
 */

import { z } from "zod";
import type {
  TelemetryEnvelope,
  PerStepCosts,
  GenerationBlock,
  PowerFlows,
} from "../types/telemetry";

// ─── §3.1: Result types ───────────────────────────────────────────────────────

export interface ValidationOk {
  ok: true;
  envelope: TelemetryEnvelope; // typed + passed-through as-is (no mutation)
  warnings: string[];          // non-empty only for forward-compat version warnings
}

export interface ValidationFail {
  ok: false;
  errors: string[];   // at least one entry; machine-checkable codes (see §5)
  warnings: string[];
}

export type ValidationResult = ValidationOk | ValidationFail;

// ─── Zod payload schemas ──────────────────────────────────────────────────────

const BatteryStateSchema = z
  .object({
    soc: z.number(),
    p_charge_mw: z.number(),
    p_discharge_mw: z.number(),
    p_max_charge_mw: z.number(),
    p_max_discharge_mw: z.number(),
    soc_violation_mwh: z.number(),
    capacity_mwh: z.number(),
  })
  .passthrough();

const GenerationBlockSchema = z
  .object({
    gross_solar_mw: z.number(),
    gross_wind_mw: z.number(),
  })
  .passthrough();

const PowerFlowsSchema = z
  .object({
    solar_to_load_mw: z.number(),
    solar_to_bat_mw: z.number(),
    solar_to_grid_mw: z.number(),
    wind_to_load_mw: z.number(),
    wind_to_bat_mw: z.number(),
    wind_to_grid_mw: z.number(),
    bat_to_load_mw: z.number(),
    bat_to_grid_mw: z.number(),
    grid_to_load_mw: z.number(),
    grid_to_bat_mw: z.number(),
    solar_curtailed_mw: z.number(),
    wind_curtailed_mw: z.number(),
    bat_curtailed_mw: z.number(),
    load_unserved_mw: z.number(),
  })
  .passthrough();

const PccStateSchema = z
  .object({
    export_mw: z.number(),
    import_mw: z.number(),
    max_export_mw: z.number(),
    max_import_mw: z.number(),
  })
  .passthrough();

const PerStepCostsSchema = z
  .object({
    c_energy_yuan: z.number(),
    c_import_yuan: z.number(),
    r_export_yuan: z.number(),
    c_demand_charge_yuan: z.number(),
    c_demand_shape_yuan: z.number(),
    c_degradation_yuan: z.number(),
    c_curtail_yuan: z.number(),
    c_voll_yuan: z.number(),
    penalty_yuan: z.number(),
    demand_rate_yuan_per_mw_month: z.number(),
    cost_total_real_yuan: z.number(),
    cost_total_reward_basis_yuan: z.number(),
  })
  .passthrough();

const CumulativeCostsSchema = z
  .object({
    c_energy_yuan_cum: z.number(),
    c_demand_charge_yuan_cum: z.number(),
    c_demand_shape_yuan_cum: z.number(),
    c_degradation_yuan_cum: z.number(),
    c_curtail_yuan_cum: z.number(),
    c_voll_yuan_cum: z.number(),
    penalty_yuan_cum: z.number(),
    cost_total_real_yuan_cum: z.number(),
    cost_total_reward_basis_yuan_cum: z.number(),
  })
  .passthrough();

const EnvStepPayloadSchema = z
  .object({
    step: z.number(),
    episode: z.number(),
    dt_hours: z.number(),
    sim_time_utc: z.string(),
    hour_of_day: z.number(),
    minute_of_hour: z.number(),
    wind_speed_mps: z.number(),
    irradiance_wm2: z.number(),
    temperature_c: z.number(),
    load_mw: z.number(),
    price_buy_yuan_per_mwh: z.number(),
    price_sell_yuan_per_mwh: z.number(),
    tariff_tier: z.string(),
    battery: BatteryStateSchema,
    generation: GenerationBlockSchema,
    flows: PowerFlowsSchema,
    pcc: PccStateSchema,
    costs: PerStepCostsSchema,
    cost_cum: CumulativeCostsSchema,
    month_peak_mw: z.number(),
    reward: z.number(),
  })
  .passthrough();

const TrainMetricsPayloadSchema = z
  .object({
    global_step: z.number(),
    // remaining fields are optional / nullable for forward-compat
    wall_seconds: z.number().optional(),
    env_steps_per_sec: z.number().optional(),
    actor_loss: z.number().nullable().optional(),
    critic_loss: z.number().nullable().optional(),
    ent_coef: z.number().nullable().optional(),
    reward_scaled_mean: z.number().nullable().optional(),
    reward_norm_mean: z.number().nullable().optional(),
    cost_total_real_mean_yuan: z.number().nullable().optional(),
    is_eval_checkpoint: z.boolean().optional(),
    checkpoint_id: z.string().nullable().optional(),
  })
  .passthrough();

const PolicyMetricsSchema = z
  .object({
    energy_cost_yuan: z.number(),
    demand_charge_yuan: z.number(),
    degradation_yuan: z.number(),
    curtailment_yuan: z.number(),
    voll_yuan: z.number(),
    total_cost_yuan: z.number(),
    soc_violations_count: z.number().optional(),
    soc_violation_mwh: z.number().optional(),
    penalty_yuan: z.number().optional(),
  })
  .passthrough();

const EvalComparePayloadSchema = z
  .object({
    eval_horizon_steps: z.number(),
    checkpoint_id: z.string(),
    cost_basis: z.string(),
    policies: z
      .object({
        rl: PolicyMetricsSchema,
      })
      .passthrough(),
  })
  .passthrough();

const PAYLOAD_SCHEMAS: Record<string, z.ZodTypeAny> = {
  env_step: EnvStepPayloadSchema,
  train_metrics: TrainMetricsPayloadSchema,
  eval_compare: EvalComparePayloadSchema,
};

// ─── §3.3: Exported helper — Finiteness ──────────────────────────────────────

/**
 * Returns dotted paths of all non-finite numeric fields (NaN, ±Infinity) found
 * by recursively traversing the value.  §8: arrays are traversed with [i] paths.
 */
export function checkFiniteness(value: unknown, path = ""): string[] {
  if (typeof value === "number") {
    return Number.isFinite(value) ? [] : [path];
  }
  if (value === null || typeof value !== "object") {
    return [];
  }
  const results: string[] = [];
  if (Array.isArray(value)) {
    value.forEach((item, i) => {
      const childPath = path ? `${path}[${i}]` : `[${i}]`;
      results.push(...checkFiniteness(item, childPath));
    });
  } else {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      const childPath = path ? `${path}.${key}` : key;
      results.push(...checkFiniteness(child, childPath));
    }
  }
  return results;
}

// ─── §3.3: Exported helper — D13 cost identities ─────────────────────────────

/**
 * Checks the three monetary D13 cost identities for an env_step payload's costs.
 * Returns error strings; empty array on pass.
 * Tolerance: |computed − stored| ≤ 1.0 ¥.
 */
export function checkD13Identities(costs: PerStepCosts): string[] {
  const errors: string[] = [];
  const TOL = 1.0;

  // 1. cost_total_real
  const real =
    costs.c_energy_yuan +
    costs.c_demand_charge_yuan +
    costs.c_degradation_yuan +
    costs.c_curtail_yuan +
    costs.c_voll_yuan;
  const realDelta = real - costs.cost_total_real_yuan;
  if (Math.abs(realDelta) > TOL) {
    errors.push(`d13_real:${realDelta}`);
  }

  // 2. cost_total_reward_basis
  const rewardBasis =
    costs.c_energy_yuan +
    2.0 * costs.c_demand_shape_yuan +
    costs.c_degradation_yuan +
    costs.c_curtail_yuan +
    costs.c_voll_yuan;
  const rewardDelta = rewardBasis - costs.cost_total_reward_basis_yuan;
  if (Math.abs(rewardDelta) > TOL) {
    errors.push(`d13_reward:${rewardDelta}`);
  }

  // 3. c_energy = c_import − r_export
  const energyComputed = costs.c_import_yuan - costs.r_export_yuan;
  const energyDelta = energyComputed - costs.c_energy_yuan;
  if (Math.abs(energyDelta) > TOL) {
    errors.push(`d13_energy:${energyDelta}`);
  }

  return errors;
}

// ─── §3.3: Exported helper — Per-source conservation ─────────────────────────

/**
 * Checks per-source (solar, wind) conservation for an env_step payload.
 * Returns error strings; empty array on pass.
 * Tolerance: |computed − gross| ≤ 0.001 MW.
 */
export function checkConservation(
  generation: GenerationBlock,
  flows: PowerFlows
): string[] {
  const errors: string[] = [];
  const TOL = 0.001;

  // Solar
  const solarOut =
    flows.solar_to_load_mw +
    flows.solar_to_bat_mw +
    flows.solar_to_grid_mw +
    flows.solar_curtailed_mw;
  const solarDelta = solarOut - generation.gross_solar_mw;
  if (Math.abs(solarDelta) > TOL) {
    errors.push(`conservation_solar:${solarDelta}`);
  }

  // Wind
  const windOut =
    flows.wind_to_load_mw +
    flows.wind_to_bat_mw +
    flows.wind_to_grid_mw +
    flows.wind_curtailed_mw;
  const windDelta = windOut - generation.gross_wind_mw;
  if (Math.abs(windDelta) > TOL) {
    errors.push(`conservation_wind:${windDelta}`);
  }

  return errors;
}

// ─── §3.2: Primary entry point ────────────────────────────────────────────────

const SEMVER_RE = /^[0-9]+\.[0-9]+\.[0-9]+$/;
const KNOWN_KINDS = new Set(["env_step", "train_metrics", "eval_compare"]);

/** Validates an incoming WebSocket telemetry message against the LOCKED schema. */
export function validate(msg: unknown): ValidationResult {
  const warnings: string[] = [];

  // §4.1: non-null, non-array object
  if (
    msg === null ||
    msg === undefined ||
    typeof msg !== "object" ||
    Array.isArray(msg)
  ) {
    return { ok: false, errors: ["not_object"], warnings };
  }

  const obj = msg as Record<string, unknown>;

  // §4.2: schema_version present and semver
  const sv = obj["schema_version"];
  if (typeof sv !== "string" || !SEMVER_RE.test(sv)) {
    return { ok: false, errors: ["bad_schema_version"], warnings };
  }

  // Parse major/minor/patch
  const [majorStr, minorStr] = sv.split(".");
  const major = parseInt(majorStr, 10);
  const minor = parseInt(minorStr, 10);

  // §4.3: major > 1 → reject
  if (major > 1) {
    return { ok: false, errors: [`version_rejected:${sv}`], warnings };
  }

  // §4.4: minor > 0 → forward-compat warning; patch-only (minor=0) → no warning
  if (major === 1 && minor > 0) {
    warnings.push(`version_forward_compat:${sv}`);
  }

  // §4.5: required envelope fields
  const REQUIRED = ["kind", "ts_utc", "run_id", "seq", "payload"] as const;
  const missingErrors: string[] = [];
  for (const field of REQUIRED) {
    if (!(field in obj) || obj[field] === undefined) {
      missingErrors.push(`missing_field:${field}`);
    }
  }
  if (missingErrors.length > 0) {
    return { ok: false, errors: missingErrors, warnings };
  }

  // §4.6: known kind
  const kind = obj["kind"] as string;
  if (!KNOWN_KINDS.has(kind)) {
    return { ok: false, errors: [`unknown_kind:${kind}`], warnings };
  }

  // §4.7: payload is non-null object
  const payload = obj["payload"];
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, errors: ["bad_payload"], warnings };
  }

  // §4.8: seq is a non-negative integer
  const seq = obj["seq"];
  if (typeof seq !== "number" || !Number.isInteger(seq) || seq < 0) {
    return { ok: false, errors: ["bad_seq"], warnings };
  }

  // §4.9: Finiteness — check BEFORE Zod so NaN/Infinity gives non_finite: codes,
  //        not payload_invalid: codes (Zod z.number() rejects NaN/Infinity).
  const finitePaths = checkFiniteness(payload);
  if (finitePaths.length > 0) {
    return {
      ok: false,
      errors: finitePaths.map((p) => `non_finite:${p}`),
      warnings,
    };
  }

  // §4.10: Payload Zod conformance (runs after finiteness — all numbers are finite here)
  const schema = PAYLOAD_SCHEMAS[kind];
  const zodResult = schema.safeParse(payload);
  if (!zodResult.success) {
    const zodErrors = zodResult.error.issues.map((issue) => {
      const path = issue.path.join(".");
      return `payload_invalid:${path || "root"}`;
    });
    return { ok: false, errors: zodErrors, warnings };
  }

  // §4.11 + reward formula (env_step only)
  if (kind === "env_step") {
    const p = payload as Record<string, unknown>;
    const costs = p["costs"] as PerStepCosts;

    // D13 monetary identities
    const d13Errors = checkD13Identities(costs);
    if (d13Errors.length > 0) {
      return { ok: false, errors: d13Errors, warnings };
    }

    // D13 reward formula: reward = −(cost_total_reward_basis + penalty) × 1e-5
    const reward = p["reward"] as number;
    const rewardComputed =
      -(costs.cost_total_reward_basis_yuan + costs.penalty_yuan) * 1e-5;
    const rewardFormulaDelta = rewardComputed - reward;
    if (Math.abs(rewardFormulaDelta) > 1e-6) {
      return {
        ok: false,
        errors: [`d13_reward_formula:${rewardFormulaDelta}`],
        warnings,
      };
    }

    // §4.12: Per-source conservation
    const conservErrors = checkConservation(
      p["generation"] as GenerationBlock,
      p["flows"] as PowerFlows
    );
    if (conservErrors.length > 0) {
      return { ok: false, errors: conservErrors, warnings };
    }
  }

  // §4.13: eval_compare per-policy cost identity
  if (kind === "eval_compare") {
    const p = payload as Record<string, unknown>;
    const policies = p["policies"] as Record<string, unknown>;
    const TOL = 1.0;
    const evalErrors: string[] = [];

    for (const [policyKey, policyData] of Object.entries(policies)) {
      if (
        policyData === null ||
        typeof policyData !== "object" ||
        Array.isArray(policyData)
      ) {
        continue;
      }
      const pm = policyData as Record<string, unknown>;
      // Only check if all five addend fields are present (forward-compat: skip partial entries)
      if (
        typeof pm["energy_cost_yuan"] === "number" &&
        typeof pm["demand_charge_yuan"] === "number" &&
        typeof pm["degradation_yuan"] === "number" &&
        typeof pm["curtailment_yuan"] === "number" &&
        typeof pm["voll_yuan"] === "number" &&
        typeof pm["total_cost_yuan"] === "number"
      ) {
        const computed =
          (pm["energy_cost_yuan"] as number) +
          (pm["demand_charge_yuan"] as number) +
          (pm["degradation_yuan"] as number) +
          (pm["curtailment_yuan"] as number) +
          (pm["voll_yuan"] as number);
        const delta = computed - (pm["total_cost_yuan"] as number);
        if (Math.abs(delta) > TOL) {
          evalErrors.push(`eval_total:${policyKey}:${delta}`);
        }
      }
    }

    if (evalErrors.length > 0) {
      return { ok: false, errors: evalErrors, warnings };
    }
  }

  // All checks passed — return the typed envelope
  return {
    ok: true,
    envelope: msg as TelemetryEnvelope,
    warnings,
  };
}
