/**
 * tests/frontend/stage_algorithm.test.tsx
 *
 * Contract: contracts/frontend/stage_algorithm.md
 * REBUILD_SPEC: §5 (training methodology)
 * LINEAGE: D32 §(a)/(c) (algorithm registry + five-stage spine)
 *
 * AMENDED 2026-06-14 Round 1 (rl-architect authority):
 *   CALL 1 — §5 defaults win (lr=1e-4, γ=0.999, batch=512, 500k steps, 4 envs,
 *             τ=0.005, ent_coef=auto, train_freq=1, gradient_steps=1)
 *   CALL 2 — baseline_only is the v1 functional default; SAC carries coming-soon copy
 *
 * AMENDED 2026-06-14 Round 2 (frontend-reviewer C1/C2/C3 + USER Option B):
 *   C1 — POST body field names → RunConfig canonical (total_env_steps, eval_every_steps,
 *         lr, hidden_sizes); pending serving contract contracts/serving/training_config.md
 *   C2 — gamma REMOVED from SacHyperparams (LOCKED constant 0.999, training_pipeline.md §3.1);
 *         T-HYPER-5/6 repurposed; gamma appears only in POST body constants
 *   C3 — nEnvs 256 cap removed; valid = power of 2, ≥ 1; UI cap pending training-engineer
 *   TQ12 — isConfirmEnabled gates hyperparam errors on algorithmType=sac (§3.7)
 *   OPT-B — SAC secondary/de-emphasized; Baseline-only is visual primary (§4.2)
 *   evalFreq default: 50_000 → 10_000 (RunConfig eval_every_steps canonical)
 *
 * Vitest + React Testing Library v16
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { useStageAlgorithmStore, getHyperparamErrors } from '../../src/stores/stageAlgorithmStore';
import StageTwoAlgorithm from '../../src/components/wizard/StageTwoAlgorithm';

// ── Mock fetch (POST /api/training/config) ─────────────────────────────────

const MOCK_CONFIG_RESPONSE = {
  config_id: 'cfg-uuid-001',
  config_hash: 'abc123def456',
};

function makeFetchOk() {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(MOCK_CONFIG_RESPONSE),
    } as Response),
  );
}

function makeFetchFail(status = 500, body = { error: 'Internal error' }) {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({
      ok: false,
      status,
      json: () => Promise.resolve(body),
    } as Response),
  );
}

// ── §5-canonical defaults (CALL 1, Round 2 amendments) ────────────────────
// REBUILD_SPEC §5 / training_pipeline.md §3 RunConfig:
//   lr=1e-4, batch=512, buffer=1e6, 500k steps, 4 envs (DummyVecEnv)
//   evalFreq=10_000 (RunConfig eval_every_steps default)
//   gamma=0.999 LOCKED — NOT in this interface (constant only, C2)

const DEFAULT_HYPERPARAMS = {
  totalSteps:   500_000,     // §5: 500k timesteps
  evalFreq:     10_000,      // RunConfig eval_every_steps default (Round 2)
  batchSize:    512,         // §5: batch 512
  learningRate: 1e-4,        // §5: lr 1e-4  (→ POST body field: lr)
  bufferSize:   1_000_000,   // §5: buffer 1e6
  nEnvs:        4,           // CALL 1: 4 parallel envs (DummyVecEnv)
  // gamma: intentionally absent — LOCKED constant 0.999 (training_pipeline.md §3.1, C2)
};

// ── Default helpers ─────────────────────────────────────────────────────────

function renderStage(props: { stageOneComplete?: boolean } = {}) {
  const onBack = vi.fn();
  const onContinue = vi.fn();
  const result = render(
    <StageTwoAlgorithm
      stageOneComplete={props.stageOneComplete ?? true}
      onBack={onBack}
      onContinue={onContinue}
    />,
  );
  return { onBack, onContinue, ...result };
}

/** Switch to SAC mode (needed when hyperparam form must be visible). */
function switchToSac() {
  fireEvent.click(screen.getByTestId('algo-card-sac'));
}

// ── Setup / teardown ───────────────────────────────────────────────────────

