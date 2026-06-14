// src/stores/stageAlgorithmStore.ts
// Zustand persist store for Wizard Stage ② algorithm + baseline selection.
// Contract: contracts/frontend/stage_algorithm.md §3.4–§3.6 (v1 simplified scope)
//
// v1 scope (rl-architect ruling 2026-06-14):
//   - Baseline selector: GET /api/baselines on unlock + static fallback on failure
//   - SAC: NON-SUBMITTING stub — algorithmType='sac' carried forward only
//   - confirm() = local state → COMPLETE; no POST (DV-6)
//   - POST /api/training/config PROVISIONAL/DEFERRED until SAC un-defers

import { create } from "zustand";
import { persist } from "zustand/middleware";

// ── Types (§3.4) ─────────────────────────────────────────────────────────────

export type StageTwoState =
  | "LOCKED"
  | "PENDING"
  | "IN_PROGRESS"
  | "COMPLETE"
  | "STALE";

export type AlgorithmType = "baseline_only" | "sac";

export type BaselineId = "do_nothing" | "peak_shave" | "import_minimiser";

export interface BaselineItem {
  id: string;
  label: string;
  description: string;
}

// ── Static fallback (used when GET /api/baselines fails) ─────────────────────

export const STATIC_BASELINES: BaselineItem[] = [
  {
    id: "do_nothing",
    label: "Do-nothing",
    description: "Grid import fills all load; battery idle",
  },
  {
    id: "peak_shave",
    label: "Peak-shave",
    description: "Discharge battery during tariff peak hours",
  },
  {
    id: "import_minimiser",
    label: "Import minimiser",
    description: "Greedy rule: charge when PV > load, else dispatch",
  },
];

// ── Store state interface (§3.4) ──────────────────────────────────────────────

export interface StageTwoStoreState {
  stageState: StageTwoState;
  algorithmType: AlgorithmType;
  selectedBaselines: BaselineId[];
  /** Available baselines from API or static fallback. Not persisted — re-fetched on mount. */
  availableBaselines: BaselineItem[];
  /** true while GET /api/baselines is in-flight. Not persisted. */
  baselinesLoading: boolean;
  /** null when no error or when static fallback is active. Not persisted. */
  baselinesError: string | null;
}

// ── Store actions interface (§3.5) ────────────────────────────────────────────

export interface StageTwoStoreActions {
  setAlgorithmType(type: AlgorithmType): void;
  toggleBaseline(id: BaselineId): void;
  setAllBaselines(ids: BaselineId[]): void;
  /** Fetch GET /api/baselines; on success updates availableBaselines; on failure keeps
   *  static fallback and sets baselinesError. Does not reset selectedBaselines. */
  loadBaselines(): Promise<void>;
  /** Transition stageState → COMPLETE. No-op if not isConfirmEnabled or already COMPLETE. */
  confirm(): void;
  lockStage(): void;
  unlockStage(): void;
  reset(): void;
  /** Called by Zustand persist onRehydrateStorage — downgrades COMPLETE → IN_PROGRESS
   *  and exposed as an action for direct testing (T-PERSIST-3). */
  onRehydrate(state: StageTwoStoreState): void;
}

type StoreType = StageTwoStoreState & StageTwoStoreActions;

// ── isConfirmEnabled (§3.6) ───────────────────────────────────────────────────
// Exported for use in the component; single source of truth.

export function isConfirmEnabled(state: Pick<StageTwoStoreState, "selectedBaselines">): boolean {
  return state.selectedBaselines.length >= 1;
}

// ── Class A edit rule (D32 §c): any algo/baseline change while COMPLETE → STALE
// Helper returns the new stageState for an edit action.

function _editStateTransition(current: StageTwoState): StageTwoState {
  if (current === "COMPLETE" || current === "STALE") return "STALE";
  if (current === "PENDING") return "IN_PROGRESS";
  return current; // LOCKED / IN_PROGRESS → unchanged
}

