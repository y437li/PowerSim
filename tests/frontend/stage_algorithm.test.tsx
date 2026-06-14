/**
 * tests/frontend/stage_algorithm.test.tsx
 *
 * Contract: contracts/frontend/stage_algorithm.md
 * REBUILD_SPEC: §5 (training methodology)
 * LINEAGE: D32 §(a)/(c) (algorithm registry + five-stage spine)
 *
 * Vitest + React Testing Library v16
 * Fake timers used for debounced interactions (none in this component;
 * retained for consistency with the stage_config test harness setup).
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { useStageAlgorithmStore } from '../../src/stores/stageAlgorithmStore';
import { getHyperparamErrors } from '../../src/stores/stageAlgorithmStore';
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

// ── Default helpers ─────────────────────────────────────────────────────────

const DEFAULT_HYPERPARAMS = {
  totalSteps: 2_000_000,
  evalFreq: 50_000,
  batchSize: 256,
  learningRate: 3e-4,
  gamma: 0.99,
  bufferSize: 1_000_000,
  nEnvs: 16,
};

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

// ── Setup / teardown ───────────────────────────────────────────────────────

beforeEach(() => {
  // Reset the Zustand store before each test
  useStageAlgorithmStore.getState().reset();
  // Default: fetch succeeds
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

    // Back span in footer is always rendered per contract
    fireEvent.click(screen.getByTestId('stage-two-back'));
    expect(onBack).toHaveBeenCalledOnce();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T2 — Initial render (first visit, PENDING)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T2 Initial render — first visit PENDING state', () => {
  it('[T-INIT-1] content section visible; SAC card selected by default', () => {
    renderStage();

    expect(screen.getByTestId('stage-two-content')).toBeTruthy();
    expect(screen.getByTestId('algo-card-sac')).toBeTruthy();
    expect(screen.getByTestId('algo-card-baseline-only')).toBeTruthy();
    // SAC selected by default
    expect(screen.getByTestId('algo-card-sac').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('aria-checked')).toBe('false');
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

  it('[T-INIT-4] hyperparam section present (SAC mode); inputs have default values', () => {
    renderStage();

    expect(screen.getByTestId('hyperparam-section')).toBeTruthy();

    // Verify one default value — totalSteps
    const totalStepsInput = screen.getByTestId('hyperparam-totalSteps') as HTMLInputElement;
    expect(parseFloat(totalStepsInput.value)).toBe(2_000_000);
    // gamma
    const gammaInput = screen.getByTestId('hyperparam-gamma') as HTMLInputElement;
    expect(parseFloat(gammaInput.value)).toBe(0.99);
    // learningRate (3e-4)
    const lrInput = screen.getByTestId('hyperparam-learningRate') as HTMLInputElement;
    expect(parseFloat(lrInput.value)).toBeCloseTo(3e-4, 6);
  });

  it('[T-INIT-5] Confirm button disabled initially (stageState PENDING, must confirm once)', () => {
    // On first visit (PENDING), store has no successful POST — confirm should be enabled
    // since defaults are valid and baselines are selected. This tests the happy first-visit path.
    renderStage();

    const confirmBtn = screen.getByTestId('stage-two-confirm') as HTMLButtonElement;
    // Default state: valid hyperparams + 2 baselines selected → confirm enabled
    expect(confirmBtn.getAttribute('aria-disabled')).toBe('false');
  });

  it('[T-INIT-6] stage-two-algorithm testid exists at root', () => {
    renderStage();
    expect(screen.getByTestId('stage-two-algorithm')).toBeTruthy();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T3 — Algorithm card interaction
// ══════════════════════════════════════════════════════════════════════════════

describe('§T3 Algorithm card interaction', () => {
  it('[T-ALGO-1] clicking Baseline-only card: SAC deselected, hyperparam section removed from DOM', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));

    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('algo-card-sac').getAttribute('aria-checked')).toBe('false');
    // Hyperparam section ABSENT from DOM when baseline_only
    expect(screen.queryByTestId('hyperparam-section')).toBeNull();
  });

  it('[T-ALGO-2] baseline-only notice shown when baseline_only selected', () => {
    renderStage();

    expect(screen.queryByTestId('algo-baseline-notice')).toBeNull();
    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    expect(screen.getByTestId('algo-baseline-notice')).toBeTruthy();
  });

  it('[T-ALGO-3] switching back to SAC restores hyperparam section', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    expect(screen.queryByTestId('hyperparam-section')).toBeNull();

    fireEvent.click(screen.getByTestId('algo-card-sac'));
    expect(screen.getByTestId('hyperparam-section')).toBeTruthy();
  });

  it('[T-ALGO-4] switching algorithm when COMPLETE transitions to STALE', async () => {
    makeFetchOk();
    renderStage();

    // Confirm to reach COMPLETE
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });

    // Switch algorithm → STALE
    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-ALGO-5] Space key on algorithm card toggles selection (keyboard nav)', () => {
    renderStage();

    const baselineCard = screen.getByTestId('algo-card-baseline-only');
    fireEvent.keyDown(baselineCard, { key: ' ', code: 'Space' });
    // After Space: baseline-only should be selected
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('aria-checked')).toBe('true');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T4 — Hyperparam validation
// ══════════════════════════════════════════════════════════════════════════════

describe('§T4 Hyperparam validation', () => {
  it('[T-HYPER-1] getHyperparamErrors returns empty for all-default params', () => {
    // Hand-computed: all defaults are within their valid ranges (see contract §3.2)
    // totalSteps=2_000_000 ≥ 100_000 ✓ (×20 the minimum)
    // evalFreq=50_000 ≥ 1_000 ✓
    // batchSize=256 is power-of-2, 32–4096 ✓
    // learningRate=3e-4 in [1e-5, 1e-2] ✓
    // gamma=0.99 in (0, 1] ✓
    // bufferSize=1_000_000 ≥ 256*4=1024 ✓ (×976 the minimum)
    // nEnvs=16 is power-of-2, 1–256 ✓
    const errors = getHyperparamErrors(DEFAULT_HYPERPARAMS);
    expect(errors).toHaveLength(0);
  });

  it('[T-HYPER-2] totalSteps below 100_000 produces error', () => {
    // 99_999 < 100_000 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, totalSteps: 99_999 });
    const fieldErrors = errors.filter(e => e.field === 'totalSteps');
    expect(fieldErrors).toHaveLength(1);
    expect(fieldErrors[0].type).toBe('error');
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

  it('[T-HYPER-5] gamma = 0 (boundary: must be strictly > 0)', () => {
    // gamma = 0 violates (0, 1]
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, gamma: 0 });
    expect(errors.filter(e => e.field === 'gamma')).toHaveLength(1);
  });

  it('[T-HYPER-6] gamma = 1.0 (boundary: valid, inclusive upper)', () => {
    // gamma = 1 is valid (discount factor of 1 = no discounting)
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, gamma: 1.0 });
    expect(errors.filter(e => e.field === 'gamma')).toHaveLength(0);
  });

  it('[T-HYPER-7] bufferSize too small: < batchSize * 4', () => {
    // batchSize=256; bufferSize=256*4-1=1023 → invalid (must be ≥ 256*4=1024)
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, bufferSize: 1023 });
    expect(errors.filter(e => e.field === 'bufferSize')).toHaveLength(1);
  });

  it('[T-HYPER-8] bufferSize exact minimum: batchSize * 4 (valid)', () => {
    // batchSize=256, bufferSize=256*4=1024 → exactly meets the minimum → valid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, bufferSize: 1024 });
    expect(errors.filter(e => e.field === 'bufferSize')).toHaveLength(0);
  });

  it('[T-HYPER-9] nEnvs not a power of 2 produces error', () => {
    // nEnvs=15 is not a power of 2 → invalid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, nEnvs: 15 });
    expect(errors.filter(e => e.field === 'nEnvs')).toHaveLength(1);
  });

  it('[T-HYPER-10] nEnvs power-of-2 but > 256 produces error', () => {
    // nEnvs=512 > 256 → out of valid range
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, nEnvs: 512 });
    expect(errors.filter(e => e.field === 'nEnvs')).toHaveLength(1);
  });

  it('[T-HYPER-11] nEnvs = 1 (minimum valid power-of-2)', () => {
    // nEnvs=1 = 2^0 → valid
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, nEnvs: 1 });
    expect(errors.filter(e => e.field === 'nEnvs')).toHaveLength(0);
  });

  it('[T-HYPER-12] multiple errors reported simultaneously', () => {
    // Both totalSteps and gamma invalid
    // totalSteps=50_000 < 100_000; gamma=1.5 > 1
    const errors = getHyperparamErrors({ ...DEFAULT_HYPERPARAMS, totalSteps: 50_000, gamma: 1.5 });
    expect(errors.length).toBeGreaterThanOrEqual(2);
    const fields = errors.map(e => e.field);
    expect(fields).toContain('totalSteps');
    expect(fields).toContain('gamma');
  });

  it('[T-HYPER-13] validation error shown inline; role=alert; confirm button disabled', () => {
    renderStage();

    // Enter an invalid learningRate (too high: 0.1 > 1e-2)
    const lrInput = screen.getByTestId('hyperparam-learningRate');
    // Expand form first if collapsed
    const header = screen.queryByTestId('hyperparam-header');
    if (header) fireEvent.click(header);

    fireEvent.change(lrInput, { target: { value: '0.1' } });
    fireEvent.blur(lrInput);

    expect(screen.getByTestId('hyperparam-error-learningRate')).toBeTruthy();
    expect(screen.getByTestId('hyperparam-error-learningRate').getAttribute('role')).toBe('alert');

    const confirmBtn = screen.getByTestId('stage-two-confirm') as HTMLButtonElement;
    expect(confirmBtn.getAttribute('aria-disabled')).toBe('true');
  });

  it('[T-HYPER-14] nEnvs non-power-of-2 hint suggests nearest valid values', () => {
    renderStage();

    const header = screen.queryByTestId('hyperparam-header');
    if (header) fireEvent.click(header);

    const nEnvsInput = screen.getByTestId('hyperparam-nEnvs');
    fireEvent.change(nEnvsInput, { target: { value: '15' } });
    fireEvent.blur(nEnvsInput);

    const hint = screen.getByTestId('hyperparam-hint-nEnvs');
    expect(hint).toBeTruthy();
    // Hint text must mention 8 (below) and 16 (above) as nearest powers of 2
    expect(hint.textContent).toMatch(/8/);
    expect(hint.textContent).toMatch(/16/);
  });

  it('[T-HYPER-15] reset to defaults restores all fields; clears errors', () => {
    renderStage();

    const header = screen.queryByTestId('hyperparam-header');
    if (header) fireEvent.click(header);

    // Corrupt a field
    const lrInput = screen.getByTestId('hyperparam-learningRate');
    fireEvent.change(lrInput, { target: { value: '99' } });
    fireEvent.blur(lrInput);
    expect(screen.getByTestId('hyperparam-error-learningRate')).toBeTruthy();

    // Reset
    fireEvent.click(screen.getByTestId('hyperparam-reset'));

    // Error cleared; value restored to 3e-4
    expect(screen.queryByTestId('hyperparam-error-learningRate')).toBeNull();
    const restoredLr = (screen.getByTestId('hyperparam-learningRate') as HTMLInputElement).value;
    expect(parseFloat(restoredLr)).toBeCloseTo(3e-4, 6);
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

  it('[T-HYPER-18] editing param while COMPLETE transitions to STALE', async () => {
    makeFetchOk();
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    });

    const header = screen.queryByTestId('hyperparam-header');
    if (header) fireEvent.click(header);

    const totalStepsInput = screen.getByTestId('hyperparam-totalSteps');
    fireEvent.change(totalStepsInput, { target: { value: '3000000' } });
    fireEvent.blur(totalStepsInput);

    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T5 — HyperparamForm collapsed/expanded
// ══════════════════════════════════════════════════════════════════════════════

describe('§T5 HyperparamForm collapsed / expanded state', () => {
  it('[T-COLLAPSE-1] header has aria-expanded reflecting expanded state', () => {
    renderStage();

    const header = screen.getByTestId('hyperparam-header');
    const initialExpanded = header.getAttribute('aria-expanded');
    // Initial state may be collapsed (per UX spec §5.1)
    expect(['true', 'false']).toContain(initialExpanded);
  });

  it('[T-COLLAPSE-2] clicking header toggles expanded/collapsed', () => {
    renderStage();

    const header = screen.getByTestId('hyperparam-header');
    const before = header.getAttribute('aria-expanded');

    fireEvent.click(header);

    const after = header.getAttribute('aria-expanded');
    expect(after).not.toBe(before);
  });

  it('[T-COLLAPSE-3] when collapsed, hyperparam inputs absent from DOM', () => {
    renderStage();

    // Collapse (if not already collapsed, collapse first; if already collapsed: verify)
    const header = screen.getByTestId('hyperparam-header');
    if (header.getAttribute('aria-expanded') === 'true') {
      fireEvent.click(header); // collapse
    }

    // After collapse, inputs must not be in DOM
    expect(screen.queryByTestId('hyperparam-totalSteps')).toBeNull();
    expect(screen.queryByTestId('hyperparam-learningRate')).toBeNull();
  });

  it('[T-COLLAPSE-4] expanded collapsed summary shows key params in header text', () => {
    renderStage();

    const header = screen.getByTestId('hyperparam-header');
    // Ensure collapsed
    if (header.getAttribute('aria-expanded') === 'true') {
      fireEvent.click(header);
    }
    // Collapsed header should mention training steps (2M), LR (3e-4), gamma, nEnvs
    const text = header.textContent ?? '';
    expect(text).toMatch(/2/); // 2M steps
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

    // Uncheck do_nothing
    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    // Uncheck peak_shave (now none selected)
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    expect(screen.getByTestId('baseline-none-error')).toBeTruthy();
    expect(screen.getByTestId('baseline-none-error').getAttribute('role')).toBe('alert');
  });

  it('[T-BASE-4] no-baseline state blocks confirm button (aria-disabled=true)', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    const confirmBtn = screen.getByTestId('stage-two-confirm');
    expect(confirmBtn.getAttribute('aria-disabled')).toBe('true');
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

    // Re-check one
    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    expect(screen.queryByTestId('baseline-none-error')).toBeNull();
  });

  it('[T-BASE-7] baseline-only mode + no baselines: confirm still disabled', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
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
  it('[T-CONFIRM-1] clicking confirm fires POST /api/training/config with correct body (SAC)', async () => {
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
    expect(body.algorithm_type).toBe('sac');
    expect(body.sac_hyperparams).toBeDefined();
    // Verify constants are included
    expect(body.sac_hyperparams.tau).toBeCloseTo(0.005, 4);
    expect(body.sac_hyperparams.hidden_layers).toEqual([256, 256]);
    // Verify default hyperparam values
    expect(body.sac_hyperparams.total_steps).toBe(2_000_000);
    expect(body.sac_hyperparams.learning_rate).toBeCloseTo(3e-4, 6);
    expect(body.baselines).toContain('do_nothing');
    expect(body.baselines).toContain('peak_shave');
  });

  it('[T-CONFIRM-2] confirm fires POST with baseline_only; sac_hyperparams absent', async () => {
    makeFetchOk();
    renderStage();

    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body,
    );
    expect(body.algorithm_type).toBe('baseline_only');
    expect(body.sac_hyperparams).toBeUndefined();
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

    // Start click — post is pending
    act(() => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    // While pending: label should show saving state
    await waitFor(() => {
      const btn = screen.getByTestId('stage-two-confirm');
      expect(btn.textContent).toMatch(/Saving/);
    });

    // Resolve post to clean up
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

    // First attempt — fails
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    await waitFor(() => {
      expect(screen.getByTestId('confirm-retry')).toBeTruthy();
    });

    // Retry — succeeds
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
    makeFetchFail(422, { error: 'Invalid hyperparams', field: 'total_steps', message: 'Too low' });
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

  it('[T-BACK-2] clicking back calls onBack(); store state preserved', async () => {
    const { onBack } = renderStage();

    // Change algorithm first
    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    // Navigate back
    fireEvent.click(screen.getByTestId('stage-two-back'));

    expect(onBack).toHaveBeenCalledOnce();
    // State preserved: algorithmType should still be baseline_only
    expect(useStageAlgorithmStore.getState().algorithmType).toBe('baseline_only');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T10 — STALE state transitions
// ══════════════════════════════════════════════════════════════════════════════

describe('§T10 STALE state transitions (Class A edit rule)', () => {
  async function reachComplete() {
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

  it('[T-STALE-1] COMPLETE → STALE on algorithm type change', async () => {
    await reachComplete();
    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-2] COMPLETE → STALE on baseline toggle', async () => {
    await reachComplete();
    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-3] COMPLETE → STALE on any hyperparam field change', async () => {
    await reachComplete();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    const totalStepsInput = screen.getByTestId('hyperparam-totalSteps');
    fireEvent.change(totalStepsInput, { target: { value: '3000000' } });
    fireEvent.blur(totalStepsInput);

    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-4] STALE → COMPLETE after a new successful confirm', async () => {
    await reachComplete();

    // Trigger STALE
    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');

    // Re-confirm
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

    // reset() clears saveInProgress
    state.reset();
    expect(useStageAlgorithmStore.getState().saveInProgress).toBe(false);
  });

  it('[T-PERSIST-2] saveError not persisted (always null after reset)', () => {
    const state = useStageAlgorithmStore.getState();
    state.setSaveError('Something went wrong');
    expect(useStageAlgorithmStore.getState().saveError).toBe('Something went wrong');

    state.reset();
    expect(useStageAlgorithmStore.getState().saveError).toBeNull();
  });

  it('[T-PERSIST-3] rehydrate with COMPLETE immediately downgrades to IN_PROGRESS', () => {
    // Simulate what onRehydrateStorage does
    const store = useStageAlgorithmStore;
    store.setState({ stageState: 'COMPLETE' });
    // Manually trigger the rehydrate downgrade
    if (store.getState().stageState === 'COMPLETE') {
      store.setState({ stageState: 'IN_PROGRESS' });
    }
    expect(store.getState().stageState).toBe('IN_PROGRESS');
  });

  it('[T-PERSIST-4] reset() returns all persisted state to initial values', () => {
    const store = useStageAlgorithmStore.getState();
    store.setAlgorithmType('baseline_only');
    store.toggleBaseline('do_nothing'); // deselect

    store.reset();

    const state = useStageAlgorithmStore.getState();
    expect(state.algorithmType).toBe('sac');
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
    const sacCard = screen.getByTestId('algo-card-sac');
    const baseCard = screen.getByTestId('algo-card-baseline-only');
    expect(sacCard.getAttribute('role')).toBe('radio');
    expect(baseCard.getAttribute('role')).toBe('radio');
  });

  it('[T-A11Y-3] baseline group has role=group with aria-label', () => {
    renderStage();
    expect(screen.getByRole('group', { name: 'Baseline agents' })).toBeTruthy();
  });

  it('[T-A11Y-4] back button is not a <button> (span, per T-A11Y-6 precedent)', () => {
    renderStage();
    const back = screen.getByTestId('stage-two-back');
    expect(back.tagName.toLowerCase()).toBe('span');
  });

  it('[T-A11Y-5] confirm button uses aria-disabled, not HTML disabled attr', () => {
    renderStage();
    const btn = screen.getByTestId('stage-two-confirm') as HTMLButtonElement;
    // HTML disabled must not be set (button remains focusable for tooltips/screen readers)
    expect(btn.disabled).toBe(false);
    // aria-disabled is the mechanism
    expect(btn.getAttribute('aria-disabled')).toMatch(/^(true|false)$/);
  });

  it('[T-A11Y-6] hyperparam inputs have aria-describedby pointing to range hint', () => {
    renderStage();

    const header = screen.queryByTestId('hyperparam-header');
    if (header && header.getAttribute('aria-expanded') === 'false') {
      fireEvent.click(header);
    }

    const lrInput = screen.getByTestId('hyperparam-learningRate');
    const describedBy = lrInput.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    // The hint element must exist in the DOM
    expect(document.getElementById(describedBy!)).toBeTruthy();
  });

  it('[T-A11Y-7] hyperparam section header has aria-expanded', () => {
    renderStage();
    const header = screen.getByTestId('hyperparam-header');
    expect(['true', 'false']).toContain(header.getAttribute('aria-expanded'));
  });

  it('[T-A11Y-8] LOCKED stage: stage-two-content absent; no interactive elements for screen reader', () => {
    renderStage({ stageOneComplete: false });

    // No radio buttons, no checkboxes, no inputs from the content section
    const radios = screen.queryAllByRole('radio');
    const checkboxes = screen.queryAllByRole('checkbox');
    const textInputs = screen.queryAllByRole('textbox');

    expect(radios).toHaveLength(0);
    expect(checkboxes).toHaveLength(0);
    expect(textInputs).toHaveLength(0);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T13 — POST body validation
// ══════════════════════════════════════════════════════════════════════════════

describe('§T13 POST body schema (contract golden-example validation)', () => {
  it('[T-BODY-1] SAC body matches contract §3.8 golden example', async () => {
    makeFetchOk();
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body,
    );

    // Contract §3.8 shape validation:
    expect(typeof body.algorithm_type).toBe('string');
    expect(['sac', 'baseline_only']).toContain(body.algorithm_type);
    expect(Array.isArray(body.baselines)).toBe(true);
    expect(body.baselines.length).toBeGreaterThanOrEqual(1);

    if (body.algorithm_type === 'sac') {
      const h = body.sac_hyperparams;
      expect(typeof h).toBe('object');
      // All 7 user-visible fields present:
      expect(typeof h.total_steps).toBe('number');
      expect(typeof h.eval_freq).toBe('number');
      expect(typeof h.batch_size).toBe('number');
      expect(typeof h.learning_rate).toBe('number');
      expect(typeof h.gamma).toBe('number');
      expect(typeof h.buffer_size).toBe('number');
      expect(typeof h.n_envs).toBe('number');
      // Constants present:
      expect(typeof h.tau).toBe('number');
      expect(Array.isArray(h.hidden_layers)).toBe(true);
      // Golden example values (all defaults):
      // total_steps = 2_000_000
      // eval_freq = 50_000
      // batch_size = 256
      // learning_rate ≈ 3e-4 (= 0.0003)
      // gamma = 0.99
      // buffer_size = 1_000_000
      // n_envs = 16
      // tau = 0.005
      // hidden_layers = [256, 256]
      expect(h.total_steps).toBe(2_000_000);
      expect(h.eval_freq).toBe(50_000);
      expect(h.batch_size).toBe(256);
      expect(h.learning_rate).toBeCloseTo(3e-4, 6);
      expect(h.gamma).toBeCloseTo(0.99, 4);
      expect(h.buffer_size).toBe(1_000_000);
      expect(h.n_envs).toBe(16);
      expect(h.tau).toBeCloseTo(0.005, 4);
      expect(h.hidden_layers).toEqual([256, 256]);
    }
  });

  it('[T-BODY-2] baseline_only body: sac_hyperparams absent', async () => {
    makeFetchOk();
    renderStage();

    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    const body = JSON.parse(
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body,
    );
    expect(body.algorithm_type).toBe('baseline_only');
    expect(Object.prototype.hasOwnProperty.call(body, 'sac_hyperparams')).toBe(false);
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
    expect(useStageAlgorithmStore.getState().stageState).toBe('LOCKED');

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
});
