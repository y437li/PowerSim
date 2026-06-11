/**
 * Test suite: telemetry_validator
 *
 * Framework: Vitest
 * Contract:  contracts/frontend/telemetry_validator.md
 * Schema:    contracts/shared/telemetry_schema.md v1.0.0 (LOCKED, PR #6)
 *
 * Golden fixture imports — authoritative passing cases from contracts/shared/telemetry_examples/.
 * If validate() returns ok:false for any golden, the implementation is wrong.
 *
 * Tests are intentionally RED until implementation exists.
 * Never modify reviewer-added tests (marked // reviewer:).
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Golden fixture imports (raw objects; types validated at runtime by the validator)
import ENV_STEP_A from "../../contracts/shared/telemetry_examples/env_step_a.json";
import ENV_STEP_B from "../../contracts/shared/telemetry_examples/env_step_b.json";
import TRAIN_METRICS from "../../contracts/shared/telemetry_examples/train_metrics.json";
import EVAL_COMPARE from "../../contracts/shared/telemetry_examples/eval_compare.json";

// ─── §1: Golden fixtures pass ─────────────────────────────────────────────────

describe("validate — golden fixtures pass", () => {
  it("env_step_a (golden A: net-export, no demand activity) → ok:true", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const result = validate(ENV_STEP_A);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.warnings).toHaveLength(0);
  });

  it("env_step_b (golden B: month-boundary demand charge) → ok:true", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const result = validate(ENV_STEP_B);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.warnings).toHaveLength(0);
  });

  it("train_metrics golden fixture → ok:true", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const result = validate(TRAIN_METRICS);
    expect(result.ok).toBe(true);
  });

  it("eval_compare golden fixture → ok:true", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const result = validate(EVAL_COMPARE);
    expect(result.ok).toBe(true);
  });
});

// ─── §4.1–4.4: non-object and version checks ─────────────────────────────────

describe("validate — §4.1 non-object inputs rejected", () => {
  it("null → ok:false, error 'not_object'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate(null);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "not_object")).toBe(true);
  });

  it("undefined → ok:false, error 'not_object'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate(undefined);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "not_object")).toBe(true);
  });

  it("a string → ok:false, error 'not_object'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate("not an object");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "not_object")).toBe(true);
  });

  it("an array → ok:false, error 'not_object'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate([ENV_STEP_A]);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "not_object")).toBe(true);
  });
});

describe("validate — §4.2/4.3 schema_version checks", () => {
  it("missing schema_version → ok:false, error 'bad_schema_version'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { schema_version: _sv, ...noVersion } = ENV_STEP_A as any;
    const r = validate(noVersion);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "bad_schema_version")).toBe(true);
  });

  it("non-semver schema_version → ok:false, error 'bad_schema_version'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, schema_version: "v1" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "bad_schema_version")).toBe(true);
  });

  it("schema_version '2.0.0' (major>1) → ok:false, error 'version_rejected:2.0.0'", async () => {
    // §9: Contract guarantees this specific code and the message is NOT dispatched.
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, schema_version: "2.0.0" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "version_rejected:2.0.0")).toBe(true);
  });

  it("schema_version '3.1.0' (major>1) → ok:false, error 'version_rejected:3.1.0'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, schema_version: "3.1.0" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "version_rejected:3.1.0")).toBe(true);
  });
});

describe("validate — §4.4 minor forward compat (1.x)", () => {
  it("schema_version '1.5.0' → ok:true, warning 'version_forward_compat:1.5.0'", async () => {
    // §9: Forward-compat: unknown fields silently ignored, pipeline continues.
    const { validate } = await import("../../src/validators/telemetryValidator");
    const fwd = { ...ENV_STEP_A, schema_version: "1.5.0",
      payload: { ...ENV_STEP_A.payload, some_future_field: 99 } };
    const r = validate(fwd);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.warnings.some(w => w === "version_forward_compat:1.5.0")).toBe(true);
  });

  it("schema_version '1.0.0' → ok:true, no version warnings", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate(ENV_STEP_A);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.warnings.filter(w => w.startsWith("version_"))).toHaveLength(0);
  });

  it("schema_version '1.0.5' (patch only, minor=0) → ok:true, no version warnings", async () => {
    // §4.4 nit: patch-only bump emits NO forward-compat warning — only minor > 0 warns.
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, schema_version: "1.0.5" });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.warnings.filter(w => w.startsWith("version_"))).toHaveLength(0);
  });
});

// ─── §4.5–4.8: Required envelope fields ──────────────────────────────────────

describe("validate — §4.5 missing envelope fields", () => {
  it("missing 'kind' → ok:false, error 'missing_field:kind'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { kind: _k, ...noKind } = ENV_STEP_A as any;
    const r = validate(noKind);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "missing_field:kind")).toBe(true);
  });

  it("missing 'payload' → ok:false, error 'missing_field:payload'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { payload: _p, ...noPayload } = ENV_STEP_A as any;
    const r = validate(noPayload);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "missing_field:payload")).toBe(true);
  });

  it("missing 'run_id' → ok:false, error 'missing_field:run_id'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { run_id: _r, ...noRunId } = ENV_STEP_A as any;
    const r = validate(noRunId);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "missing_field:run_id")).toBe(true);
  });

  it("missing 'seq' → ok:false, error 'missing_field:seq'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { seq: _s, ...noSeq } = ENV_STEP_A as any;
    const r = validate(noSeq);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "missing_field:seq")).toBe(true);
  });
});

describe("validate — §4.6/4.7 bad kind and payload", () => {
  it("unknown kind 'debug_info' → ok:false, error 'unknown_kind:debug_info'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, kind: "debug_info" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "unknown_kind:debug_info")).toBe(true);
  });

  it("payload is null → ok:false, error 'bad_payload'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, payload: null });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "bad_payload")).toBe(true);
  });

  it("payload is a string → ok:false, error 'bad_payload'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, payload: "nope" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "bad_payload")).toBe(true);
  });

  it("seq is -1 (negative) → ok:false, error 'bad_seq'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, seq: -1 });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "bad_seq")).toBe(true);
  });
});

// ─── §4.10: Finiteness checks ─────────────────────────────────────────────────

describe("validate — §4.10 finiteness (§9 unhappy paths)", () => {
  it("reward: NaN → ok:false, error 'non_finite:reward'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: { ...ENV_STEP_A.payload, reward: NaN },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "non_finite:reward")).toBe(true);
  });

  it("battery.soc: Infinity → ok:false, error 'non_finite:battery.soc'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: {
        ...ENV_STEP_A.payload,
        battery: { ...ENV_STEP_A.payload.battery, soc: Infinity },
      },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "non_finite:battery.soc")).toBe(true);
  });

  it("costs.c_energy_yuan: -Infinity → ok:false, error 'non_finite:costs.c_energy_yuan'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: {
        ...ENV_STEP_A.payload,
        costs: { ...ENV_STEP_A.payload.costs, c_energy_yuan: -Infinity },
      },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e === "non_finite:costs.c_energy_yuan")).toBe(true);
  });
});

// ─── §4.11: D13 identity checks ──────────────────────────────────────────────

describe("validate — §4.11 D13 cost identities (env_step)", () => {
  it("cost_total_real_yuan off by 2000 → error 'non_finite:…' or 'd13_real:…'", async () => {
    // Contract §6: |computed − stored| ≤ 1.0 ¥; off by 2000 must fail.
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: {
        ...ENV_STEP_A.payload,
        costs: { ...ENV_STEP_A.payload.costs, cost_total_real_yuan: ENV_STEP_A.payload.costs.cost_total_real_yuan + 2000 },
      },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("d13_real:"))).toBe(true);
  });

  it("cost_total_reward_basis_yuan off by −5000 → error starts with 'd13_reward:'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: {
        ...ENV_STEP_A.payload,
        costs: { ...ENV_STEP_A.payload.costs, cost_total_reward_basis_yuan: ENV_STEP_A.payload.costs.cost_total_reward_basis_yuan - 5000 },
      },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("d13_reward:"))).toBe(true);
  });

  it("c_energy_yuan ≠ c_import − r_export → error starts with 'd13_energy:'", async () => {
    // Force mismatch: set c_energy_yuan to the correct value + 500
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: {
        ...ENV_STEP_A.payload,
        costs: { ...ENV_STEP_A.payload.costs, c_energy_yuan: ENV_STEP_A.payload.costs.c_energy_yuan + 500 },
      },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("d13_energy:"))).toBe(true);
  });

  it("reward formula violated (reward off by 0.01) → error starts with 'd13_reward_formula:'", async () => {
    // |computed − stored| ≤ 1e-6; off by 0.01 must fail.
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: { ...ENV_STEP_A.payload, reward: ENV_STEP_A.payload.reward + 0.01 },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("d13_reward_formula:"))).toBe(true);
  });
});

// ─── §4.12: Per-source conservation ──────────────────────────────────────────

describe("validate — §4.12 per-source conservation (env_step)", () => {
  it("solar output exceeds gross_solar_mw by 5 MW → error starts with 'conservation_solar:'", async () => {
    // gross_solar_mw = 30.0; set solar_to_load = 35 while keeping gross = 30 → 5 MW excess
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: {
        ...ENV_STEP_A.payload,
        flows: { ...ENV_STEP_A.payload.flows, solar_to_load_mw: 35.0 },
      },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("conservation_solar:"))).toBe(true);
  });

  it("wind output exceeds gross_wind_mw by 10 MW → error starts with 'conservation_wind:'", async () => {
    // gross_wind_mw = 92.5; set wind_to_grid = 90 (was 80) → sum = 12.5+0+90+0 = 102.5, off by 10
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({
      ...ENV_STEP_A,
      payload: {
        ...ENV_STEP_A.payload,
        flows: { ...ENV_STEP_A.payload.flows, wind_to_grid_mw: 90.0 },
      },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("conservation_wind:"))).toBe(true);
  });
});

// ─── §3.3: Exported helper functions ─────────────────────────────────────────

describe("checkD13Identities — exported helper", () => {
  it("golden-A costs → empty array (all identities pass)", async () => {
    const { checkD13Identities } = await import("../../src/validators/telemetryValidator");
    const errors = checkD13Identities(ENV_STEP_A.payload.costs as any);
    expect(errors).toHaveLength(0);
  });

  it("golden-B costs → empty array (month-boundary demand charge identities pass)", async () => {
    const { checkD13Identities } = await import("../../src/validators/telemetryValidator");
    const errors = checkD13Identities(ENV_STEP_B.payload.costs as any);
    expect(errors).toHaveLength(0);
  });

  it("mutated cost_total_real_yuan returns errors starting with 'd13_real:'", async () => {
    const { checkD13Identities } = await import("../../src/validators/telemetryValidator");
    const badCosts = { ...ENV_STEP_A.payload.costs, cost_total_real_yuan: 0 };
    const errors = checkD13Identities(badCosts as any);
    expect(errors.some(e => e.startsWith("d13_real:"))).toBe(true);
  });

  it("mutated cost_total_reward_basis_yuan returns errors starting with 'd13_reward:'", async () => {
    const { checkD13Identities } = await import("../../src/validators/telemetryValidator");
    const badCosts = { ...ENV_STEP_A.payload.costs, cost_total_reward_basis_yuan: 999999 };
    const errors = checkD13Identities(badCosts as any);
    expect(errors.some(e => e.startsWith("d13_reward:"))).toBe(true);
  });
});

describe("checkFiniteness — exported helper", () => {
  it("clean payload → empty array", async () => {
    const { checkFiniteness } = await import("../../src/validators/telemetryValidator");
    const errors = checkFiniteness(ENV_STEP_A.payload);
    expect(errors).toHaveLength(0);
  });

  it("payload with NaN soc → returns 'battery.soc'", async () => {
    const { checkFiniteness } = await import("../../src/validators/telemetryValidator");
    const bad = { ...ENV_STEP_A.payload, battery: { ...ENV_STEP_A.payload.battery, soc: NaN } };
    const errors = checkFiniteness(bad);
    expect(errors.some(e => e === "battery.soc")).toBe(true);
  });

  it("payload with Infinity load_mw → returns 'load_mw'", async () => {
    const { checkFiniteness } = await import("../../src/validators/telemetryValidator");
    const bad = { ...ENV_STEP_A.payload, load_mw: Infinity };
    const errors = checkFiniteness(bad);
    expect(errors.some(e => e === "load_mw")).toBe(true);
  });

  it("§8 — NaN inside array element is reported with indexed path", async () => {
    // §8: arrays are traversed; numeric fields inside array elements are checked.
    const { checkFiniteness } = await import("../../src/validators/telemetryValidator");
    const payloadWithArray = { assets_ext: [{ capacity_mwh: NaN }, { capacity_mwh: 10 }] };
    const errors = checkFiniteness(payloadWithArray);
    expect(errors.some(e => e === "assets_ext[0].capacity_mwh")).toBe(true);
    expect(errors.some(e => e === "assets_ext[1].capacity_mwh")).toBe(false);
  });
});

describe("checkConservation — exported helper", () => {
  it("golden-A generation + flows → empty array", async () => {
    const { checkConservation } = await import("../../src/validators/telemetryValidator");
    const errors = checkConservation(ENV_STEP_A.payload.generation as any, ENV_STEP_A.payload.flows as any);
    expect(errors).toHaveLength(0);
  });

  it("golden-B generation + flows → empty array (night-time: solar=0)", async () => {
    const { checkConservation } = await import("../../src/validators/telemetryValidator");
    const errors = checkConservation(ENV_STEP_B.payload.generation as any, ENV_STEP_B.payload.flows as any);
    expect(errors).toHaveLength(0);
  });

  it("solar_to_load_mw modified to cause imbalance → returns error starting with 'conservation_solar:'", async () => {
    const { checkConservation } = await import("../../src/validators/telemetryValidator");
    const badFlows = { ...ENV_STEP_A.payload.flows, solar_to_load_mw: 50.0 }; // was 30; gross is 30 → +20 excess
    const errors = checkConservation(ENV_STEP_A.payload.generation as any, badFlows as any);
    expect(errors.some(e => e.startsWith("conservation_solar:"))).toBe(true);
  });
});

// ─── §3.1: Result shape ───────────────────────────────────────────────────────

describe("validate — ValidationResult shape", () => {
  it("ok result has envelope property typed as TelemetryEnvelope", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate(ENV_STEP_A);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.envelope).toBeDefined();
      expect(r.envelope.kind).toBe("env_step");
      expect(r.envelope.run_id).toBe("golden-a");
      expect(r.warnings).toBeDefined();
    }
  });

  it("fail result has errors array with at least one entry", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...ENV_STEP_A, schema_version: "2.0.0" });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(Array.isArray(r.errors)).toBe(true);
      expect(r.errors.length).toBeGreaterThan(0);
      expect(Array.isArray(r.warnings)).toBe(true);
    }
  });

  it("envelope on ok result is passed through unchanged (no mutation)", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate(ENV_STEP_A);
    expect(r.ok).toBe(true);
    if (r.ok) {
      // The envelope object returned must contain the original seq value
      expect(r.envelope.seq).toBe(ENV_STEP_A.seq);
      expect((r.envelope.payload as any).reward).toBe(ENV_STEP_A.payload.reward);
    }
  });
});

// ─── §4.9: Payload Zod conformance ───────────────────────────────────────────

describe("validate — §4.9 payload Zod conformance", () => {
  it("env_step missing payload.step → ok:false, error starts with 'payload_invalid:'", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { step: _s, ...noStep } = ENV_STEP_A.payload as any;
    const r = validate({ ...ENV_STEP_A, payload: noStep });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("payload_invalid:"))).toBe(true);
  });

  it("train_metrics missing payload.global_step → ok:false", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { global_step: _g, ...noGS } = TRAIN_METRICS.payload as any;
    const r = validate({ ...TRAIN_METRICS, payload: noGS });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("payload_invalid:"))).toBe(true);
  });

  it("eval_compare missing policies.rl → ok:false", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const { rl: _rl, ...noPolicies } = EVAL_COMPARE.payload.policies as any;
    const r = validate({ ...EVAL_COMPARE, payload: { ...EVAL_COMPARE.payload, policies: noPolicies } });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("payload_invalid:"))).toBe(true);
  });

  it("train_metrics reward_norm_mean: null → ok:true (null is valid per schema)", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate({ ...TRAIN_METRICS, payload: { ...TRAIN_METRICS.payload, reward_norm_mean: null } });
    expect(r.ok).toBe(true);
  });
});

// ─── §10: Integration — ok result passes through seq and run_id ───────────────

describe("validate — §10 integration envelope pass-through", () => {
  it("validated train_metrics envelope preserves run_id and seq", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate(TRAIN_METRICS);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.envelope.run_id).toBe("golden-train");
      expect(r.envelope.seq).toBe(250);
    }
  });

  it("validated eval_compare envelope preserves checkpoint_id in payload", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const r = validate(EVAL_COMPARE);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect((r.envelope.payload as any).checkpoint_id).toBe("ckpt-000250000");
    }
  });
});

// ─── REVIEWER-ADDED (frontend-reviewer): eval_compare cost identity ───────────
describe("reviewer: validate — eval_compare per-policy additive identity (D13)", () => {
  // reviewer: MUST-FIX — the pipeline runs D13 only on env_step (§4.11). eval_compare
  // is the headline RL-vs-baseline comparison; a policy whose total_cost_yuan !=
  // energy+demand_charge+degradation+curtailment+voll would pass validation and
  // mislabel the "best" policy. The validator must enforce this per policy
  // (proposed pipeline step + error code `eval_total:<policy>:<delta>`).
  it("a policy whose total_cost_yuan is off by 1000 → ok:false with an eval-total error", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    const broken = {
      ...EVAL_COMPARE,
      payload: {
        ...EVAL_COMPARE.payload,
        policies: {
          ...EVAL_COMPARE.payload.policies,
          rl: {
            ...(EVAL_COMPARE.payload.policies as any).rl,
            total_cost_yuan: (EVAL_COMPARE.payload.policies as any).rl.total_cost_yuan + 1000,
          },
        },
      },
    };
    const r = validate(broken);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.errors.some(e => e.startsWith("eval_total"))).toBe(true);
  });

  it("the unmodified golden eval_compare still passes (no false positive)", async () => {
    const { validate } = await import("../../src/validators/telemetryValidator");
    expect(validate(EVAL_COMPARE).ok).toBe(true);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// TV.ROB — Robustness amendment tests (task #29, post-D26)
// Contract: contracts/frontend/telemetry_validator.md §10–§15
//
// These tests are intentionally RED until:
//   - telemetryStore.receiveEnvStep calls validate() and skips on ok:false (§10.1/§10.3)
//   - telemetryStore gains droppedFrameCount + lastValidationErrors (§13.1)
//   - deriveAlerts gains "telemetry_invalid" AlertEvent kind (§13.2)
//   - trainingStore.receiveTrainMetrics validates symmetrically (§10.4)
//   - ErrorBoundary gains resetKey prop (§14)
// ═══════════════════════════════════════════════════════════════════════════════

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Build a structurally-valid env_step envelope with overrides applied to payload. */
function makeEnvStep(payloadOverride: Record<string, unknown> = {}) {
  return {
    ...(ENV_STEP_A as Record<string, unknown>),
    payload: {
      ...(ENV_STEP_A as any).payload,
      ...payloadOverride,
    },
  };
}

