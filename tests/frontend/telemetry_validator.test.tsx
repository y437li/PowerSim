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

import { describe, it, expect } from "vitest";

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
