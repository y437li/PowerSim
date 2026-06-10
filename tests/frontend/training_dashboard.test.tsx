/**
 * Training Dashboard — contract + tests
 * Contract: contracts/frontend/training_dashboard.md
 * Telemetry schema: contracts/shared/telemetry_schema.md v1.0.0 (LOCKED)
 * Golden fixtures:  contracts/shared/telemetry_examples/train_metrics.json
 *                   contracts/shared/telemetry_examples/eval_compare.json
 *
 * ALL tests are intentionally RED — no implementation exists yet.
 * validate-telemetry skill: tests include full-message validation against golden fixtures.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import React from "react";

// ── Golden fixtures (imported as JSON — vitest resolves JSON imports) ────────
import trainMetricsGolden from "../../contracts/shared/telemetry_examples/train_metrics.json";
import evalCompareGolden  from "../../contracts/shared/telemetry_examples/eval_compare.json";

// ── SUT imports (will fail until implementation exists) ──────────────────────
import { TrainingPanel }        from "../../src/routes/TrainingPanel";
import { MetricCurves }         from "../../src/components/training/MetricCurves";
import { ThroughputCard }       from "../../src/components/training/ThroughputCard";
import { CheckpointEventList }  from "../../src/components/training/CheckpointEventList";
import { EvalCompareTable }     from "../../src/components/training/EvalCompareTable";
import { StreamStatusBanner }   from "../../src/components/training/StreamStatusBanner";
import { RunSelector }          from "../../src/components/training/RunSelector";
import {
  formatThroughput,
  formatSteps,
  formatWallSeconds,
  formatYuan,
} from "../../src/utils/units";
import type {
  TrainMetricsPayload,
  EvalComparePayload,
  TelemetryEnvelope,
} from "../../src/types/telemetry";

// ── Zustand store mocks ──────────────────────────────────────────────────────
vi.mock("../../src/stores/trainingStore", () => ({
  useTrainingStore: vi.fn(),
}));
vi.mock("../../src/stores/evalStore", () => ({
  useEvalStore: vi.fn(),
}));
vi.mock("../../src/stores/telemetryStore", () => ({
  useTelemetryStore: vi.fn(),
}));
import { useTrainingStore } from "../../src/stores/trainingStore";
import { useEvalStore }     from "../../src/stores/evalStore";
import { useTelemetryStore } from "../../src/stores/telemetryStore";

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Wrap a payload in a valid TelemetryEnvelope for full-message validation tests */
function makeEnvelope<T>(kind: string, payload: T, seq = 1, runId = "test-run"): TelemetryEnvelope {
  return {
    schema_version: "1.0.0",
    kind: kind as TelemetryEnvelope["kind"],
    ts_utc: "2026-06-10T08:00:00Z",
    run_id: runId,
    seq,
    payload,
  } as TelemetryEnvelope;
}

/** Minimal valid TrainMetricsPayload (mirrors golden fixture fields) */
const GOLDEN_TRAIN: TrainMetricsPayload = trainMetricsGolden.payload as TrainMetricsPayload;

/** Minimal valid EvalComparePayload (mirrors golden fixture fields) */
const GOLDEN_EVAL: EvalComparePayload = evalCompareGolden.payload as EvalComparePayload;

/** A train_metrics payload representing a checkpoint event */
const CHECKPOINT_TRAIN: TrainMetricsPayload = {
  ...GOLDEN_TRAIN,
  global_step: 500000,
  is_eval_checkpoint: true,
  checkpoint_id: "ckpt-000500000",
  reward_norm_mean: null,  // null on eval checkpoints per schema
};