// ─── TV.ROB.1–TV.ROB.7: telemetryStore.receiveEnvStep — store-boundary validation
//
// All tests call receiveEnvStep() directly (no wsClient in the loop).
// The REAL validate() is used throughout — no mocking of the validator.

describe("TV.ROB — telemetryStore.receiveEnvStep store-boundary validation (§10.1/§10.3)", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("TV.ROB.1 — NaN reward field → receiveEnvStep skips; envStep unchanged; droppedFrameCount=1", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    // Seed a good frame so envStep is non-null
    useTelemetryStore.getState().receiveEnvStep(ENV_STEP_A as any);
    const goodState = useTelemetryStore.getState().envStep;
    expect(goodState).not.toBeNull();
    const historyLen = useTelemetryStore.getState().history.length;

    // NaN reward — validate() catches at §4.9 finiteness check
    const badFrame = makeEnvStep({ reward: NaN });
    expect(() => useTelemetryStore.getState().receiveEnvStep(badFrame as any)).not.toThrow();

    expect(useTelemetryStore.getState().envStep).toStrictEqual(goodState); // unchanged
    expect(useTelemetryStore.getState().history).toHaveLength(historyLen); // no new entry
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(1);
  });

  it("TV.ROB.2 — Infinity in a numeric field → receiveEnvStep skips (same semantics)", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().receiveEnvStep(ENV_STEP_A as any);
    const historyLenBefore = useTelemetryStore.getState().history.length;

    const badFrame = makeEnvStep({ load_mw: Infinity });
    useTelemetryStore.getState().receiveEnvStep(badFrame as any);

    expect(useTelemetryStore.getState().history).toHaveLength(historyLenBefore);
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(1);
  });

  it("TV.ROB.3 — missing payload.battery (the PR #46 crash path) → receiveEnvStep DOES NOT THROW; store unchanged", async () => {
    // This tests the exact failure mode: a component reading envStep.battery.soc would
    // throw if this frame reached the store, crashing the ErrorBoundary.
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().receiveEnvStep(ENV_STEP_A as any);
    const goodEnvStep = useTelemetryStore.getState().envStep;

    const { battery: _omit, ...payloadNoBattery } = (ENV_STEP_A as any).payload;
    const badFrame = { ...(ENV_STEP_A as any), payload: payloadNoBattery };

    // Must not throw
    expect(() => useTelemetryStore.getState().receiveEnvStep(badFrame as any)).not.toThrow();

    // Store must be unchanged
    expect(useTelemetryStore.getState().envStep).toStrictEqual(goodEnvStep);
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(1);
  });

  it("TV.ROB.4 — recovery: valid frame accepted after a bad one (per-frame, not sticky)", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");

    // Bad frame
    const badFrame = makeEnvStep({ reward: NaN });
    useTelemetryStore.getState().receiveEnvStep(badFrame as any);
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(1);
    expect(useTelemetryStore.getState().envStep).toBeNull(); // still null — never accepted

    // Next valid frame — must be accepted
    useTelemetryStore.getState().receiveEnvStep(ENV_STEP_A as any);
    expect(useTelemetryStore.getState().envStep).not.toBeNull();
    expect(useTelemetryStore.getState().history).toHaveLength(1);
    // droppedFrameCount stays at 1 (only the one bad frame)
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(1);
  });

  it("TV.ROB.5 — golden env_step_a.json → validate ok:true → receiveEnvStep accepts; envStep updated", async () => {
    // Regression: valid frames MUST still be accepted after the amendment.
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().receiveEnvStep(ENV_STEP_A as any);

    expect(useTelemetryStore.getState().envStep).not.toBeNull();
    expect(useTelemetryStore.getState().history).toHaveLength(1);
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(0); // no false drops
  });

  it("TV.ROB.6 — bad frame increments droppedFrameCount and sets lastValidationErrors", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");

    const badFrame = makeEnvStep({ reward: NaN });
    useTelemetryStore.getState().receiveEnvStep(badFrame as any);

    expect(useTelemetryStore.getState().droppedFrameCount).toBe(1);
    const errs = useTelemetryStore.getState().lastValidationErrors;
    expect(errs.length).toBeGreaterThan(0);
    expect(errs.some((e: string) => e.startsWith("non_finite:"))).toBe(true);
  });

  it("TV.ROB.7 — D13 identity violation → receiveEnvStep skips; deriveAlerts includes telemetry_invalid", async () => {
    // validate() step 4.11 checks D13 identities. Violate cost_total_real_yuan.
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    const { deriveAlerts } = await import("../../src/utils/deriveAlerts");

    const costs = (ENV_STEP_A as any).payload.costs;
    const badCosts = { ...costs, cost_total_real_yuan: costs.cost_total_real_yuan + 5000 };
    const badFrame = makeEnvStep({ costs: badCosts });
    useTelemetryStore.getState().receiveEnvStep(badFrame as any);

    expect(useTelemetryStore.getState().droppedFrameCount).toBe(1);

    // deriveAlerts (amended) should surface a telemetry_invalid alert
    const { droppedFrameCount, lastValidationErrors } = useTelemetryStore.getState();
    const alerts = deriveAlerts(
      useTelemetryStore.getState().history,
      droppedFrameCount,
      lastValidationErrors
    );
    const invalidAlert = alerts.find(a => a.kind === "telemetry_invalid");
    expect(invalidAlert).toBeDefined();
    expect(invalidAlert?.detail).toContain("d13_real:");
  });
});