// ── Initial state ─────────────────────────────────────────────────────────────

const INITIAL_STATE: StageTwoStoreState = {
  stageState: "PENDING",
  algorithmType: "baseline_only",
  selectedBaselines: ["do_nothing", "peak_shave"],
  availableBaselines: STATIC_BASELINES,
  baselinesLoading: false,
  baselinesError: null,
};

// ── Store ─────────────────────────────────────────────────────────────────────

export const useStageAlgorithmStore = create<StoreType>()(
  persist(
    (set, get) => ({
      ...INITIAL_STATE,

      // ── Algorithm selection ─────────────────────────────────────────────

      setAlgorithmType(type) {
        set((s) => ({
          algorithmType: type,
          stageState: _editStateTransition(s.stageState),
        }));
      },

      // ── Baseline selection ──────────────────────────────────────────────

      toggleBaseline(id) {
        set((s) => {
          const already = s.selectedBaselines.includes(id);
          const next = already
            ? s.selectedBaselines.filter((b) => b !== id)
            : [...s.selectedBaselines, id];
          return {
            selectedBaselines: next,
            stageState: _editStateTransition(s.stageState),
          };
        });
      },

      setAllBaselines(ids) {
        set({ selectedBaselines: ids });
      },

      // ── GET /api/baselines ──────────────────────────────────────────────

      async loadBaselines() {
        set({ baselinesLoading: true, baselinesError: null });
        try {
          const res = await fetch("/api/baselines");
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data: BaselineItem[] = await res.json();
          // Update available list; do NOT reset selectedBaselines (T-BASE-FETCH-7)
          set({ availableBaselines: data, baselinesLoading: false });
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          // Keep static fallback; set error indicator
          set({
            availableBaselines: STATIC_BASELINES,
            baselinesLoading: false,
            baselinesError: msg,
          });
        }
      },

      // ── Confirm (local only — no POST in v1) ────────────────────────────

      confirm() {
        const s = get();
        if (!isConfirmEnabled(s)) return; // guard: no baselines selected
        if (s.stageState === "COMPLETE") return; // double-submit guard (T-CONFIRM-5)
        set({ stageState: "COMPLETE" });
      },

      // ── Lock / unlock (driven by stageOneComplete prop) ─────────────────

      lockStage() {
        set({ stageState: "LOCKED" });
      },

      unlockStage() {
        set((s) => {
          if (s.stageState === "LOCKED") return { stageState: "PENDING" as StageTwoState };
          return {};
        });
      },

      // ── Reset ────────────────────────────────────────────────────────────

      reset() {
        set({ ...INITIAL_STATE });
      },

      // ── onRehydrate: called by persist's onRehydrateStorage + exposed for
      //    direct testing (T-PERSIST-3). Downgrades COMPLETE → IN_PROGRESS. ──

      onRehydrate(hydratedState) {
        const nextStageState: StageTwoState =
          hydratedState.stageState === "COMPLETE"
            ? "IN_PROGRESS"
            : hydratedState.stageState;
        set({
          ...hydratedState,
          stageState: nextStageState,
          // Transient UI flags always reset regardless of persisted value
          baselinesLoading: false,
          baselinesError: null,
          availableBaselines: hydratedState.availableBaselines ?? STATIC_BASELINES,
        });
      },
    }),
    {
      name: "energygo.stage2",
      // Persist wizard selections; exclude transient loading/error flags
      partialize: (state) => ({
        stageState: state.stageState,
        algorithmType: state.algorithmType,
        selectedBaselines: state.selectedBaselines,
      }),
      onRehydrateStorage: () => (hydratedState) => {
        if (hydratedState) {
          // Delegate to the store action so test can call it directly (T-PERSIST-3)
          useStageAlgorithmStore.getState().onRehydrate(hydratedState as StageTwoStoreState);
        }
      },
    },
  ),
);