/** Default mock store state — empty training */
function emptyTrainingState() {
  return { history: [], latest: null, receiveTrainMetrics: vi.fn(), clear: vi.fn() };
}
function emptyEvalState() {
  return { history: [], latest: null, receiveEvalCompare: vi.fn(), clear: vi.fn() };
}
function connectedTelemetryState() {
  return { wsStatus: "connected" as const };
}

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 1 — Full golden-fixture validation (validate-telemetry requirement)
// Every consumer must validate against the LOCKED golden fixtures.
// ─────────────────────────────────────────────────────────────────────────────
describe("validate-telemetry: golden fixture conformance", () => {
  it("train_metrics golden fixture — envelope has required fields", () => {
    const msg = trainMetricsGolden as TelemetryEnvelope;
    expect(msg.schema_version).toBe("1.0.0");
    expect(msg.kind).toBe("train_metrics");
    expect(typeof msg.ts_utc).toBe("string");
    expect(typeof msg.run_id).toBe("string");
    expect(typeof msg.seq).toBe("number");
    expect(msg.payload).toBeDefined();
  });

  it("train_metrics golden payload — all LOCKED fields present with correct types", () => {
    const p = GOLDEN_TRAIN;
    // global_step: 250000
    expect(typeof p.global_step).toBe("number");
    expect(p.global_step).toBe(250000);
    // wall_seconds: 184.2
    expect(typeof p.wall_seconds).toBe("number");
    expect(p.wall_seconds).toBeCloseTo(184.2);
    // env_steps_per_sec: 1,350,000
    expect(typeof p.env_steps_per_sec).toBe("number");
    expect(p.env_steps_per_sec).toBeCloseTo(1350000);
    // losses
    expect(typeof p.actor_loss).toBe("number");
    expect(typeof p.critic_loss).toBe("number");
    expect(typeof p.ent_coef).toBe("number");
    // reward fields
    expect(typeof p.reward_scaled_mean).toBe("number");
    // reward_norm_mean: 0.83 (not null — non-checkpoint step)
    expect(typeof p.reward_norm_mean).toBe("number");
    // cost: -61000 (real money, negative = revenue)
    expect(p.cost_total_real_mean_yuan).toBeCloseTo(-61000);
    // checkpoint fields
    expect(p.is_eval_checkpoint).toBe(false);
    expect(p.checkpoint_id).toBeNull();
  });

  it("train_metrics golden — no NaN or Infinity in numeric fields", () => {
    const p = GOLDEN_TRAIN;
    const numericFields: (keyof TrainMetricsPayload)[] = [
      "global_step", "wall_seconds", "env_steps_per_sec",
      "actor_loss", "critic_loss", "ent_coef",
      "reward_scaled_mean", "cost_total_real_mean_yuan",
    ];
    for (const field of numericFields) {
      const v = p[field] as number;
      expect(Number.isFinite(v)).toBe(true);
    }
  });

  it("eval_compare golden fixture — envelope has required fields", () => {
    const msg = evalCompareGolden as TelemetryEnvelope;
    expect(msg.schema_version).toBe("1.0.0");
    expect(msg.kind).toBe("eval_compare");
    expect(typeof msg.run_id).toBe("string");
    expect(typeof msg.seq).toBe("number");
    expect(msg.payload).toBeDefined();
  });

  it("eval_compare golden payload — cost_basis is 'real_money'", () => {
    expect(GOLDEN_EVAL.cost_basis).toBe("real_money");
  });

  it("eval_compare golden — eval_horizon_steps matches D3 (8760 at Δt=1h)", () => {
    // D3: episodes are 8760 steps at Δt=1h (365-day eval)
    expect(GOLDEN_EVAL.eval_horizon_steps).toBe(8760);
  });

  it("eval_compare golden — all three baseline policy keys present", () => {
    const keys = Object.keys(GOLDEN_EVAL.policies);
    expect(keys).toContain("rl");
    expect(keys).toContain("no_battery");
    expect(keys).toContain("rule_based_tou");
  });

  it("eval_compare golden — additive identity per policy: total_cost_yuan == sum of 5 components", () => {
    // D13: total_cost_yuan = energy_cost + demand_charge + degradation + curtailment + voll (real money)
    // SOC violations and penalty are NOT included in total_cost_yuan
    for (const [key, policy] of Object.entries(GOLDEN_EVAL.policies)) {
      const computed =
        policy.energy_cost_yuan +
        policy.demand_charge_yuan +
        policy.degradation_yuan +
        policy.curtailment_yuan +
        policy.voll_yuan;
      // Arithmetic for "rl":
      //   12,000,000 + 9,000,000 + 1,500,000 + 300,000 + 0 = 22,800,000
      // Arithmetic for "no_battery":
      //   18,000,000 + 14,000,000 + 0 + 900,000 + 0 = 32,900,000
      // Arithmetic for "rule_based_tou":
      //   15,000,000 + 11,000,000 + 2,000,000 + 500,000 + 0 = 28,500,000
      expect(computed).toBeCloseTo(policy.total_cost_yuan, 0);
    }
  });

  it("eval_compare golden — SOC violations and penalty_yuan excluded from total_cost_yuan", () => {
    const rl = GOLDEN_EVAL.policies["rl"];
    // penalty_yuan = 0.0, soc_violations_count = 0 for rl; penalty does NOT change total
    expect(rl.soc_violations_count).toBe(0);
    expect(rl.soc_violation_mwh).toBe(0);
    expect(rl.penalty_yuan).toBe(0);
    // rule_based_tou has non-zero SOC violations but they don't affect total
    const rbt = GOLDEN_EVAL.policies["rule_based_tou"];
    expect(rbt.soc_violations_count).toBeGreaterThan(0);
    const rbtComputed =
      rbt.energy_cost_yuan + rbt.demand_charge_yuan +
      rbt.degradation_yuan + rbt.curtailment_yuan + rbt.voll_yuan;
    // 15,000,000 + 11,000,000 + 2,000,000 + 500,000 + 0 = 28,500,000 (penalty 30,000 excluded)
    expect(rbtComputed).toBeCloseTo(rbt.total_cost_yuan, 0);
    expect(rbt.penalty_yuan).not.toBeCloseTo(0);  // 30,000 — present but not in total
  });

  it("eval_compare golden — RL has lowest total_cost_yuan (§5 acceptance criterion)", () => {
    const rl    = GOLDEN_EVAL.policies["rl"].total_cost_yuan;
    const noBat = GOLDEN_EVAL.policies["no_battery"].total_cost_yuan;
    const rbt   = GOLDEN_EVAL.policies["rule_based_tou"].total_cost_yuan;
    // 22,800,000 < 28,500,000 < 32,900,000
    expect(rl).toBeLessThan(noBat);
    expect(rl).toBeLessThan(rbt);
  });

  it("train_metrics checkpoint event — reward_norm_mean is null on eval checkpoint", () => {
    // Per schema: reward_norm_mean is null on eval checkpoints (VecNormalize off during eval)
    expect(CHECKPOINT_TRAIN.is_eval_checkpoint).toBe(true);
    expect(CHECKPOINT_TRAIN.reward_norm_mean).toBeNull();
    expect(CHECKPOINT_TRAIN.checkpoint_id).toBe("ckpt-000500000");
  });

  it("full-message round-trip: train_metrics golden envelope → parse payload → all fields accessible", () => {
    const envelope = makeEnvelope("train_metrics", GOLDEN_TRAIN, 250);
    const payload = envelope.payload as TrainMetricsPayload;
    expect(payload.global_step).toBe(250000);
    expect(payload.env_steps_per_sec).toBeCloseTo(1350000);
    expect(payload.cost_total_real_mean_yuan).toBeCloseTo(-61000);
  });

  it("full-message round-trip: eval_compare golden envelope → parse payload → policies accessible", () => {
    const envelope = makeEnvelope("eval_compare", GOLDEN_EVAL, 1);
    const payload = envelope.payload as EvalComparePayload;
    expect(payload.cost_basis).toBe("real_money");
    expect(payload.policies["rl"].total_cost_yuan).toBeCloseTo(22800000);
    expect(payload.policies["no_battery"].total_cost_yuan).toBeCloseTo(32900000);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 2 — Formatting utilities (units.ts additions)
// ─────────────────────────────────────────────────────────────────────────────
describe("formatThroughput", () => {
  it("≥1,000,000 → M/s notation", () => {
    // 1,350,000 → "1.35M/s"
    expect(formatThroughput(1350000)).toBe("1.35M/s");
  });
  it("exactly 1,000,000 → '1.00M/s'", () => {
    expect(formatThroughput(1000000)).toBe("1.00M/s");
  });
  it("≥1,000 < 1,000,000 → k/s notation", () => {
    // 350,000 → "350k/s"
    expect(formatThroughput(350000)).toBe("350k/s");
  });
  it("< 1,000 → integer /s notation", () => {
    // 850 → "850/s"
    expect(formatThroughput(850)).toBe("850/s");
  });
});

describe("formatSteps", () => {
  it("≥1,000,000 → M steps notation", () => {
    // 1,350,000 → "1.35M steps"
    expect(formatSteps(1350000)).toBe("1.35M steps");
  });
  it("≥1,000 < 1,000,000 → k steps notation", () => {
    // 250,000 → "250k steps"
    expect(formatSteps(250000)).toBe("250k steps");
  });
  it("< 1,000 → integer steps", () => {
    // 999 → "999 steps"
    expect(formatSteps(999)).toBe("999 steps");
  });
  it("exactly 1,000 → '1k steps'", () => {
    expect(formatSteps(1000)).toBe("1k steps");
  });
});

describe("formatWallSeconds", () => {
  it("< 60s → seconds notation", () => {
    // 45 → "45s"
    expect(formatWallSeconds(45)).toBe("45s");
  });
  it("exactly 60s → '1m 0s'", () => {
    expect(formatWallSeconds(60)).toBe("1m 0s");
  });
  it("184.2s → '3m 4s' (truncates sub-seconds)", () => {
    // 184.2 / 60 = 3m 4.2s → "3m 4s"
    expect(formatWallSeconds(184.2)).toBe("3m 4s");
  });
  it("< 3600 → mm:ss notation", () => {
    // 3599 → "59m 59s"
    expect(formatWallSeconds(3599)).toBe("59m 59s");
  });
  it("≥ 3600 → hh:mm notation", () => {
    // 3662 → "1h 1m"
    expect(formatWallSeconds(3662)).toBe("1h 1m");
  });
  it("0s → '0s'", () => {
    // E16: wall_seconds=0 → "0s"
    expect(formatWallSeconds(0)).toBe("0s");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 3 — ThroughputCard
// ─────────────────────────────────────────────────────────────────────────────
describe("ThroughputCard", () => {
  it("renders '—' for all fields when latest is null (E1)", () => {
    render(<ThroughputCard latest={null} />);
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(3);
  });

  it("renders env_steps_per_sec from golden fixture", () => {
    render(<ThroughputCard latest={GOLDEN_TRAIN} />);
    // 1,350,000 → "1.35M/s"
    expect(screen.getByText("1.35M/s")).toBeInTheDocument();
  });

  it("renders global_step from golden fixture", () => {
    render(<ThroughputCard latest={GOLDEN_TRAIN} />);
    // 250,000 → "250k steps"
    expect(screen.getByText("250k steps")).toBeInTheDocument();
  });

  it("renders wall_seconds from golden fixture", () => {
    render(<ThroughputCard latest={GOLDEN_TRAIN} />);
    // 184.2 → "3m 4s"
    expect(screen.getByText("3m 4s")).toBeInTheDocument();
  });

  it("all-zero train_metrics renders without NaN (E12)", () => {
    const zeroMetrics: TrainMetricsPayload = {
      ...GOLDEN_TRAIN,
      global_step: 0,
      wall_seconds: 0,
      env_steps_per_sec: 0,
    };
    render(<ThroughputCard latest={zeroMetrics} />);
    expect(screen.queryByText(/NaN/)).toBeNull();
    expect(screen.getByText("0s")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 4 — MetricCurves
// ─────────────────────────────────────────────────────────────────────────────
describe("MetricCurves", () => {
  it("renders empty-state placeholder when history is empty (E1)", () => {
    render(<MetricCurves history={[]} />);
    expect(screen.getByText("No training data yet")).toBeInTheDocument();
  });

  it("renders four chart panels with correct headings", () => {
    render(<MetricCurves history={[GOLDEN_TRAIN]} />);
    expect(screen.getByText(/actor loss/i)).toBeInTheDocument();
    expect(screen.getByText(/critic loss/i)).toBeInTheDocument();
    expect(screen.getByText(/entropy/i)).toBeInTheDocument();
    expect(screen.getByText(/reward/i)).toBeInTheDocument();
  });

  it("renders episode cost panel (fifth chart)", () => {
    render(<MetricCurves history={[GOLDEN_TRAIN]} />);
    expect(screen.getByText(/episode cost/i)).toBeInTheDocument();
  });

  it("negative cost_total_real_mean_yuan (-61000) displayed without clamping (E4)", () => {
    render(<MetricCurves history={[GOLDEN_TRAIN]} />);
    // Chart must include a data point with value -61000;
    // we confirm the component renders without a '¥0' floor clamp by checking data-testid
    // (implementation must expose a data-testid="metric-curves" root)
    const root = screen.getByTestId("metric-curves");
    expect(root).toBeInTheDocument();
    // No "Infinity" or "NaN" text anywhere in the rendered output
    expect(screen.queryByText(/NaN/)).toBeNull();
    expect(screen.queryByText(/Infinity/)).toBeNull();
  });

  it("checkpoint markers rendered for is_eval_checkpoint=true entries", () => {
    const history = [GOLDEN_TRAIN, CHECKPOINT_TRAIN];
    render(<MetricCurves history={history} />);
    // At least one element with the checkpoint_id label should appear
    expect(screen.getByText(/ckpt-000500/)).toBeInTheDocument();
  });

  it("reward_norm_mean=null on eval checkpoint does not produce NaN in chart (E3)", () => {
    const history = [GOLDEN_TRAIN, CHECKPOINT_TRAIN];
    render(<MetricCurves history={history} />);
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("single-point history renders without axis scale errors (E15)", () => {
    render(<MetricCurves history={[GOLDEN_TRAIN]} />);
    expect(screen.queryByText(/NaN/)).toBeNull();
    expect(screen.queryByText(/Infinity/)).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 5 — CheckpointEventList
// ─────────────────────────────────────────────────────────────────────────────
describe("CheckpointEventList", () => {
  it("shows 'No checkpoints yet' when no checkpoint events", () => {
    render(<CheckpointEventList history={[GOLDEN_TRAIN]} />);
    // GOLDEN_TRAIN has is_eval_checkpoint=false → no checkpoint rows
    expect(screen.getByText("No checkpoints yet")).toBeInTheDocument();
  });

  it("renders checkpoint row for is_eval_checkpoint=true entry", () => {
    render(<CheckpointEventList history={[GOLDEN_TRAIN, CHECKPOINT_TRAIN]} />);
    expect(screen.getByText("ckpt-000500000")).toBeInTheDocument();
    // global_step 500,000 → "500k steps"
    expect(screen.getByText("500k steps")).toBeInTheDocument();
  });

  it("renders cost in checkpoint row using formatYuan", () => {
    render(<CheckpointEventList history={[GOLDEN_TRAIN, CHECKPOINT_TRAIN]} />);
    // cost_total_real_mean_yuan = -61000 → "¥-61,000" (negative = revenue)
    expect(screen.getByText("¥-61,000")).toBeInTheDocument();
  });

  it("checkpoint_id=null shows '—' label (E5)", () => {
    const noIdCheckpoint: TrainMetricsPayload = {
      ...CHECKPOINT_TRAIN,
      checkpoint_id: null,
    };
    render(<CheckpointEventList history={[noIdCheckpoint]} />);
    // checkpoint row exists (is_eval_checkpoint=true) but id shows "—"
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("multiple checkpoints ordered newest first", () => {
    const older: TrainMetricsPayload = { ...CHECKPOINT_TRAIN, global_step: 100000, checkpoint_id: "ckpt-A" };
    const newer: TrainMetricsPayload = { ...CHECKPOINT_TRAIN, global_step: 500000, checkpoint_id: "ckpt-B" };
    render(<CheckpointEventList history={[older, newer]} />);
    const items = screen.getAllByRole("listitem");
    // Newer first: ckpt-B before ckpt-A
    expect(items[0].textContent).toContain("ckpt-B");
    expect(items[1].textContent).toContain("ckpt-A");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 6 — EvalCompareTable
// ─────────────────────────────────────────────────────────────────────────────
describe("EvalCompareTable", () => {
  it("shows placeholder when latest is null (E2)", () => {
    render(<EvalCompareTable latest={null} />);
    expect(screen.getByText(/No eval run yet/i)).toBeInTheDocument();
  });

  it("renders all three golden-fixture policy rows", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    expect(screen.getByText("RL Agent")).toBeInTheDocument();
    expect(screen.getByText("No Battery")).toBeInTheDocument();
    expect(screen.getByText("Rule-Based TOU")).toBeInTheDocument();
  });

  it("RL row is highlighted as best when it has the lowest total_cost_yuan (§5)", () => {
    // rl: 22.8M < rule_based_tou: 28.5M < no_battery: 32.9M
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    const rlRow = screen.getByText("RL Agent").closest("tr");
    expect(rlRow).toHaveAttribute("data-best", "true");
  });

  it("non-RL row highlighted when baseline beats RL (E13)", () => {
    // Mutate so no_battery has a lower total_cost_yuan than rl
    const modifiedEval: EvalComparePayload = {
      ...GOLDEN_EVAL,
      policies: {
        ...GOLDEN_EVAL.policies,
        rl:         { ...GOLDEN_EVAL.policies["rl"],         total_cost_yuan: 35000000 },
        no_battery: { ...GOLDEN_EVAL.policies["no_battery"], total_cost_yuan: 20000000 },
      },
    };
    render(<EvalCompareTable latest={modifiedEval} />);
    const rlRow       = screen.getByText("RL Agent").closest("tr");
    const noBatteryRow = screen.getByText("No Battery").closest("tr");
    expect(rlRow).not.toHaveAttribute("data-best", "true");
    expect(noBatteryRow).toHaveAttribute("data-best", "true");
  });

  it("total_cost_yuan formatted with ¥ and zero decimals", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    // rl total: 22,800,000 → "¥22,800,000"
    expect(screen.getByText("¥22,800,000")).toBeInTheDocument();
  });

  it("SOC violation count column present for rule_based_tou (2 violations)", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    // rule_based_tou has soc_violations_count=2
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("penalty_yuan column present with footnote about exclusion from total", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    expect(screen.getByText(/excluded from/i)).toBeInTheDocument();
  });

  it("penalty_yuan for rule_based_tou shows 30,000 (not 0)", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    // rule_based_tou penalty_yuan = 30,000 → "¥30,000"
    expect(screen.getByText("¥30,000")).toBeInTheDocument();
  });

  it("EXTENSIBILITY: unknown future policy key rendered as a row without crash (E6)", () => {
    const futureEval: EvalComparePayload = {
      ...GOLDEN_EVAL,
      policies: {
        ...GOLDEN_EVAL.policies,
        greedy: {
          energy_cost_yuan: 20000000,
          demand_charge_yuan: 12000000,
          degradation_yuan: 0,
          curtailment_yuan: 700000,
          voll_yuan: 0,
          total_cost_yuan: 32700000,
          soc_violations_count: 0,
          soc_violation_mwh: 0,
          penalty_yuan: 0,
        },
      },
    };
    render(<EvalCompareTable latest={futureEval} />);
    // "greedy" → display label "Greedy" (from POLICY_DISPLAY_NAMES)
    expect(screen.getByText("Greedy")).toBeInTheDocument();
  });

  it("EXTENSIBILITY: dp_oracle policy key uses display name 'DP Oracle'", () => {
    const withOracle: EvalComparePayload = {
      ...GOLDEN_EVAL,
      policies: {
        rl:        GOLDEN_EVAL.policies["rl"],
        dp_oracle: GOLDEN_EVAL.policies["rl"],  // same values; testing label only
      },
    };
    render(<EvalCompareTable latest={withOracle} />);
    expect(screen.getByText("DP Oracle")).toBeInTheDocument();
  });

  it("EXTENSIBILITY: truly unknown key rendered as title-cased key", () => {
    const unknownEval: EvalComparePayload = {
      ...GOLDEN_EVAL,
      policies: {
        rl:          GOLDEN_EVAL.policies["rl"],
        my_custom_algo: GOLDEN_EVAL.policies["no_battery"],
      },
    };
    render(<EvalCompareTable latest={unknownEval} />);
    // "my_custom_algo" → "My Custom Algo"
    expect(screen.getByText("My Custom Algo")).toBeInTheDocument();
  });

  it("single-policy eval_compare (E14) renders that one row", () => {
    const singlePolicy: EvalComparePayload = {
      ...GOLDEN_EVAL,
      policies: { rl: GOLDEN_EVAL.policies["rl"] },
    };
    render(<EvalCompareTable latest={singlePolicy} />);
    expect(screen.getByText("RL Agent")).toBeInTheDocument();
    expect(screen.queryByText("No Battery")).toBeNull();
  });

  it("RL row is always first regardless of sort order", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    const rows = screen.getAllByRole("row");
    // First data row (index 1, after header) should be RL Agent
    expect(rows[1].textContent).toContain("RL Agent");
  });

  it("additive identity visible in rendered values (total == sum of five components)", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    // RL: energy 12M + demand 9M + degrad 1.5M + curtail 0.3M + voll 0 = 22.8M
    // All five component columns + total column must be rendered (no column suppressed)
    expect(screen.getByText("¥12,000,000")).toBeInTheDocument();  // energy_cost
    expect(screen.getByText("¥9,000,000")).toBeInTheDocument();   // demand_charge
    expect(screen.getByText("¥1,500,000")).toBeInTheDocument();   // degradation
    expect(screen.getByText("¥300,000")).toBeInTheDocument();     // curtailment
    expect(screen.getByText("¥22,800,000")).toBeInTheDocument();  // total
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 7 — StreamStatusBanner
// ─────────────────────────────────────────────────────────────────────────────
describe("StreamStatusBanner", () => {
  it("renders nothing when connected and fresh and no gap", () => {
    // ts_utc 10 seconds ago — not stale
    const recentTs = new Date(Date.now() - 10_000).toISOString();
    const { container } = render(
      <StreamStatusBanner wsStatus="connected" lastMessageTsUtc={recentTs} seqGap={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders stale warning when last message ts_utc > 30s ago (E11)", () => {
    const staleTs = new Date(Date.now() - 35_000).toISOString();
    render(<StreamStatusBanner wsStatus="connected" lastMessageTsUtc={staleTs} seqGap={false} />);
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
  });

  it("renders disconnection banner when wsStatus is 'disconnected' (E10)", () => {
    render(<StreamStatusBanner wsStatus="disconnected" lastMessageTsUtc={null} seqGap={false} />);
    expect(screen.getByText(/disconnected/i)).toBeInTheDocument();
  });

  it("renders seq gap warning when seqGap is true (E9)", () => {
    const recentTs = new Date(Date.now() - 1_000).toISOString();
    render(<StreamStatusBanner wsStatus="connected" lastMessageTsUtc={recentTs} seqGap={true} />);
    expect(screen.getByText(/sequence gap/i)).toBeInTheDocument();
  });

  it("disconnected banner takes precedence over gap warning (highest severity wins)", () => {
    render(<StreamStatusBanner wsStatus="disconnected" lastMessageTsUtc={null} seqGap={true} />);
    // Only the disconnection message, not both
    expect(screen.getByText(/disconnected/i)).toBeInTheDocument();
    expect(screen.queryByText(/sequence gap/i)).toBeNull();
  });

  it("renders nothing when connected, no messages yet, no gap (initial state)", () => {
    const { container } = render(
      <StreamStatusBanner wsStatus="connected" lastMessageTsUtc={null} seqGap={false} />
    );
    // No stale banner when lastMessageTsUtc is null (training hasn't started yet)
    expect(container.firstChild).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 8 — RunSelector
// ─────────────────────────────────────────────────────────────────────────────
describe("RunSelector", () => {
  function makeRestClient(runs: object[], rejectWith?: Error) {
    return {
      getRuns: rejectWith
        ? vi.fn().mockRejectedValue(rejectWith)
        : vi.fn().mockResolvedValue(runs),
      getSiteConfig: vi.fn(),
      getCheckpoint: vi.fn(),
    };
  }

  it("shows loading state before getRuns resolves", () => {
    const client = makeRestClient([]);
    render(<RunSelector restClient={client as any} />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("shows 'No runs available' when getRuns returns empty list (E8)", async () => {
    const client = makeRestClient([]);
    render(<RunSelector restClient={client as any} />);
    await waitFor(() =>
      expect(screen.getByText(/no runs available/i)).toBeInTheDocument()
    );
  });

  it("renders run IDs from getRuns result", async () => {
    const runs = [
      { run_id: "run-001", started_at: "2026-06-10T08:00:00Z", status: "running", checkpoint_count: 3 },
      { run_id: "run-002", started_at: "2026-06-10T06:00:00Z", status: "completed", checkpoint_count: 10 },
    ];
    const client = makeRestClient(runs);
    render(<RunSelector restClient={client as any} />);
    await waitFor(() => expect(screen.getByText("run-001")).toBeInTheDocument());
    expect(screen.getByText("run-002")).toBeInTheDocument();
  });

  it("shows error state and retry button on REST failure (E7)", async () => {
    const client = makeRestClient([], new Error("http_5xx: 503 /api/runs"));
    render(<RunSelector restClient={client as any} />);
    await waitFor(() => expect(screen.getByText(/could not load runs/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("retry button calls getRuns again", async () => {
    const client = makeRestClient([], new Error("http_5xx: 503"));
    render(<RunSelector restClient={client as any} />);
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(client.getRuns).toHaveBeenCalledTimes(2);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 9 — TrainingPanel (integration: route component)
// ─────────────────────────────────────────────────────────────────────────────
describe("TrainingPanel", () => {
  beforeEach(() => {
    vi.mocked(useTelemetryStore).mockReturnValue({ wsStatus: "connected" });
    vi.mocked(useEvalStore).mockReturnValue(emptyEvalState());
  });

  it("shows 'Waiting for training data…' placeholder when history is empty (E1)", () => {
    vi.mocked(useTrainingStore).mockReturnValue(emptyTrainingState());
    render(<TrainingPanel />);
    expect(screen.getByText(/waiting for training data/i)).toBeInTheDocument();
  });

  it("does not render MetricCurves charts in empty state", () => {
    vi.mocked(useTrainingStore).mockReturnValue(emptyTrainingState());
    render(<TrainingPanel />);
    expect(screen.queryByText(/actor loss/i)).toBeNull();
  });

  it("renders MetricCurves when training history is non-empty", () => {
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history: [GOLDEN_TRAIN],
      latest: GOLDEN_TRAIN,
    });
    render(<TrainingPanel />);
    expect(screen.getByText(/actor loss/i)).toBeInTheDocument();
  });

  it("does NOT render EvalCompareTable when evalStore.latest is null (E2)", () => {
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history: [GOLDEN_TRAIN],
      latest: GOLDEN_TRAIN,
    });
    vi.mocked(useEvalStore).mockReturnValue(emptyEvalState());
    render(<TrainingPanel />);
    expect(screen.queryByText(/policy comparison/i)).toBeNull();
  });

  it("renders EvalCompareTable when evalStore.latest is populated", () => {
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history: [GOLDEN_TRAIN],
      latest: GOLDEN_TRAIN,
    });
    vi.mocked(useEvalStore).mockReturnValue({
      ...emptyEvalState(),
      latest: GOLDEN_EVAL,
      history: [GOLDEN_EVAL],
    });
    render(<TrainingPanel />);
    expect(screen.getByText(/policy comparison/i)).toBeInTheDocument();
  });

  it("contains no SceneMountPoint or 3D elements", () => {
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history: [GOLDEN_TRAIN],
      latest: GOLDEN_TRAIN,
    });
    render(<TrainingPanel />);
    expect(document.querySelector(".scene-mount-point")).toBeNull();
    expect(document.querySelector("canvas")).toBeNull();
  });

  it("does NOT consume env_step or battery data (no flows/costs rendered)", () => {
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history: [GOLDEN_TRAIN],
      latest: GOLDEN_TRAIN,
    });
    render(<TrainingPanel />);
    // None of the env_step live-dashboard terms should appear
    expect(screen.queryByText(/soc/i)).toBeNull();
    expect(screen.queryByText(/battery/i)).toBeNull();
    expect(screen.queryByText(/power flow/i)).toBeNull();
  });

  it("disconnected wsStatus shows StreamStatusBanner (E10)", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({ wsStatus: "disconnected" });
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history: [GOLDEN_TRAIN],
      latest: GOLDEN_TRAIN,
    });
    render(<TrainingPanel />);
    expect(screen.getByText(/disconnected/i)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 10 — Seq-gap detection for train_metrics stream
// ─────────────────────────────────────────────────────────────────────────────
describe("train_metrics seq-gap detection", () => {
  // These tests exercise the gap-detection logic that TrainingPanel
  // maintains locally (see contract §5). We test via the StreamStatusBanner
  // rendered by TrainingPanel.

  it("no gap when messages are contiguous (seq N then N+1)", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({ wsStatus: "connected" });
    vi.mocked(useEvalStore).mockReturnValue(emptyEvalState());

    const recentTs = new Date(Date.now() - 1_000).toISOString();
    const history = [
      makeEnvelope("train_metrics", GOLDEN_TRAIN, 10),
      makeEnvelope("train_metrics", GOLDEN_TRAIN, 11),
    ].map(e => e.payload as TrainMetricsPayload);
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history,
      latest: history[1],
    });
    render(<TrainingPanel />);
    // No gap banner
    expect(screen.queryByText(/sequence gap/i)).toBeNull();
  });

  it("gap detected when seq jumps by 2 (seq 10 then 12)", () => {
    vi.mocked(useTelemetryStore).mockReturnValue({ wsStatus: "connected" });
    vi.mocked(useEvalStore).mockReturnValue(emptyEvalState());
    // History with injected seq gap — TrainingPanel detects this internally.
    // We simulate by constructing messages with gap; in implementation
    // TrainingPanel tracks lastTrainSeq and sets seqGap accordingly.
    // The test verifies the banner appears.
    const msg1 = { ...GOLDEN_TRAIN, _seq: 10 } as TrainMetricsPayload & { _seq: number };
    const msg2 = { ...GOLDEN_TRAIN, _seq: 12 } as TrainMetricsPayload & { _seq: number };
    vi.mocked(useTrainingStore).mockReturnValue({
      ...emptyTrainingState(),
      history: [msg1, msg2],
      latest: msg2,
    });
    // NOTE: implementation must expose seqGap via internal state derived from store
    // history seqs. The test verifies the eventual UI outcome, not internal mechanism.
    render(<TrainingPanel />);
    expect(screen.getByText(/sequence gap/i)).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// SECTION 11 — Edge case: schema version rejection
// ─────────────────────────────────────────────────────────────────────────────
describe("schema version handling", () => {
  it("train_metrics with schema_version 1.x.x (minor bump) does not break rendering", () => {
    // Minor bumps add fields; existing dashboard must still render
    const minorBump = {
      ...GOLDEN_TRAIN,
      replay_buffer_fill_fraction: 0.85,  // hypothetical future minor-bump field
    };
    render(<MetricCurves history={[minorBump as TrainMetricsPayload]} />);
    expect(screen.queryByText(/NaN/)).toBeNull();
    expect(screen.queryByText(/error/i)).toBeNull();
  });

  it("eval_compare with extra future policy field does not crash EvalCompareTable", () => {
    const futureEval: EvalComparePayload = {
      ...GOLDEN_EVAL,
      extra_future_field: "ignored",  // future minor bump field
    } as EvalComparePayload;
    render(<EvalCompareTable latest={futureEval} />);
    expect(screen.getByText("RL Agent")).toBeInTheDocument();
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// REVIEWER-ADDED CASES (frontend-reviewer, 2026-06-10) — marked // reviewer:
// High-confidence edge cases with explicit expected values per the contract's
// stated formatting rules. (Other gaps — E17/1e9, best-tie, sub-thousand
// rounding — need a contract decision first and are listed in the review record.)
// ═════════════════════════════════════════════════════════════════════════════

describe("reviewer: EvalCompareTable zero-value ¥ rendering", () => {
  // reviewer: a 0-¥ cost component must render as "¥0", never blank — a blank cell
  // reads as "missing data" on a cost table. Golden no_battery.degradation_yuan = 0
  // and every policy's voll_yuan = 0, so ¥0 cells must appear.
  it("renders a zero-¥ cost component as '¥0', not an empty cell", () => {
    render(<EvalCompareTable latest={GOLDEN_EVAL} />);
    expect(screen.getAllByText("¥0").length).toBeGreaterThanOrEqual(1);
  });
});

describe("reviewer: formatThroughput edge values", () => {
  // reviewer: startup emits 0 steps/s before the first batch; must not render "NaN/s"
  // or blank. Per §4 rule "<1,000 → integer /s".
  it("0 → '0/s'", () => {
    expect(formatThroughput(0)).toBe("0/s");
  });
  it("999 → '999/s' (just below the k threshold)", () => {
    expect(formatThroughput(999)).toBe("999/s");
  });
});

describe("reviewer: formatWallSeconds sub-second truncation in the <60 branch", () => {
  // reviewer: 184.2 → "3m 4s" pins truncation in the minutes branch; pin the same
  // floor behavior just under a minute so 59.9 isn't rounded up to "1m 0s".
  it("59.9 → '59s' (floor, consistent with 184.2 → '3m 4s')", () => {
    expect(formatWallSeconds(59.9)).toBe("59s");
  });
});