// ─── TV.ROB.8: ErrorBoundary resetKey (§14) ───────────────────────────────────

describe("TV.ROB — ErrorBoundary resetKey self-heals on key change (§14)", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("TV.ROB.8 — child crash + resetKey change → boundary resets, children re-render", async () => {
    const React = await import("react");
    const { render, screen, cleanup } = await import("@testing-library/react");
    const { ErrorBoundary } = await import("../../src/components/ErrorBoundary");

    let shouldThrow = true;
    const ThrowOnMount = () => {
      if (shouldThrow) throw new Error("simulated crash");
      return React.createElement("div", { "data-testid": "child-ok" }, "OK");
    };

    const { rerender } = render(
      React.createElement(
        ErrorBoundary,
        { resetKey: "session-1" },
        React.createElement(ThrowOnMount, null)
      )
    );

    // Boundary caught the error — child not rendered
    expect(screen.queryByTestId("child-ok")).toBeNull();

    // Fix the component and change resetKey — boundary must reset
    shouldThrow = false;
    rerender(
      React.createElement(
        ErrorBoundary,
        { resetKey: "session-2" },
        React.createElement(ThrowOnMount, null)
      )
    );

    expect(screen.getByTestId("child-ok")).toBeDefined();
    cleanup();
  });
});

// ─── TV.ROB.9: Render integration — store boundary protects UI components ─────
//
// Uses NaN in battery.soc specifically — the field the PR #46 crash path reads.
// Before implementation: store accepts bad frame → component renders "NaN%" → test FAILS (RED)
// After implementation: store rejects bad frame → component shows last-good % → test PASSES

