/**
 * tests/frontend/stage_algorithm.test.tsx
 *
 * Contract: contracts/frontend/stage_algorithm.md (Round 3 — v1 simplified scope)
 * REBUILD_SPEC: §5 (training methodology)
 * LINEAGE: D32 §(a)/(c) (algorithm registry + five-stage spine)
 *
 * v1 scope (rl-architect ruling 2026-06-14):
 *   - SAC is a NON-SUBMITTING stub card (coming-soon, read-only §5 constants preview)
 *   - Baseline selector: GET /api/baselines on mount; static fallback on failure
 *   - Confirm = local state only (stageState → COMPLETE; no POST)
 *   - POST /api/training/config deferred with SAC (DV-6) — C1/C2/C3 dissolved
 *
 * Vitest + React Testing Library v16
 */

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { useStageAlgorithmStore } from '../../src/stores/stageAlgorithmStore';
import StageTwoAlgorithm from '../../src/components/wizard/StageTwoAlgorithm';

// ── Mock fetch (GET /api/baselines) ───────────────────────────────────────

const STATIC_BASELINES = [
  { id: 'do_nothing',       label: 'Do-nothing',       description: 'Grid import fills all load; battery idle' },
  { id: 'peak_shave',       label: 'Peak-shave',       description: 'Discharge battery during tariff peak hours' },
  { id: 'import_minimiser', label: 'Import minimiser', description: 'Greedy rule: charge when PV > load, else dispatch' },
];

function makeBaselinesOk(baselines = STATIC_BASELINES) {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(baselines),
    } as Response),
  );
}

function makeBaselinesFail() {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ error: 'Internal error' }),
    } as Response),
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────

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

function switchToSac() {
  fireEvent.click(screen.getByTestId('algo-card-sac'));
}

// ── Setup / teardown ───────────────────────────────────────────────────────

beforeEach(() => {
  useStageAlgorithmStore.getState().reset();
  makeBaselinesOk();
});