beforeEach(() => {
  useStageAlgorithmStore.getState().reset();
  makeFetchOk();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ══════════════════════════════════════════════════════════════════════════════
// §T1 — LOCKED state (Stage ① not COMPLETE)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T1 LOCKED state (stage-one not complete)', () => {
  it('[T-LOCK-1] shows locked notice; content section absent from DOM', () => {
    renderStage({ stageOneComplete: false });

    expect(screen.getByTestId('stage-two-locked')).toBeTruthy();
    expect(screen.queryByTestId('stage-two-content')).toBeNull();
  });

  it('[T-LOCK-2] locked state: algorithm cards absent from DOM (not just hidden)', () => {
    renderStage({ stageOneComplete: false });

    expect(screen.queryByTestId('algo-card-sac')).toBeNull();
    expect(screen.queryByTestId('algo-card-baseline-only')).toBeNull();
    expect(screen.queryByTestId('hyperparam-header')).toBeNull();
    expect(screen.queryByTestId('baselines-section')).toBeNull();
  });

  it('[T-LOCK-3] locked state: "← Go to Config" link calls onBack()', () => {
    const { onBack } = renderStage({ stageOneComplete: false });

    fireEvent.click(screen.getByTestId('stage-two-locked-go-config'));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('[T-LOCK-4] locked state: back button in footer still calls onBack()', () => {
    const { onBack } = renderStage({ stageOneComplete: false });

    fireEvent.click(screen.getByTestId('stage-two-back'));
    expect(onBack).toHaveBeenCalledOnce();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T2 — Initial render (CALL 2: baseline_only is the v1 functional default)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T2 Initial render — baseline_only is the v1 functional default (CALL 2)', () => {
  it('[T-INIT-1] content section visible; baseline_only card selected by default (CALL 2)', () => {
    renderStage();

    expect(screen.getByTestId('stage-two-content')).toBeTruthy();
    // CALL 2: baseline_only is the default — not SAC
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('algo-card-sac').getAttribute('aria-checked')).toBe('false');
  });

  it('[T-INIT-2] algorithm cards have role=radio; group has role=radiogroup + aria-label', () => {
    renderStage();

    expect(screen.getByTestId('algo-card-sac').getAttribute('role')).toBe('radio');
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('role')).toBe('radio');

    const group = screen.getByRole('radiogroup', { name: 'Training algorithm' });
    expect(group).toBeTruthy();
  });

  it('[T-INIT-3] do_nothing and peak_shave baselines checked by default', () => {
    renderStage();

    const doNothing = screen.getByTestId('baseline-checkbox-do_nothing') as HTMLInputElement;
    const peakShave = screen.getByTestId('baseline-checkbox-peak_shave') as HTMLInputElement;
    const importMin = screen.getByTestId('baseline-checkbox-import_minimiser') as HTMLInputElement;

    expect(doNothing.checked).toBe(true);
    expect(peakShave.checked).toBe(true);
    expect(importMin.checked).toBe(false);
  });

  it('[T-INIT-4] hyperparam section ABSENT on initial render (baseline_only); baseline notice shown; gamma never rendered', () => {
    renderStage();

    // CALL 2: default is baseline_only → HyperparamForm must not be in DOM
    expect(screen.queryByTestId('hyperparam-section')).toBeNull();
    // Baseline-only notice visible immediately (no interaction needed)
    expect(screen.getByTestId('algo-baseline-notice')).toBeTruthy();
    // C2: gamma is a LOCKED constant — no gamma input anywhere in the form
    expect(screen.queryByTestId('hyperparam-gamma')).toBeNull();
  });

  it('[T-INIT-5] SAC card has coming-soon copy; notice not shown until SAC selected', () => {
    renderStage();
    // Coming-soon notice only appears when SAC is actively selected
    expect(screen.queryByTestId('algo-sac-coming-soon-notice')).toBeNull();

    switchToSac();
    expect(screen.getByTestId('algo-sac-coming-soon-notice')).toBeTruthy();
  });

  it('[T-INIT-6] Confirm button enabled on initial render (baseline_only + 2 baselines = valid)', () => {
    renderStage();
    const confirmBtn = screen.getByTestId('stage-two-confirm') as HTMLButtonElement;
    expect(confirmBtn.getAttribute('aria-disabled')).toBe('false');
  });

  it('[T-INIT-7] stage-two-algorithm testid exists at root', () => {
    renderStage();
    expect(screen.getByTestId('stage-two-algorithm')).toBeTruthy();
  });

  it('[T-INIT-8] SAC card has future-badge element (Option B: SAC is secondary/de-emphasized)', () => {
    // Option B (USER decision 2026-06-14): SAC is a secondary "future capability" entry
    renderStage();
    expect(screen.getByTestId('algo-card-sac-future-badge')).toBeTruthy();
    // The baseline-only card should NOT have a future-badge
    expect(screen.queryByTestId('algo-card-baseline-only-future-badge')).toBeNull();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T3 — Algorithm card interaction
// ══════════════════════════════════════════════════════════════════════════════

describe('§T3 Algorithm card interaction', () => {
  it('[T-ALGO-1] clicking SAC card: baseline_only deselected; hyperparam section added to DOM', () => {
    renderStage();

    // Initial: baseline_only selected, no hyperparam section
    expect(screen.queryByTestId('hyperparam-section')).toBeNull();

    switchToSac();

    expect(screen.getByTestId('algo-card-sac').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('aria-checked')).toBe('false');
    expect(screen.getByTestId('hyperparam-section')).toBeTruthy();
  });

  it('[T-ALGO-2] baseline-only notice shown on initial render; hidden after switching to SAC', () => {
    renderStage();

    // Initial: baseline_only selected → notice visible immediately
    expect(screen.getByTestId('algo-baseline-notice')).toBeTruthy();

    switchToSac();
    expect(screen.queryByTestId('algo-baseline-notice')).toBeNull();
  });

  it('[T-ALGO-3] switching SAC → baseline_only removes hyperparam section; notice reappears', () => {
    renderStage();

    switchToSac();
    expect(screen.getByTestId('hyperparam-section')).toBeTruthy();

    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    expect(screen.queryByTestId('hyperparam-section')).toBeNull();
    expect(screen.getByTestId('algo-baseline-notice')).toBeTruthy();
  });

  it('[T-ALGO-4] switching algorithm when COMPLETE transitions to STALE', async () => {
    makeFetchOk();
    renderStage();

    // Confirm with baseline_only (the default) → COMPLETE
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });

    // Switch to SAC → STALE
    switchToSac();
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-ALGO-5] Space key on SAC card selects SAC (keyboard nav)', () => {
    renderStage();

    const sacCard = screen.getByTestId('algo-card-sac');
    fireEvent.keyDown(sacCard, { key: ' ', code: 'Space' });

    expect(screen.getByTestId('algo-card-sac').getAttribute('aria-checked')).toBe('true');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T4 — Hyperparam validation (pure getHyperparamErrors; §5-canonical defaults)
//        Note: gamma is NOT in SacHyperparams — LOCKED constant 0.999 (C2)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T4 Hyperparam validation', () => {
  it('[T-HYPER-1] getHyperparamErrors returns empty for all §5-canonical defaults (CALL 1, Round 2)', () => {
    // Hand-computed: all 6 user-editable §5 defaults within valid ranges:
    // totalSteps=500_000 ≥ 100_000 ✓ (×5 the minimum)
    // evalFreq=10_000 ≥ 1_000 ✓ (RunConfig eval_every_steps canonical)
    // batchSize=512 is power-of-2, 32–4096 ✓ (2^9)
    // learningRate=1e-4 in [1e-5, 1e-2] ✓ (middle of range)
    // bufferSize=1_000_000 ≥ 512×4=2048 ✓ (×488 the minimum)
    // nEnvs=4 is power-of-2, ≥ 1 ✓ (2^2; no 256 cap — C3)
    // gamma: NOT in DEFAULT_HYPERPARAMS — LOCKED constant (C2)
    const errors = getHyperparamErrors(DEFAULT_HYPERPARAMS);
    expect(errors).toHaveLength(0);
  });

  it('[T-HYPER-2] totalSteps below 100_000 produces error', () => {
    // 99_999 < 100_000 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, totalSteps: 99_999 });
    expect(errors.filter(e => e.field === 'totalSteps')).toHaveLength(1);
    expect(errors.filter(e => e.field === 'totalSteps')[0].type).toBe('error');
  });

  it('[T-HYPER-3] learningRate out of range: below 1e-5', () => {
    // 5e-6 < 1e-5 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, learningRate: 5e-6 });
    expect(errors.filter(e => e.field === 'learningRate')).toHaveLength(1);
  });

  it('[T-HYPER-4] learningRate out of range: above 1e-2', () => {
    // 0.02 > 1e-2 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, learningRate: 0.02 });
    expect(errors.filter(e => e.field === 'learningRate')).toHaveLength(1);
  });

  it('[T-HYPER-5] gamma is NOT a SacHyperparams field; getHyperparamErrors produces no gamma key (C2)', () => {
    // C2 fix: gamma is LOCKED constant 0.999 (training_pipeline.md §3.1).
    // getHyperparamErrors() does not accept or return gamma errors.
    // DEFAULT_HYPERPARAMS has no 'gamma' key — confirm absence.
    const errors = getHyperparamErrors(DEFAULT_HYPERPARAMS);
    const gammaErrors = errors.filter(e => e.field === ('gamma' as never));
    expect(gammaErrors).toHaveLength(0);
    expect(Object.prototype.hasOwnProperty.call(DEFAULT_HYPERPARAMS, 'gamma')).toBe(false);
  });

  it('[T-HYPER-6] nEnvs=512 is VALID — no 256 cap (C3; RunConfig power-of-2 ≥ 1 only)', () => {
    // C3 fix: removed incorrect 256 cap from §3.2.
    // 512 = 2^9 is a power of 2 ≥ 1 → valid per RunConfig (training_pipeline.md §3).
    // Hand-computed: 512 is 2^9 ✓; 512 ≥ 1 ✓; no explicit max in RunConfig.
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, nEnvs: 512 });
    expect(errors.filter(e => e.field === 'nEnvs')).toHaveLength(0);
  });

  it('[T-HYPER-7] bufferSize too small: < batchSize × 4', () => {
    // batchSize=512; minimum valid bufferSize = 512×4=2048; 2047 is invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, bufferSize: 2047 });
    expect(errors.filter(e => e.field === 'bufferSize')).toHaveLength(1);
  });

  it('[T-HYPER-8] bufferSize exact minimum: batchSize × 4 (valid)', () => {
    // batchSize=512; bufferSize=512×4=2048 → exactly meets the minimum → valid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, bufferSize: 2048 });
    expect(errors.filter(e => e.field === 'bufferSize')).toHaveLength(0);
  });

  it('[T-HYPER-9] nEnvs not a power of 2 produces error', () => {
    // nEnvs=15 is not a power of 2 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, nEnvs: 15 });
    expect(errors.filter(e => e.field === 'nEnvs')).toHaveLength(1);
  });

  it('[T-HYPER-10] nEnvs=4096 is VALID (C3: no cap; RunConfig §7 canonical vmap value)', () => {
    // C3 fix: removed incorrect 256 cap.
    // 4096 = 2^12 is a power of 2 ≥ 1 → valid per RunConfig.
    // Hand-computed: 4096 = 2^12 ✓; 4096 ≥ 1 ✓; §7 "vmap 4096 envs" is the canonical value.
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, nEnvs: 4096 });
    expect(errors.filter(e => e.field === 'nEnvs')).toHaveLength(0);
  });

  it('[T-HYPER-11] nEnvs = 1 (minimum valid power-of-2)', () => {
    // nEnvs=1 = 2^0 → valid (minimum per RunConfig "power of 2 ≥ 1")
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, nEnvs: 1 });
    expect(errors.filter(e => e.field === 'nEnvs')).toHaveLength(0);
  });

  it('[T-HYPER-12] multiple errors reported simultaneously (gamma NOT included — C2)', () => {
    // Both totalSteps and nEnvs invalid simultaneously
    // totalSteps=50_000 < 100_000 → invalid; nEnvs=15 not a power of 2 → invalid
    // gamma is excluded (it is not a user-editable field)
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, totalSteps: 50_000, nEnvs: 15 });
    expect(errors.length).toBeGreaterThanOrEqual(2);
    const fields = errors.map(e => e.field);
    expect(fields).toContain('totalSteps');
    expect(fields).toContain('nEnvs');
    // gamma must NOT appear as a reported error field
    expect(fields).not.toContain('gamma');
  });

  it('[T-HYPER-13] validation error shown inline; role=alert; confirm button disabled', () => {
    renderStage();
    // Must switch to SAC first (baseline_only is default; hyperparam form absent otherwise)
    switchToSac();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    // Enter learningRate above max (0.1 > 1e-2 = 0.01)
    const lrInput = screen.getByTestId('hyperparam-learningRate');
    fireEvent.change(lrInput, { target: { value: '0.1' } });
    fireEvent.blur(lrInput);

    expect(screen.getByTestId('hyperparam-error-learningRate')).toBeTruthy();
    expect(screen.getByTestId('hyperparam-error-learningRate').getAttribute('role')).toBe('alert');

    const confirmBtn = screen.getByTestId('stage-two-confirm') as HTMLButtonElement;
    expect(confirmBtn.getAttribute('aria-disabled')).toBe('true');
  });

  it('[T-HYPER-14] nEnvs non-power-of-2 hint suggests nearest valid values', () => {
    renderStage();
    switchToSac();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    const nEnvsInput = screen.getByTestId('hyperparam-nEnvs');
    fireEvent.change(nEnvsInput, { target: { value: '15' } });
    fireEvent.blur(nEnvsInput);

    const hint = screen.getByTestId('hyperparam-hint-nEnvs');
    expect(hint).toBeTruthy();
    // Nearest powers of 2: 8 (below 15) and 16 (above 15)
    expect(hint.textContent).toMatch(/8/);
    expect(hint.textContent).toMatch(/16/);
  });

  it('[T-HYPER-15] reset to defaults restores §5-canonical values (lr=1e-4); clears errors', () => {
    renderStage();
    switchToSac();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    // Corrupt learningRate
    const lrInput = screen.getByTestId('hyperparam-learningRate');
    fireEvent.change(lrInput, { target: { value: '99' } });
    fireEvent.blur(lrInput);
    expect(screen.getByTestId('hyperparam-error-learningRate')).toBeTruthy();

    // Reset
    fireEvent.click(screen.getByTestId('hyperparam-reset'));

    // Error cleared; value restored to §5 default: 1e-4 (not 3e-4 — CALL 1)
    expect(screen.queryByTestId('hyperparam-error-learningRate')).toBeNull();
    const restoredLr = (screen.getByTestId('hyperparam-learningRate') as HTMLInputElement).value;
    expect(parseFloat(restoredLr)).toBeCloseTo(1e-4, 6);
  });

  it('[T-HYPER-16] batchSize not power-of-2 (e.g. 300) produces error', () => {
    // 300 is not a power of 2 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: 300 });
    expect(errors.filter(e => e.field === 'batchSize')).toHaveLength(1);
  });

  it('[T-HYPER-17] evalFreq below 1_000 produces error', () => {
    // evalFreq=999 < 1_000 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, evalFreq: 999 });
    expect(errors.filter(e => e.field === 'evalFreq')).toHaveLength(1);
  });

  it('[T-HYPER-18] editing SAC hyperparam while COMPLETE transitions to STALE', async () => {
    makeFetchOk();
    renderStage();
    switchToSac();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    const totalStepsInput = screen.getByTestId('hyperparam-totalSteps');
    fireEvent.change(totalStepsInput, { target: { value: '1000000' } });
    fireEvent.blur(totalStepsInput);

    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-HYPER-19] gamma input absent from DOM even in SAC mode (constant, not user-editable, C2)', () => {
    renderStage();
    switchToSac();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    // gamma is a LOCKED constant; must never render a user-editable input
    expect(screen.queryByTestId('hyperparam-gamma')).toBeNull();
  });

  it('[T-HYPER-20] baseline_only + invalid SAC hyperparams → confirm still enabled (TQ12, §3.7)', () => {
    // §3.7: isConfirmEnabled gates hyperparam errors on algorithmType === 'sac'.
    // A user who set invalid params in SAC mode then switched to baseline_only
    // must still be able to confirm — hyperparams are not sent in baseline_only POSTs.
    renderStage();

    // Set an invalid learningRate while in SAC mode
    switchToSac();
    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }
    const lrInput = screen.getByTestId('hyperparam-learningRate');
    fireEvent.change(lrInput, { target: { value: '999' } });
    fireEvent.blur(lrInput);

    // Confirm disabled in SAC mode (hyperparam error blocks it)
    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('true');

    // Switch back to baseline_only — confirm must re-enable despite stale invalid LR in store
    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('false');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T5 — HyperparamForm collapsed/expanded (SAC mode required)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T5 HyperparamForm collapsed / expanded state', () => {
  it('[T-COLLAPSE-1] header has aria-expanded reflecting expanded state', () => {
    renderStage();
    switchToSac();

    const header = screen.getByTestId('hyperparam-header');
    expect(['true', 'false']).toContain(header.getAttribute('aria-expanded'));
  });

  it('[T-COLLAPSE-2] clicking header toggles expanded/collapsed', () => {
    renderStage();
    switchToSac();

    const header = screen.getByTestId('hyperparam-header');
    const before = header.getAttribute('aria-expanded');

    fireEvent.click(header);

    const after = header.getAttribute('aria-expanded');
    expect(after).not.toBe(before);
  });

  it('[T-COLLAPSE-3] when collapsed, hyperparam inputs absent from DOM', () => {
    renderStage();
    switchToSac();

    const header = screen.getByTestId('hyperparam-header');
    if (header.getAttribute('aria-expanded') === 'true') {
      fireEvent.click(header); // collapse
    }

    expect(screen.queryByTestId('hyperparam-totalSteps')).toBeNull();
    expect(screen.queryByTestId('hyperparam-learningRate')).toBeNull();
  });

  it('[T-COLLAPSE-4] collapsed header summary shows key params', () => {
    renderStage();
    switchToSac();

    const header = screen.getByTestId('hyperparam-header');
    if (header.getAttribute('aria-expanded') === 'true') {
      fireEvent.click(header);
    }
    const text = header.textContent ?? '';
    expect(text.length).toBeGreaterThan(0);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T6 — Baseline selection
// ══════════════════════════════════════════════════════════════════════════════

describe('§T6 Baseline selection', () => {
  it('[T-BASE-1] baselines section has role=group with aria-label', () => {
    renderStage();
    const group = screen.getByRole('group', { name: 'Baseline agents' });
    expect(group).toBeTruthy();
  });

  it('[T-BASE-2] each baseline renders checkbox testid', () => {
    renderStage();
    expect(screen.getByTestId('baseline-checkbox-do_nothing')).toBeTruthy();
    expect(screen.getByTestId('baseline-checkbox-peak_shave')).toBeTruthy();
    expect(screen.getByTestId('baseline-checkbox-import_minimiser')).toBeTruthy();
  });

  it('[T-BASE-3] unchecking all baselines shows baseline-none-error with role=alert', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    expect(screen.getByTestId('baseline-none-error')).toBeTruthy();
    expect(screen.getByTestId('baseline-none-error').getAttribute('role')).toBe('alert');
  });

  it('[T-BASE-4] no-baseline state blocks confirm button (aria-disabled=true)', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('true');
  });

  it('[T-BASE-5] confirm-disabled-reason shows baseline message when no baseline selected', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    const reason = screen.getByTestId('confirm-disabled-reason');
    expect(reason.textContent).toMatch(/baseline/i);
  });

  it('[T-BASE-6] re-checking a baseline clears no-baseline error', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));
    expect(screen.getByTestId('baseline-none-error')).toBeTruthy();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    expect(screen.queryByTestId('baseline-none-error')).toBeNull();
  });

  it('[T-BASE-7] baseline-only mode + no baselines: confirm still disabled', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('true');
  });

  it('[T-BASE-8] toggling baseline while COMPLETE → STALE', async () => {
    makeFetchOk();
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });

    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T7 — Confirm & Continue (happy path)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T7 Confirm & Continue — happy path', () => {
  it('[T-CONFIRM-1] default confirm (baseline_only) fires POST with correct body', async () => {
    makeFetchOk();
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    expect(globalThis.fetch).toHaveBeenCalledOnce();
    const [url, opts] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('/api/training/config');
    expect(opts.method).toBe('POST');

    const body = JSON.parse(opts.body);
    expect(body.algorithm_type).toBe('baseline_only');
    // sac_hyperparams must be absent for baseline_only (field must not exist)
    expect(Object.prototype.hasOwnProperty.call(body, 'sac_hyperparams')).toBe(false);
    expect(body.baselines).toContain('do_nothing');
    expect(body.baselines).toContain('peak_shave');
  });

  it('[T-CONFIRM-2] SAC confirm fires POST with RunConfig canonical field names + all constants (C1, C2)', async () => {
    makeFetchOk();
    renderStage();

    switchToSac();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body,
    );
    expect(body.algorithm_type).toBe('sac');
    expect(body.sac_hyperparams).toBeDefined();

    const h = body.sac_hyperparams;

    // C1: RunConfig canonical field names must be present
    expect(typeof h.total_env_steps).toBe('number');    // NOT total_steps
    expect(typeof h.eval_every_steps).toBe('number');   // NOT eval_freq
    expect(typeof h.batch_size).toBe('number');
    expect(typeof h.lr).toBe('number');                 // NOT learning_rate
    expect(typeof h.buffer_size).toBe('number');
    expect(typeof h.n_envs).toBe('number');

    // C1: old field names must NOT be present
    expect(Object.prototype.hasOwnProperty.call(h, 'total_steps')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(h, 'eval_freq')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(h, 'learning_rate')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(h, 'hidden_layers')).toBe(false);

    // C2: gamma must appear as a LOCKED CONSTANT (not from user input), value 0.999
    expect(h.gamma).toBeCloseTo(0.999, 4);

    // Other constants
    expect(h.tau).toBeCloseTo(0.005, 4);
    expect(h.ent_coef).toBe('auto');
    expect(h.train_freq).toBe(1);
    expect(h.gradient_steps).toBe(1);
    expect(h.hidden_sizes).toEqual([256, 256]);          // NOT hidden_layers
  });

  it('[T-CONFIRM-3] on 200 response: stageState → COMPLETE; onContinue() called', async () => {
    const { onContinue } = renderStage();
    makeFetchOk();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
      expect(onContinue).toHaveBeenCalledOnce();
    });
  });

  it('[T-CONFIRM-4] configId and configHash stored in store after success', async () => {
    makeFetchOk();
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    await waitFor(() => {
      const state = useStageAlgorithmStore.getState();
      expect(state.configId).toBe(MOCK_CONFIG_RESPONSE.config_id);
      expect(state.configHash).toBe(MOCK_CONFIG_RESPONSE.config_hash);
    });
  });

  it('[T-CONFIRM-5] button shows "Saving… ⟳" while POST in flight', async () => {
    let resolvePost: (v: Response) => void;
    globalThis.fetch = vi.fn(
      () =>
        new Promise<Response>(res => {
          resolvePost = res;
        }),
    );
    renderStage();

    act(() => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    await waitFor(() => {
      const btn = screen.getByTestId('stage-two-confirm');
      expect(btn.textContent).toMatch(/Saving/);
    });

    resolvePost!({
      ok: true,
      status: 200,
      json: () => Promise.resolve(MOCK_CONFIG_RESPONSE),
    } as Response);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T8 — Confirm unhappy path (API error + Retry)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T8 Confirm & Continue — API error + Retry', () => {
  it('[T-API-ERR-1] POST 500 → confirm-api-error shown; stageState not COMPLETE', async () => {
    makeFetchFail(500, { error: 'Internal server error' });
    const { onContinue } = renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('confirm-api-error')).toBeTruthy();
    });
    expect(useStageAlgorithmStore.getState().stageState).not.toBe('COMPLETE');
    expect(onContinue).not.toHaveBeenCalled();
  });

  it('[T-API-ERR-2] confirm-retry button present after API error', async () => {
    makeFetchFail();
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('confirm-retry')).toBeTruthy();
    });
  });

  it('[T-API-ERR-3] clicking Retry after failure re-fires POST; success clears error', async () => {
    let calls = 0;
    globalThis.fetch = vi.fn(() => {
      calls++;
      if (calls === 1) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(MOCK_CONFIG_RESPONSE),
      } as Response);
    });

    const { onContinue } = renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('confirm-retry')).toBeTruthy();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('confirm-retry'));
    });
    await waitFor(() => {
      expect(screen.queryByTestId('confirm-api-error')).toBeNull();
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
      expect(onContinue).toHaveBeenCalledOnce();
    });
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  it('[T-API-ERR-4] POST 422 (validation error) → error shown; stageState not COMPLETE', async () => {
    makeFetchFail(422, { error: 'Invalid config', field: 'total_env_steps', message: 'Too low' });
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    await waitFor(() => {
      expect(screen.getByTestId('confirm-api-error')).toBeTruthy();
    });
    expect(useStageAlgorithmStore.getState().stageState).not.toBe('COMPLETE');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T9 — Back button
// ══════════════════════════════════════════════════════════════════════════════

describe('§T9 Back button', () => {
  it('[T-BACK-1] back button is a <span>, not <button>', () => {
    renderStage();
    const back = screen.getByTestId('stage-two-back');
    expect(back.tagName.toLowerCase()).toBe('span');
  });

  it('[T-BACK-2] clicking back calls onBack(); store state preserved', () => {
    const { onBack } = renderStage();

    switchToSac();
    fireEvent.click(screen.getByTestId('stage-two-back'));

    expect(onBack).toHaveBeenCalledOnce();
    expect(useStageAlgorithmStore.getState().algorithmType).toBe('sac');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T10 — STALE state transitions (Class A edit rule D32 §c)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T10 STALE state transitions (Class A edit rule)', () => {
  async function reachCompleteBaseline() {
    makeFetchOk();
    const result = renderStage();
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });
    return result;
  }

  async function reachCompleteSac() {
    makeFetchOk();
    const result = renderStage();
    switchToSac();
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });
    return result;
  }

  it('[T-STALE-1] COMPLETE (baseline_only) → STALE on switching to SAC', async () => {
    await reachCompleteBaseline();
    switchToSac();
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-2] COMPLETE → STALE on baseline toggle', async () => {
    await reachCompleteBaseline();
    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-3] COMPLETE (SAC) → STALE on hyperparam field change', async () => {
    await reachCompleteSac();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    const totalStepsInput = screen.getByTestId('hyperparam-totalSteps');
    fireEvent.change(totalStepsInput, { target: { value: '1000000' } });
    fireEvent.blur(totalStepsInput);

    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-4] STALE → COMPLETE after a new successful confirm', async () => {
    await reachCompleteBaseline();

    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');

    makeFetchOk();
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T11 — Store persistence (partialize / rehydrate)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T11 Store persistence and rehydration', () => {
  it('[T-PERSIST-1] saveInProgress not persisted (always false after reset)', () => {
    const state = useStageAlgorithmStore.getState();
    state.setSaveInProgress(true);
    expect(useStageAlgorithmStore.getState().saveInProgress).toBe(true);

    state.reset();
    expect(useStageAlgorithmStore.getState().saveInProgress).toBe(false);
  });

  it('[T-PERSIST-2] saveError not persisted (always null after reset)', () => {
    const state = useStageAlgorithmStore.getState();
    state.setSaveError('Something went wrong');
    state.reset();
    expect(useStageAlgorithmStore.getState().saveError).toBeNull();
  });

  it('[T-PERSIST-3] onRehydrateStorage: COMPLETE → IN_PROGRESS via the real persist callback', () => {
    // Exercises the actual Zustand persist `onRehydrateStorage` hook, not a manual setState.
    // The store must expose an `onRehydrate(state)` method that the middleware calls on hydration.
    // Calling it with stageState='COMPLETE' must downgrade to 'IN_PROGRESS' — forces re-confirm
    // on page reload so the persisted config_hash must match the current Stage ① config.
    const store = useStageAlgorithmStore;
    const hydratedState = { ...store.getState(), stageState: 'COMPLETE' as const };
    store.getState().onRehydrate(hydratedState);
    expect(store.getState().stageState).toBe('IN_PROGRESS');
  });

  it('[T-PERSIST-4] reset() returns all persisted state to initial values (CALL 2: default baseline_only)', () => {
    const store = useStageAlgorithmStore.getState();
    store.setAlgorithmType('sac');
    store.toggleBaseline('do_nothing');

    store.reset();

    const state = useStageAlgorithmStore.getState();
    // CALL 2: default is baseline_only
    expect(state.algorithmType).toBe('baseline_only');
    expect(state.selectedBaselines).toContain('do_nothing');
    expect(state.selectedBaselines).toContain('peak_shave');
    expect(state.stageState).toBe('PENDING');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T12 — Accessibility
// ══════════════════════════════════════════════════════════════════════════════

describe('§T12 Accessibility', () => {
  it('[T-A11Y-1] algorithm radiogroup has aria-label', () => {
    renderStage();
    expect(screen.getByRole('radiogroup', { name: 'Training algorithm' })).toBeTruthy();
  });

  it('[T-A11Y-2] each algorithm card has role=radio', () => {
    renderStage();
    expect(screen.getByTestId('algo-card-sac').getAttribute('role')).toBe('radio');
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('role')).toBe('radio');
  });

  it('[T-A11Y-3] baseline group has role=group with aria-label', () => {
    renderStage();
    expect(screen.getByRole('group', { name: 'Baseline agents' })).toBeTruthy();
  });

  it('[T-A11Y-4] back button is not a <button> (span, DV-1 precedent)', () => {
    renderStage();
    const back = screen.getByTestId('stage-two-back');
    expect(back.tagName.toLowerCase()).toBe('span');
  });

  it('[T-A11Y-5] confirm button uses aria-disabled, not HTML disabled attr', () => {
    renderStage();
    const btn = screen.getByTestId('stage-two-confirm') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    expect(btn.getAttribute('aria-disabled')).toMatch(/^(true|false)$/);
  });

  it('[T-A11Y-6] hyperparam inputs have aria-describedby pointing to range hint (SAC mode)', () => {
    renderStage();
    switchToSac();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    const lrInput = screen.getByTestId('hyperparam-learningRate');
    const describedBy = lrInput.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy!)).toBeTruthy();
  });

  it('[T-A11Y-7] hyperparam section header has aria-expanded (SAC mode)', () => {
    renderStage();
    switchToSac();

    const header = screen.getByTestId('hyperparam-header');
    expect(['true', 'false']).toContain(header.getAttribute('aria-expanded'));
  });

  it('[T-A11Y-8] LOCKED stage: no interactive elements in DOM for screen reader', () => {
    renderStage({ stageOneComplete: false });

    expect(screen.queryAllByRole('radio')).toHaveLength(0);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryAllByRole('textbox')).toHaveLength(0);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T13 — POST body schema (contract golden-example validation, all amendments)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T13 POST body schema (contract golden-example validation)', () => {
  it('[T-BODY-1] baseline_only body matches contract §3.8 golden example (CALL 2 default)', async () => {
    makeFetchOk();
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body,
    );

    expect(body.algorithm_type).toBe('baseline_only');
    // sac_hyperparams must be absent (field must not exist — not just null)
    expect(Object.prototype.hasOwnProperty.call(body, 'sac_hyperparams')).toBe(false);
    expect(Array.isArray(body.baselines)).toBe(true);
    expect(body.baselines.length).toBeGreaterThanOrEqual(1);
    expect(body.baselines).toContain('do_nothing');
    expect(body.baselines).toContain('peak_shave');
  });

  it('[T-BODY-2] SAC body matches §3.8 golden — RunConfig names + CALL 1 values + C2 gamma constant', async () => {
    makeFetchOk();
    renderStage();
    switchToSac();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body,
    );

    expect(body.algorithm_type).toBe('sac');
    expect(typeof body.sac_hyperparams).toBe('object');

    const h = body.sac_hyperparams;

    // C1 fix: RunConfig canonical field names (training_pipeline.md §3)
    // 6 user-editable fields:
    expect(typeof h.total_env_steps).toBe('number');    // NOT total_steps
    expect(typeof h.eval_every_steps).toBe('number');   // NOT eval_freq
    expect(typeof h.batch_size).toBe('number');
    expect(typeof h.lr).toBe('number');                 // NOT learning_rate
    expect(typeof h.buffer_size).toBe('number');
    expect(typeof h.n_envs).toBe('number');
    // 6 constants (RunConfig canonical names):
    expect(typeof h.gamma).toBe('number');              // C2: LOCKED constant
    expect(typeof h.tau).toBe('number');
    expect(typeof h.ent_coef).toBe('string');
    expect(typeof h.train_freq).toBe('number');
    expect(typeof h.gradient_steps).toBe('number');
    expect(Array.isArray(h.hidden_sizes)).toBe(true);  // NOT hidden_layers

    // C1: old field names must NOT be present
    expect(Object.prototype.hasOwnProperty.call(h, 'total_steps')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(h, 'eval_freq')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(h, 'learning_rate')).toBe(false);
    expect(Object.prototype.hasOwnProperty.call(h, 'hidden_layers')).toBe(false);

    // Golden example values (CALL 1 + Round 2 amendments):
    // total_env_steps=500_000 (§5); eval_every_steps=10_000 (RunConfig default);
    // batch_size=512 (§5); lr≈1e-4 (§5); buffer_size=1_000_000 (§5); n_envs=4 (CALL 1 DummyVecEnv)
    // gamma=0.999 (LOCKED constant — C2); tau=0.005; ent_coef="auto"; train_freq=1; gradient_steps=1
    // hidden_sizes=[256,256]
    expect(h.total_env_steps).toBe(500_000);
    expect(h.eval_every_steps).toBe(10_000);
    expect(h.batch_size).toBe(512);
    expect(h.lr).toBeCloseTo(1e-4, 6);
    expect(h.buffer_size).toBe(1_000_000);
    expect(h.n_envs).toBe(4);
    expect(h.gamma).toBeCloseTo(0.999, 4);
    expect(h.tau).toBeCloseTo(0.005, 4);
    expect(h.ent_coef).toBe('auto');
    expect(h.train_freq).toBe(1);
    expect(h.gradient_steps).toBe(1);
    expect(h.hidden_sizes).toEqual([256, 256]);

    expect(Array.isArray(body.baselines)).toBe(true);
    expect(body.baselines.length).toBeGreaterThanOrEqual(1);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T14 — lockStage / unlockStage (Stage ① → Stage ② propagation)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T14 lockStage / unlockStage propagation', () => {
  it('[T-LOCK-PROP-1] lockStage() transitions any state → LOCKED', () => {
    useStageAlgorithmStore.getState().unlockStage();
    expect(useStageAlgorithmStore.getState().stageState).not.toBe('LOCKED');

    useStageAlgorithmStore.getState().lockStage();
    expect(useStageAlgorithmStore.getState().stageState).toBe('LOCKED');
  });

  it('[T-LOCK-PROP-2] unlockStage() from LOCKED → PENDING', () => {
    useStageAlgorithmStore.getState().lockStage();
    useStageAlgorithmStore.getState().unlockStage();
    expect(useStageAlgorithmStore.getState().stageState).toBe('PENDING');
  });

  it('[T-LOCK-PROP-3] component re-renders to LOCKED when stageOneComplete changes to false', async () => {
    const { rerender } = render(
      <StageTwoAlgorithm
        stageOneComplete={true}
        onBack={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    expect(screen.getByTestId('stage-two-content')).toBeTruthy();

    rerender(
      <StageTwoAlgorithm
        stageOneComplete={false}
        onBack={vi.fn()}
        onContinue={vi.fn()}
      />,
    );
    expect(screen.getByTestId('stage-two-locked')).toBeTruthy();
    expect(screen.queryByTestId('stage-two-content')).toBeNull();
  });

  it('[T-LOCK-PROP-4] false → true → false stageOneComplete cycle: content visible after re-enable', () => {
    // Verifies the LOCKED flip false→true→false cycle (TQ13 reviewer requirement)
    const { rerender } = render(
      <StageTwoAlgorithm stageOneComplete={true} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-content')).toBeTruthy();

    rerender(
      <StageTwoAlgorithm stageOneComplete={false} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-locked')).toBeTruthy();

    // Re-enable Stage ①: Stage ② content must be accessible again (not stuck LOCKED)
    rerender(
      <StageTwoAlgorithm stageOneComplete={true} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-content')).toBeTruthy();
    expect(screen.queryByTestId('stage-two-locked')).toBeNull();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T15 — reviewer adversarial additions (frontend-reviewer, PR #115 gate Round 2)
// reviewer: required test additions TQ1–TQ11 from contracts/reviews/stage_algorithm.md.
// Added now that C1 (RunConfig field names), C2 (gamma constant), C3 (nEnvs range)
// are settled. Boundaries assert hand-computed expected values; the POST-body cases
// guard against field-name swaps/leakage; the UI cases pin §4.6/§5.2/§3.7/DV-2 behavior.
// ══════════════════════════════════════════════════════════════════════════════

describe('reviewer: §T15 adversarial additions (TQ1–TQ11)', () => {
  // ── TQ1 — POST body has the EXACT key set; no camelCase leakage ──
  it('reviewer: [T-BODY-3] SAC sac_hyperparams has exactly the 12 RunConfig keys; no camelCase leakage', async () => {
    // reviewer: T-CONFIRM-2/T-BODY-2 assert RunConfig names present + 4 old snake_case names
    // absent, but neither pins the EXACT key set nor rules out camelCase store keys leaking
    // (e.g. the raw store object being JSON.stringify'd). A serialized store would carry
    // totalSteps/learningRate/etc. and still pass those tests. Pin the exact contract §3.8 set.
    makeFetchOk();
    renderStage();
    switchToSac();
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body,
    );
    const keys = Object.keys(body.sac_hyperparams).sort();
    // Contract §3.8: 6 user-editable + 6 constants (all RunConfig canonical names).
    const expected = [
      'batch_size', 'buffer_size', 'ent_coef', 'eval_every_steps', 'gamma',
      'gradient_steps', 'hidden_sizes', 'lr', 'n_envs', 'tau',
      'total_env_steps', 'train_freq',
    ].sort();
    expect(keys).toEqual(expected);
    // No camelCase store keys may leak into the wire body:
    for (const leak of ['totalSteps', 'evalFreq', 'learningRate', 'bufferSize', 'nEnvs', 'hiddenSizes', 'hiddenLayers']) {
      expect(Object.prototype.hasOwnProperty.call(body.sac_hyperparams, leak)).toBe(false);
    }
  });

  // ── TQ2 — batchSize range boundaries (power of 2 AND 32–4096) ──
  it('reviewer: [T-HYPER-21] batchSize=16 is INVALID (power-of-2 but < 32)', () => {
    // reviewer: 16 = 2^4 is a power of 2 but below the 32 minimum (contract §3.2) → error.
    // Catches an impl that checks power-of-2 but omits the lower bound.
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: 16 });
    expect(errors.filter(e => e.field === 'batchSize')).toHaveLength(1);
  });
  it('reviewer: [T-HYPER-22] batchSize=32 is VALID (exact min, 2^5)', () => {
    // reviewer: 32 = 2^5, exact lower bound → valid (off-by-one guard: >= not >).
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: 32 });
    expect(errors.filter(e => e.field === 'batchSize')).toHaveLength(0);
  });
  it('reviewer: [T-HYPER-23] batchSize=4096 is VALID (exact max, 2^12)', () => {
    // reviewer: 4096 = 2^12, exact upper bound → valid. bufferSize default 1e6 ≥ 4096×4=16384 ✓.
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: 4096 });
    expect(errors.filter(e => e.field === 'batchSize')).toHaveLength(0);
  });
  it('reviewer: [T-HYPER-24] batchSize=8192 is INVALID (power-of-2 but > 4096)', () => {
    // reviewer: 8192 = 2^13 is a power of 2 but above the 4096 max → error.
    // Catches an impl that checks power-of-2 but omits the upper bound.
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: 8192 });
    expect(errors.filter(e => e.field === 'batchSize')).toHaveLength(1);
  });

  // ── TQ3/TQ4/TQ6 — exact inclusive bounds (off-by-one guards) ──
  it('reviewer: [T-HYPER-25] evalFreq=1000 is VALID (exact min ≥ 1_000)', () => {
    // reviewer: only 999 (invalid) was tested; pin the inclusive boundary (>= not >).
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, evalFreq: 1000 });
    expect(errors.filter(e => e.field === 'evalFreq')).toHaveLength(0);
  });
  it('reviewer: [T-HYPER-26] totalSteps=100_000 is VALID (exact min ≥ 100_000)', () => {
    // reviewer: only 99_999 (invalid) was tested; pin the inclusive boundary.
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, totalSteps: 100_000 });
    expect(errors.filter(e => e.field === 'totalSteps')).toHaveLength(0);
  });
  it('reviewer: [T-HYPER-27] learningRate=1e-5 and 1e-2 are VALID (inclusive bounds)', () => {
    // reviewer: contract §3.2 is "1e-5 ≤ lr ≤ 1e-2" (inclusive); only 5e-6/0.02 (outside) were tested.
    expect(getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, learningRate: 1e-5 })
      .filter(e => e.field === 'learningRate')).toHaveLength(0);
    expect(getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, learningRate: 1e-2 })
      .filter(e => e.field === 'learningRate')).toHaveLength(0);
  });

  // ── TQ7 — NaN/parse must be caught (prevents NaN→null in the POST body) ──
  it('reviewer: [T-HYPER-28] getHyperparamErrors flags NaN as an error (not silently valid)', () => {
    // reviewer: §5.2 "Must be a number". If NaN reaches getHyperparamErrors it MUST produce an
    // error, else NaN serializes to null in the POST body — a silent data-corruption path.
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: NaN });
    expect(errors.filter(e => e.field === 'batchSize').length).toBeGreaterThanOrEqual(1);
  });
  it('reviewer: [T-HYPER-29] non-numeric SAC input shows parse error and disables confirm', () => {
    // reviewer: §5.2 — non-numeric/empty blur shows the field error and blocks confirm.
    renderStage();
    switchToSac();
    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') fireEvent.click(header);
    const batchInput = screen.getByTestId('hyperparam-batchSize');
    fireEvent.change(batchInput, { target: { value: 'abc' } });
    fireEvent.blur(batchInput);
    expect(screen.getByTestId('hyperparam-error-batchSize')).toBeTruthy();
    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('true');
  });

  // ── TQ8 — cross-field bufferSize uses the CURRENT batchSize, not a hardcoded 1024/2048 ──
  it('reviewer: [T-HYPER-30] bufferSize cross-field tracks a CHANGED batchSize', () => {
    // reviewer: existing T-HYPER-7/8 only use the default batchSize=512 (boundary 2048), so an
    // impl hardcoding "bufferSize ≥ 2048" would pass. With batchSize=1024 the minimum is
    // 1024×4=4096: 4095 must fail, 4096 must pass. (1024=2^10 ∈ [32,4096] ✓.)
    const invalid = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: 1024, bufferSize: 4095 });
    expect(invalid.filter(e => e.field === 'bufferSize')).toHaveLength(1);
    const valid = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, batchSize: 1024, bufferSize: 4096 });
    expect(valid.filter(e => e.field === 'bufferSize')).toHaveLength(0);
  });

  // ── TQ9 — aria-disabled is honored: a disabled confirm must NOT fire the POST (DV-2) ──
  it('reviewer: [T-CONFIRM-6] clicking confirm while aria-disabled does NOT fire POST nor change state', () => {
    // reviewer: DV-2 uses aria-disabled (not HTML disabled), so the handler MUST intercept the
    // click itself. Deselect all baselines → aria-disabled=true → a click must be a no-op.
    makeFetchOk();
    renderStage();
    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));
    const confirm = screen.getByTestId('stage-two-confirm');
    expect(confirm.getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(confirm);
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(useStageAlgorithmStore.getState().stageState).not.toBe('COMPLETE');
  });

  // ── TQ10 — double-submit guard: a second click while saving must not fire a second POST ──
  it('reviewer: [T-CONFIRM-7] second confirm click while saveInProgress does not fire a 2nd POST', async () => {
    // reviewer: a double-click must not create two training configs. While the first POST is in
    // flight (saveInProgress), the button is aria-disabled (§4.6) and must swallow further clicks.
    let resolvePost: (v: Response) => void;
    globalThis.fetch = vi.fn(
      () => new Promise<Response>(res => { resolvePost = res; }),
    );
    renderStage();  // baseline_only default → confirm enabled
    act(() => { fireEvent.click(screen.getByTestId('stage-two-confirm')); });
    await waitFor(() => {
      expect(screen.getByTestId('stage-two-confirm').textContent).toMatch(/Saving/);
    });
    // Second click while the first POST is pending:
    act(() => { fireEvent.click(screen.getByTestId('stage-two-confirm')); });
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
    resolvePost!({ ok: true, status: 200, json: () => Promise.resolve(MOCK_CONFIG_RESPONSE) } as Response);
  });

  // ── TQ11 — confirm-disabled-reason priority (§4.6) ──
  it('reviewer: [T-REASON-1] hyperparam error (SAC) + baselines OK → reason = "Fix hyperparameter errors"', () => {
    // reviewer: §4.6 — when baselines are selected but a hyperparam is invalid, the reason text
    // is the hyperparam message (only the baseline message was tested previously).
    renderStage();
    switchToSac();  // baselines do_nothing+peak_shave still selected
    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') fireEvent.click(header);
    const lrInput = screen.getByTestId('hyperparam-learningRate');
    fireEvent.change(lrInput, { target: { value: '999' } });
    fireEvent.blur(lrInput);
    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByTestId('confirm-disabled-reason').textContent).toMatch(/hyperparam/i);
  });
  it('reviewer: [T-REASON-2] no baseline + hyperparam error → baseline message takes priority (§4.6)', () => {
    // reviewer: §4.6 "(both conditions: baseline message takes priority)".
    renderStage();
    switchToSac();
    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') fireEvent.click(header);
    const lrInput = screen.getByTestId('hyperparam-learningRate');
    fireEvent.change(lrInput, { target: { value: '999' } });
    fireEvent.blur(lrInput);
    // Now also deselect every baseline → both failure conditions hold:
    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));
    expect(screen.getByTestId('confirm-disabled-reason').textContent).toMatch(/baseline/i);
  });
});