describe("TV.ROB — render integration: bad frame → last-good value shown, no crash (§10.3)", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("TV.ROB.9 — component reading envStep.battery.soc shows last-good after store rejects NaN-soc frame", async () => {
    const React = await import("react");
    const { render, screen, act, cleanup } = await import("@testing-library/react");
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");

    // Minimal component reading battery.soc — the crash-causing field from PR #46
    const SocDisplay = () => {
      const envStep = useTelemetryStore((s) => s.envStep);
      if (!envStep) return React.createElement("div", { "data-testid": "no-data" }, "No data");
      const soc = (envStep as any).battery.soc;
      // toFixed() on NaN produces "NaN" — this is what we check is absent
      return React.createElement("div", { "data-testid": "soc-value" }, `${(soc * 100).toFixed(0)}%`);
    };

    render(React.createElement(SocDisplay, null));
    expect(screen.getByTestId("no-data")).toBeDefined();

    // Accept a valid frame — store updates, component shows good SOC
    await act(async () => {
      useTelemetryStore.getState().receiveEnvStep(ENV_STEP_A as any);
    });
    const goodSoc = (ENV_STEP_A as any).payload.battery.soc;
    const expectedText = `${(goodSoc * 100).toFixed(0)}%`;
    expect(screen.getByTestId("soc-value").textContent).toBe(expectedText);

    // Bad frame: NaN in battery.soc — the exact field the component reads.
    // Before implementation: store ACCEPTS this, component renders "NaN%", assertion FAILS.
    // After implementation: store REJECTS this, envStep unchanged, component still shows goodSoc.
    const badFrame = makeEnvStep({
      battery: { ...(ENV_STEP_A as any).payload.battery, soc: NaN },
    });
    await act(async () => {
      useTelemetryStore.getState().receiveEnvStep(badFrame as any);
    });

    // Last-good SOC must still be shown; "NaN" must not appear
    expect(screen.getByTestId("soc-value").textContent).toBe(expectedText);
    expect(screen.queryByText(/NaN/)).toBeNull();
    cleanup();
  });
});