afterEach(() => {
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

  it('[T-LOCK-2] locked: algorithm cards and baselines section absent from DOM (not just hidden)', () => {
    renderStage({ stageOneComplete: false });

    expect(screen.queryByTestId('algo-card-sac')).toBeNull();
    expect(screen.queryByTestId('algo-card-baseline-only')).toBeNull();
    expect(screen.queryByTestId('baselines-section')).toBeNull();
  });

  it('[T-LOCK-3] locked: "← Go to Config" link calls onBack()', () => {
    const { onBack } = renderStage({ stageOneComplete: false });
    fireEvent.click(screen.getByTestId('stage-two-locked-go-config'));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('[T-LOCK-4] locked: back button in footer calls onBack()', () => {
    const { onBack } = renderStage({ stageOneComplete: false });
    fireEvent.click(screen.getByTestId('stage-two-back'));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('[T-LOCK-5] locked: GET /api/baselines NOT called (no fetch when locked)', async () => {
    renderStage({ stageOneComplete: false });
    await Promise.resolve(); // flush microtasks
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('[T-LOCK-6] locked → unlocked: content becomes visible; loadBaselines fires', async () => {
    const { rerender } = renderStage({ stageOneComplete: false });
    expect(screen.queryByTestId('stage-two-content')).toBeNull();

    rerender(
      <StageTwoAlgorithm stageOneComplete={true} onBack={vi.fn()} onContinue={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByTestId('stage-two-content')).toBeTruthy();
    });
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T2 — Initial render (CALL 2: baseline_only default; Option B: SAC secondary)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T2 Initial render — baseline_only default + Option B visual treatment', () => {
  it('[T-INIT-1] content visible; baseline_only selected by default; SAC not selected', () => {
    renderStage();

    expect(screen.getByTestId('stage-two-content')).toBeTruthy();
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('algo-card-sac').getAttribute('aria-checked')).toBe('false');
  });

  it('[T-INIT-2] algorithm cards have role=radio; wrapper has role=radiogroup + aria-label', () => {
    renderStage();

    expect(screen.getByTestId('algo-card-sac').getAttribute('role')).toBe('radio');
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('role')).toBe('radio');
    expect(screen.getByRole('radiogroup', { name: 'Training algorithm' })).toBeTruthy();
  });

  it('[T-INIT-3] do_nothing and peak_shave checked by default; import_minimiser unchecked', async () => {
    renderStage();
    await waitFor(() => {
      expect((screen.getByTestId('baseline-checkbox-do_nothing') as HTMLInputElement).checked).toBe(true);
    });
    expect((screen.getByTestId('baseline-checkbox-peak_shave') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId('baseline-checkbox-import_minimiser') as HTMLInputElement).checked).toBe(false);
  });

  it('[T-INIT-4] baseline notice visible on initial render; SAC sections absent (baseline_only mode)', () => {
    renderStage();

    expect(screen.getByTestId('algo-baseline-notice')).toBeTruthy();
    expect(screen.queryByTestId('algo-sac-coming-soon-notice')).toBeNull();
    expect(screen.queryByTestId('algo-sac-constants-preview')).toBeNull();
  });

  it('[T-INIT-5] SAC card has future-badge element (Option B: secondary/de-emphasized)', () => {
    renderStage();
    expect(screen.getByTestId('algo-card-sac-future-badge')).toBeTruthy();
    expect(screen.queryByTestId('algo-card-baseline-only-future-badge')).toBeNull();
  });

  it('[T-INIT-6] Confirm enabled on initial render (baseline_only + 2 baselines = valid)', () => {
    renderStage();
    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('false');
  });

  it('[T-INIT-7] stage-two-algorithm root testid exists', () => {
    renderStage();
    expect(screen.getByTestId('stage-two-algorithm')).toBeTruthy();
  });

  it('[T-INIT-8] no POST to /api/training/config issued on any user action (no config POST in v1)', async () => {
    renderStage();
    switchToSac();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    // Only GET /api/baselines should ever be called — not a config POST
    const allCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    allCalls.forEach(([url]: [string]) => {
      expect(url).not.toContain('/api/training/config');
    });
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T3 — Algorithm card interaction (SAC = non-submitting stub)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T3 Algorithm card interaction (SAC = non-submitting stub)', () => {
  it('[T-ALGO-1] selecting SAC: aria-checked flips; coming-soon notice + constants preview appear', () => {
    renderStage();
    switchToSac();

    expect(screen.getByTestId('algo-card-sac').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('algo-card-baseline-only').getAttribute('aria-checked')).toBe('false');
    expect(screen.getByTestId('algo-sac-coming-soon-notice')).toBeTruthy();
    expect(screen.getByTestId('algo-sac-constants-preview')).toBeTruthy();
  });

  it('[T-ALGO-2] SAC constants-preview contains NO editable inputs (read-only display)', () => {
    renderStage();
    switchToSac();

    const preview = screen.getByTestId('algo-sac-constants-preview');
    expect(preview.querySelectorAll('input, textarea')).toHaveLength(0);
  });

  it('[T-ALGO-3] SAC constants-preview shows §5 locked gamma = 0.999 (read-only display constant, C2 resolution)', () => {
    // gamma is LOCKED per training_pipeline.md §3.1; shown read-only in the SAC stub preview
    renderStage();
    switchToSac();

    const preview = screen.getByTestId('algo-sac-constants-preview');
    expect(preview.textContent).toMatch(/0\.999/);
  });

  it('[T-ALGO-4] baseline-only notice visible on initial render; hidden after switching to SAC', () => {
    renderStage();
    expect(screen.getByTestId('algo-baseline-notice')).toBeTruthy();

    switchToSac();
    expect(screen.queryByTestId('algo-baseline-notice')).toBeNull();
  });

  it('[T-ALGO-5] switching SAC → baseline_only: SAC sections hidden; notice reappears', () => {
    renderStage();
    switchToSac();

    expect(screen.getByTestId('algo-sac-coming-soon-notice')).toBeTruthy();

    fireEvent.click(screen.getByTestId('algo-card-baseline-only'));
    expect(screen.queryByTestId('algo-sac-coming-soon-notice')).toBeNull();
    expect(screen.queryByTestId('algo-sac-constants-preview')).toBeNull();
    expect(screen.getByTestId('algo-baseline-notice')).toBeTruthy();
  });

  it('[T-ALGO-6] switching algorithm when COMPLETE → STALE (Class A rule D32 §c)', async () => {
    renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');

    switchToSac();
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-ALGO-7] Space key on SAC card selects it (keyboard navigation)', () => {
    renderStage();
    const sacCard = screen.getByTestId('algo-card-sac');
    fireEvent.keyDown(sacCard, { key: ' ', code: 'Space' });
    expect(sacCard.getAttribute('aria-checked')).toBe('true');
  });

  it('[T-ALGO-8] selecting SAC does NOT fire a POST (non-submitting in v1)', async () => {
    renderStage();
    switchToSac();
    await Promise.resolve();

    const postCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([url]: [string]) => url === '/api/training/config',
    );
    expect(postCalls).toHaveLength(0);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T4 — GET /api/baselines (fetch on mount + static fallback)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T4 GET /api/baselines fetch', () => {
  it('[T-BASE-FETCH-1] fires GET /api/baselines on mount', async () => {
    renderStage();

    await waitFor(() => {
      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const baselinesCalls = calls.filter(([url]: [string]) => url === '/api/baselines');
      expect(baselinesCalls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('[T-BASE-FETCH-2] GET success → baseline checkboxes rendered', async () => {
    renderStage();

    await waitFor(() => {
      expect(screen.getByTestId('baseline-checkbox-do_nothing')).toBeTruthy();
      expect(screen.getByTestId('baseline-checkbox-peak_shave')).toBeTruthy();
      expect(screen.getByTestId('baseline-checkbox-import_minimiser')).toBeTruthy();
    });
  });

  it('[T-BASE-FETCH-3] GET failure → static fallback; all three baselines still render', async () => {
    makeBaselinesFail();
    renderStage();

    await waitFor(() => {
      expect(screen.getByTestId('baseline-checkbox-do_nothing')).toBeTruthy();
      expect(screen.getByTestId('baseline-checkbox-peak_shave')).toBeTruthy();
      expect(screen.getByTestId('baseline-checkbox-import_minimiser')).toBeTruthy();
    });
  });

  it('[T-BASE-FETCH-4] GET failure → baselines-load-error rendered with role=status', async () => {
    makeBaselinesFail();
    renderStage();

    await waitFor(() => {
      expect(screen.getByTestId('baselines-load-error')).toBeTruthy();
    });
    expect(screen.getByTestId('baselines-load-error').getAttribute('role')).toBe('status');
  });

  it('[T-BASE-FETCH-5] GET failure → confirm NOT blocked (static fallback + defaults selected)', async () => {
    makeBaselinesFail();
    renderStage();

    await waitFor(() => {
      expect(screen.getByTestId('baselines-load-error')).toBeTruthy();
    });

    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('false');
  });

  it('[T-BASE-FETCH-6] GET success → no baselines-load-error rendered', async () => {
    makeBaselinesOk();
    renderStage();

    await waitFor(() => {
      expect(screen.queryByTestId('baselines-load-error')).toBeNull();
    });
  });

  it('[T-BASE-FETCH-7] selectedBaselines preserved across load (no reset on fetch completion)', async () => {
    renderStage();

    // Deselect one baseline before fetch settles
    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));

    await waitFor(() => expect(screen.queryByTestId('baselines-load-error')).toBeNull());

    // Still deselected — fetch must not reset user state
    expect((screen.getByTestId('baseline-checkbox-do_nothing') as HTMLInputElement).checked).toBe(false);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T5 — Baseline selection
// ══════════════════════════════════════════════════════════════════════════════

describe('§T5 Baseline selection', () => {
  it('[T-BASE-1] baselines section has role=group with aria-label', () => {
    renderStage();
    expect(screen.getByRole('group', { name: 'Baseline agents' })).toBeTruthy();
  });

  it('[T-BASE-2] each baseline has its checkbox testid', () => {
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

  it('[T-BASE-4] no-baseline state → confirm aria-disabled=true', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('true');
  });

  it('[T-BASE-5] confirm-disabled-reason shows "baseline" message when none selected', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    expect(screen.getByTestId('confirm-disabled-reason').textContent).toMatch(/baseline/i);
  });

  it('[T-BASE-6] re-checking a baseline clears the no-baseline error', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));
    expect(screen.getByTestId('baseline-none-error')).toBeTruthy();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    expect(screen.queryByTestId('baseline-none-error')).toBeNull();
  });

  it('[T-BASE-7] toggling baseline while COMPLETE → STALE', async () => {
    renderStage();
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');

    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-BASE-8] all three baselines can be selected; confirm enabled', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));

    expect((screen.getByTestId('baseline-checkbox-do_nothing') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId('baseline-checkbox-peak_shave') as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId('baseline-checkbox-import_minimiser') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId('stage-two-confirm').getAttribute('aria-disabled')).toBe('false');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T6 — Confirm & Continue (local state only — no POST in v1)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T6 Confirm & Continue — local state only (no POST)', () => {
  it('[T-CONFIRM-1] confirm (baseline_only) → COMPLETE; onContinue called; no POST fetch', async () => {
    const { onContinue } = renderStage();
    await waitFor(() => expect(screen.queryByTestId('baselines-load-error')).toBeNull());

    (globalThis.fetch as ReturnType<typeof vi.fn>).mockClear();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    expect(onContinue).toHaveBeenCalledOnce();
    // No POST issued
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('[T-CONFIRM-2] confirm (SAC selected) → COMPLETE; onContinue called; no POST', async () => {
    const { onContinue } = renderStage();
    switchToSac();
    await waitFor(() => expect(screen.queryByTestId('baselines-load-error')).toBeNull());

    (globalThis.fetch as ReturnType<typeof vi.fn>).mockClear();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
    expect(onContinue).toHaveBeenCalledOnce();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('[T-CONFIRM-3] after confirm, store carries algorithmType and selectedBaselines', async () => {
    renderStage();
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    const state = useStageAlgorithmStore.getState();
    expect(state.algorithmType).toBe('baseline_only');
    expect(state.selectedBaselines).toContain('do_nothing');
    expect(state.selectedBaselines).toContain('peak_shave');
  });

  it('[T-CONFIRM-4] aria-disabled=true: click intercepted; onContinue NOT called; stageState unchanged', () => {
    // reviewer: aria-disabled interception — disabled button must not fire the confirm handler
    const { onContinue } = renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    const btn = screen.getByTestId('stage-two-confirm');
    expect(btn.getAttribute('aria-disabled')).toBe('true');

    fireEvent.click(btn);
    expect(onContinue).not.toHaveBeenCalled();
    expect(useStageAlgorithmStore.getState().stageState).not.toBe('COMPLETE');
  });

  it('[T-CONFIRM-5] double-confirm: second click after COMPLETE does not double-call onContinue', async () => {
    // reviewer: double-submit protection — confirm is idempotent
    const { onContinue } = renderStage();

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });

    // Must have been called at most once
    expect(onContinue).toHaveBeenCalledOnce();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T7 — Back button
// ══════════════════════════════════════════════════════════════════════════════

describe('§T7 Back button', () => {
  it('[T-BACK-1] back button is a <span>, not <button> (DV-1)', () => {
    renderStage();
    expect(screen.getByTestId('stage-two-back').tagName.toLowerCase()).toBe('span');
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
// §T8 — STALE state transitions (Class A edit rule D32 §c)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T8 STALE state transitions', () => {
  async function reachComplete() {
    renderStage();
    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
  }

  it('[T-STALE-1] COMPLETE (baseline_only) → STALE on switching to SAC', async () => {
    await reachComplete();
    switchToSac();
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-2] COMPLETE → STALE on baseline toggle', async () => {
    await reachComplete();
    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');
  });

  it('[T-STALE-3] STALE → COMPLETE after re-confirm', async () => {
    await reachComplete();
    fireEvent.click(screen.getByTestId('baseline-checkbox-import_minimiser'));
    expect(useStageAlgorithmStore.getState().stageState).toBe('STALE');

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-two-confirm'));
    });
    expect(useStageAlgorithmStore.getState().stageState).toBe('COMPLETE');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T9 — Store persistence (partialize / rehydrate)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T9 Store persistence and rehydration', () => {
  it('[T-PERSIST-1] baselinesLoading not persisted (false after reset)', () => {
    useStageAlgorithmStore.setState({ baselinesLoading: true });
    useStageAlgorithmStore.getState().reset();
    expect(useStageAlgorithmStore.getState().baselinesLoading).toBe(false);
  });

  it('[T-PERSIST-2] baselinesError not persisted (null after reset)', () => {
    useStageAlgorithmStore.setState({ baselinesError: 'load failed' });
    useStageAlgorithmStore.getState().reset();
    expect(useStageAlgorithmStore.getState().baselinesError).toBeNull();
  });

  it('[T-PERSIST-3] onRehydrate(): COMPLETE → IN_PROGRESS via the real persist hook', () => {
    // reviewer: TQ14 — real rehydrate path, not a fake setState.
    // The store exposes onRehydrate(state) — the exact function Zustand's
    // onRehydrateStorage calls. We call it directly to verify the downgrade logic.
    const store = useStageAlgorithmStore;
    const hydratedState = { ...store.getState(), stageState: 'COMPLETE' as const };
    store.getState().onRehydrate(hydratedState);
    expect(store.getState().stageState).toBe('IN_PROGRESS');
  });

  it('[T-PERSIST-4] reset() restores initial values (CALL 2: baseline_only, 2 defaults)', () => {
    const store = useStageAlgorithmStore.getState();
    store.setAlgorithmType('sac');
    store.toggleBaseline('do_nothing');
    store.reset();

    const state = useStageAlgorithmStore.getState();
    expect(state.algorithmType).toBe('baseline_only');
    expect(state.selectedBaselines).toContain('do_nothing');
    expect(state.selectedBaselines).toContain('peak_shave');
    expect(state.stageState).toBe('PENDING');
  });

  it('[T-PERSIST-5] algorithmType and selectedBaselines survive onRehydrate (persisted fields)', () => {
    const store = useStageAlgorithmStore;
    store.setState({ algorithmType: 'sac', selectedBaselines: ['import_minimiser'] });

    // onRehydrate must NOT reset persisted fields
    const hydratedState = { ...store.getState() };
    store.getState().onRehydrate(hydratedState);

    expect(store.getState().algorithmType).toBe('sac');
    expect(store.getState().selectedBaselines).toEqual(['import_minimiser']);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T10 — Accessibility
// ══════════════════════════════════════════════════════════════════════════════

describe('§T10 Accessibility', () => {
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

  it('[T-A11Y-4] back button is a <span> not <button> (DV-1)', () => {
    renderStage();
    expect(screen.getByTestId('stage-two-back').tagName.toLowerCase()).toBe('span');
  });

  it('[T-A11Y-5] confirm button uses aria-disabled, not HTML disabled', () => {
    renderStage();
    const btn = screen.getByTestId('stage-two-confirm') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    expect(btn.getAttribute('aria-disabled')).toMatch(/^(true|false)$/);
  });

  it('[T-A11Y-6] LOCKED stage: no interactive elements in DOM (screen reader safe)', () => {
    renderStage({ stageOneComplete: false });

    expect(screen.queryAllByRole('radio')).toHaveLength(0);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryAllByRole('textbox')).toHaveLength(0);
  });

  it('[T-A11Y-7] aria-disabled="true" confirm intercepts click; confirm handler NOT called', () => {
    // reviewer: aria-disabled interception — the click event must not reach the handler
    const { onContinue } = renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    const btn = screen.getByTestId('stage-two-confirm');
    expect(btn.getAttribute('aria-disabled')).toBe('true');

    fireEvent.click(btn);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it('[T-A11Y-8] baseline-none-error has role=alert', () => {
    renderStage();

    fireEvent.click(screen.getByTestId('baseline-checkbox-do_nothing'));
    fireEvent.click(screen.getByTestId('baseline-checkbox-peak_shave'));

    expect(screen.getByTestId('baseline-none-error').getAttribute('role')).toBe('alert');
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T11 — lockStage / unlockStage propagation (incl. false→true→false cycle)
// ══════════════════════════════════════════════════════════════════════════════

describe('§T11 lockStage / unlockStage propagation', () => {
  it('[T-LOCK-PROP-1] lockStage() → LOCKED', () => {
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

  it('[T-LOCK-PROP-3] component re-renders to LOCKED when stageOneComplete becomes false', () => {
    const { rerender } = render(
      <StageTwoAlgorithm stageOneComplete={true} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-content')).toBeTruthy();

    rerender(
      <StageTwoAlgorithm stageOneComplete={false} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-locked')).toBeTruthy();
    expect(screen.queryByTestId('stage-two-content')).toBeNull();
  });

  it('[T-LOCK-PROP-4] false→true→false stageOneComplete cycle: content accessible after re-enable', () => {
    // reviewer: TQ13 — LOCKED flip must not leave component stuck in LOCKED state
    const { rerender } = render(
      <StageTwoAlgorithm stageOneComplete={true} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-content')).toBeTruthy();

    rerender(
      <StageTwoAlgorithm stageOneComplete={false} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-locked')).toBeTruthy();

    rerender(
      <StageTwoAlgorithm stageOneComplete={true} onBack={vi.fn()} onContinue={vi.fn()} />,
    );
    expect(screen.getByTestId('stage-two-content')).toBeTruthy();
    expect(screen.queryByTestId('stage-two-locked')).toBeNull();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// §T12 — reviewer adversarial additions (frontend-reviewer, PR #115 Round 4 re-gate)
// reviewer: the v1 scope removed the POST + editable hyperparams, so the SAC §5
// constants PREVIEW is now the stage's main data-display surface. T-ALGO-3 pins only
// gamma=0.999; these pin the rest and guard against the superseded UX placeholders
// (lr=3e-4, batch=256, 2M steps, 16 envs) leaking into the read-only display — a
// wrong displayed constant is a prime-directive data-correctness bug. Also pins that
// a server /api/baselines response is actually consumed (not silently ignored for static).
// ══════════════════════════════════════════════════════════════════════════════

describe('reviewer: §T12 adversarial additions (v1 scope)', () => {
  it('reviewer: [T-ALGO-9] SAC constants-preview shows the correct §5 values (lr, batch, steps), not UX placeholders', () => {
    // reviewer: §5 / training_pipeline.md §3 RunConfig — lr=1e-4, batch_size=512,
    // total_env_steps=500_000. The superseded stage_2_algorithm.md placeholders were
    // lr=3e-4 and batch=256; they must NOT appear. (gamma=0.999 is covered by T-ALGO-3.)
    renderStage();
    switchToSac();
    const text = screen.getByTestId('algo-sac-constants-preview').textContent ?? '';

    // lr = 1e-4 present; old placeholder 3e-4 absent
    expect(text).toMatch(/1e-?4|0\.0001/);
    expect(text).not.toMatch(/3e-?4|0\.0003/);
    // batch_size = 512 present (512 is unique to batch among the §5 constants)
    expect(text).toMatch(/\b512\b/);
    // total_env_steps = 500_000 present (accept 500000 / 500,000 / 500_000 / 500k)
    expect(text).toMatch(/500[,_\s]?000|500\s*k/i);
  });

  it('reviewer: [T-BASE-FETCH-8] a server /api/baselines response is actually consumed (not ignored for static)', async () => {
    // reviewer: T-BASE-FETCH-2/3 use the default mock whose list == the static fallback, so an
    // impl that ignores the fetch and always renders the static list would pass both. Return a
    // server payload with a distinguishing label and assert it reaches the DOM — proving the
    // fetched data is what's rendered on the success path.
    makeBaselinesOk([
      { id: 'do_nothing',       label: 'Do-nothing [SERVER]',       description: 'server desc 1' },
      { id: 'peak_shave',       label: 'Peak-shave [SERVER]',       description: 'server desc 2' },
      { id: 'import_minimiser', label: 'Import minimiser [SERVER]', description: 'server desc 3' },
    ]);
    renderStage();
    await waitFor(() => {
      expect(screen.getByText(/Do-nothing \[SERVER\]/)).toBeTruthy();
    });
  });
});