// ─── TV.ROB.10: trainingStore.receiveTrainMetrics symmetric validation (§10.4) ─

describe("TV.ROB — trainingStore.receiveTrainMetrics store-boundary validation (§10.4)", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("TV.ROB.10 — invalid train_metrics (missing global_step) → trainingStore skips state update", async () => {
    const { useTrainingStore } = await import("../../src/stores/trainingStore");

    // Accept a valid frame first
    useTrainingStore.getState().receiveTrainMetrics(TRAIN_METRICS as any);
    const goodState = useTrainingStore.getState().latestMetrics;
    expect(goodState).not.toBeNull();

    // Bad frame: missing global_step → Zod rejects
    const { global_step: _drop, ...payloadNoStep } = (TRAIN_METRICS as any).payload;
    const badFrame = { ...(TRAIN_METRICS as any), payload: payloadNoStep };
    expect(() => useTrainingStore.getState().receiveTrainMetrics(badFrame as any)).not.toThrow();

    // Store state must be unchanged
    expect(useTrainingStore.getState().latestMetrics).toStrictEqual(goodState);
    expect(useTrainingStore.getState().droppedFrameCount).toBe(1);
  });

  it("TV.ROB.10b — golden train_metrics → accepted (regression)", async () => {
    const { useTrainingStore } = await import("../../src/stores/trainingStore");
    useTrainingStore.getState().receiveTrainMetrics(TRAIN_METRICS as any);
    expect(useTrainingStore.getState().latestMetrics).not.toBeNull();
    expect(useTrainingStore.getState().droppedFrameCount).toBe(0);
  });
});

// ─── TV.ROB golden-fixture regression (validate-telemetry skill) ──────────────

describe("TV.ROB — golden fixtures validate + accepted by store (validate-telemetry skill)", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("TV.ROB.G1 — env_step_a.json: validate() ok:true AND receiveEnvStep accepts with correct payload", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().receiveEnvStep(ENV_STEP_A as any);

    const step = useTelemetryStore.getState().envStep;
    expect(step).not.toBeNull();
    expect((step as any).step).toBe((ENV_STEP_A as any).payload.step);
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(0);
  });

  it("TV.ROB.G2 — env_step_b.json: validate() ok:true AND receiveEnvStep accepts (month-boundary)", async () => {
    const { useTelemetryStore } = await import("../../src/stores/telemetryStore");
    useTelemetryStore.getState().receiveEnvStep(ENV_STEP_B as any);

    const step = useTelemetryStore.getState().envStep;
    expect(step).not.toBeNull();
    expect(useTelemetryStore.getState().droppedFrameCount).toBe(0);
  });
});

// ─── reviewer (frontend-reviewer): wrong-TYPE field through the wsClient gate ──
// TV.ROB.2 covers a missing field and TV.ROB.5 covers null; a wrong-TYPE field (a string
// where a number is required — a realistic serving-encoder bug) is a DISTINCT Zod rejection
// path that must ALSO be dropped before dispatch. Completes the missing/null/wrong-type matrix
// for the D26 gate.
describe("reviewer — wsClient drops a wrong-type field (Zod type rejection, §10.1)", () => {
  let mockWs: MockWsInstance;
  beforeEach(() => {
    mockWs = makeMockWsInstance();
    vi.stubGlobal("WebSocket", vi.fn().mockImplementation(() => mockWs));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("reviewer — env_step with battery.soc as a string → validate() rejects → onEnvStep NOT dispatched", async () => {
    const { createWsClient } = await vi.importActual<typeof import("../../src/clients/wsClient")>(
      "../../src/clients/wsClient"
    );
    const onEnvStep = vi.fn();
    createWsClient({
      url: "ws://localhost/ws/test",
      onEnvStep,
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    }).connect();
    // battery.soc as the string "0.5" — valid JSON, wrong type. Zod must reject before dispatch.
    const p = (ENV_STEP_A as any).payload;
    const badFrame = {
      ...(ENV_STEP_A as any),
      payload: { ...p, battery: { ...p.battery, soc: "0.5" } },
    };
    mockWs.onmessage?.({ data: JSON.stringify(badFrame) } as MessageEvent);
    expect(onEnvStep).not.toHaveBeenCalled();
  });
});
