// src/stores/stageOneStore.ts
// Zustand store for Wizard Stage ① persistent state
// Contract: contracts/frontend/stage_config.md §3.2

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  StageOneState,
  WeatherMode,
  LatLon,
  DeviceRow,
  ValidationResult,
  WeatherCoverage,
  FleetEntry,
} from "../types/stageConfig";

// ── Assemble body builder (§5.1) ───────────────────────────────────────────

function buildAssembleBody(state: StageOneStoreState & StageOneStoreActions) {
  const validRows = state.fleet.filter(r => r.valid === true);
  const fleetEntries: FleetEntry[] = validRows.map(r => {
    switch (r.type) {
      case 'pv_panel':
        return { model_id: r.id, fleet_capacity_mw: r.fleetCapacityMw ?? 0 };
      case 'grid_connection':
        return { model_id: r.id };
      default:
        return { model_id: r.id, count: r.count ?? 1 };
    }
  });

  return {
    fleet: fleetEntries,
    tariff_region: state.tariffRegion,
    site_meta: {
      ...(state.location && { lat: state.location.lat, lon: state.location.lon }),
      ...(state.siteName && { name: state.siteName }),
      ...(state.province && { province: state.province }),
      weather_mode: state.weatherMode,
    },
  };
}

// ── Module-level debounce state (§5.1) ─────────────────────────────────────
// Placed outside store to survive across state updates and test cycles.

let _debounceTimer: ReturnType<typeof setTimeout> | null = null;
let _activeController: AbortController | null = null;

function _clearDebounce() {
  if (_debounceTimer !== null) { clearTimeout(_debounceTimer); _debounceTimer = null; }
}

/** Schedule a POST /api/site/assemble debounce.
 *  Classic debounce: clear old timer, schedule new 300ms timer.
 *  When timer fires: abort any in-flight request, start new one with AbortController. */
function _scheduleAssemble() {
  const state = useStageOneStore.getState();
  const validCount = state.fleet.filter(r => r.valid === true).length;
  const guardMet = validCount > 0 && state.tariffRegion !== '';

  // Clear the existing timer regardless (reset debounce on every meaningful change)
  _clearDebounce();
  // Also abort the in-flight request (stale response guard per §5.1 race-condition rule)
  if (_activeController !== null) { _activeController.abort(); _activeController = null; }

  if (!guardMet) return;

  _debounceTimer = setTimeout(async () => {
    _debounceTimer = null;
    const s = useStageOneStore.getState();
    const validNow = s.fleet.filter(r => r.valid === true).length;
    if (validNow === 0 || s.tariffRegion === '') return;

    // Transition to VALIDATING
    useStageOneStore.setState({ validationPending: true });
    if (s.stageState === 'IN_PROGRESS' || s.stageState === 'STALE') {
      useStageOneStore.setState({ stageState: 'VALIDATING' });
    }

    // Start new request with fresh AbortController
    _activeController = new AbortController();
    const { signal } = _activeController;

    try {
      const body = buildAssembleBody(s);
      const resp = await fetch('/api/site/assemble', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      });
      if (!resp.ok) throw new Error(`${resp.status}`);
      const data = await resp.json() as { errors: ValidationResult['errors']; warnings: ValidationResult['warnings'] };
      _activeController = null;
      useStageOneStore.getState().receiveValidation({ errors: data.errors, warnings: data.warnings });
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      _activeController = null;
      // B5: surface the error so ValidationPanel can show it via apiError
      useStageOneStore.setState({
        validationPending: false,
        assembleError: (err as Error).message || 'Assemble failed',
      });
    }
  }, 300);
}

// ── Store interfaces (§3.2) ─────────────────────────────────────────────────

export interface StageOneStoreState {
  stageState:               StageOneState;
  siteName:                 string;
  province:                 string;
  tariffRegion:             string;
  tariffManuallyOverridden: boolean;
  location:                 LatLon | null;
  weatherMode:              WeatherMode;
  fleet:                    DeviceRow[];
  scenarioBasePowerActive:  boolean;
  lastValidation:           ValidationResult | null;
  acknowledgedWarnings:     string[];
  validationPending:        boolean;
  coveragePending:          boolean;
  coverageResult:           WeatherCoverage | null;
  coverageError:            string | null;
  saveInProgress:           boolean;
  saveError:                string | null;
  assembleError:            string | null;
  provenanceHash:           string | null;
}

export interface StageOneStoreActions {
  setSiteName(name: string): void;
  setProvince(province: string): void;
  setTariffRegion(regionId: string, isManualOverride: boolean): void;
  resetTariffToProvinceDefault(): void;
  setLocation(loc: LatLon | null): void;
  setWeatherMode(mode: WeatherMode): void;

  addDevice(row: DeviceRow): void;
  updateDeviceCount(index: number, count: number): void;
  updateDeviceFleetMw(index: number, mw: number): void;
  removeDevice(index: number): void;
  resolveDevice(index: number, resolved: Pick<DeviceRow, 'type' | 'label' | 'valid' | 'physics'>): void;

  acknowledgeWarning(ruleId: string): void;
  receiveValidation(result: ValidationResult): void;
  setValidationPending(pending: boolean): void;
  receiveCoverage(result: WeatherCoverage): void;
  setCoverageError(msg: string | null): void;

  setSaveInProgress(v: boolean): void;
  setSaveError(msg: string | null): void;
  onSaveSuccess(configHash: string): void;

  /** Clear assembleError and re-fire the 300ms assemble debounce (B6 fix). */
  retryAssemble(): void;

  reset(): void;
}

// ── Helper: check if we're now COMPLETE ────────────────────────────────────

function _isNowComplete(
  validation: ValidationResult | null,
  acked: string[],
): boolean {
  if (!validation) return false;
  if (validation.errors.length > 0) return false;
  const unacked = validation.warnings.filter(w => !acked.includes(w.rule_id));
  return unacked.length === 0;
}

// ── Helper: transition state on meaningful edit (S1 rule) ──────────────────

function _editTransition(current: StageOneState): StageOneState {
  if (current === 'FIRST_VISIT') return 'IN_PROGRESS';
  if (current === 'COMPLETE') return 'STALE';
  return current;
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useStageOneStore = create<StageOneStoreState & StageOneStoreActions>()(
  persist(
    (set, get) => ({
      // ── Initial state ──────────────────────────────────────────────────
      stageState:               'FIRST_VISIT',
      siteName:                 '',
      province:                 '',
      tariffRegion:             '',
      tariffManuallyOverridden: false,
      location:                 null,
      weatherMode:              'synthetic',
      fleet:                    [],
      scenarioBasePowerActive:  true,
      lastValidation:           null,
      acknowledgedWarnings:     [],
      validationPending:        false,
      coveragePending:          false,
      coverageResult:           null,
      coverageError:            null,
      saveInProgress:           false,
      saveError:                null,
      assembleError:            null,
      provenanceHash:           null,

      // ── Actions ────────────────────────────────────────────────────────

      setSiteName(name) {
        set(s => ({ siteName: name }));
        // siteName is not a meaningful-edit trigger for assemble (not in §5.1 list)
      },

      setProvince(province) {
        set({ province });
        // Province change is not in the assemble trigger list directly;
        // it affects tariff via useSiteMetaForm auto-update
      },

      setTariffRegion(regionId, isManualOverride) {
        set(s => ({
          tariffRegion: regionId,
          tariffManuallyOverridden: isManualOverride,
          stageState: _editTransition(s.stageState),
          acknowledgedWarnings: [],  // S1: clear all acks on meaningful edit
        }));
        _scheduleAssemble();
      },

      resetTariffToProvinceDefault() {
        // Called by useSiteMetaForm; sets tariffManuallyOverridden = false
        // The actual tariff value is set by useSiteMetaForm before calling this
        set({ tariffManuallyOverridden: false });
      },

      setLocation(loc) {
        set(s => ({
          location: loc,
          stageState: _editTransition(s.stageState),
          acknowledgedWarnings: [],  // S1: clear all acks on meaningful edit
        }));
        _scheduleAssemble();
      },

      setWeatherMode(mode) {
        set(s => ({
          weatherMode: mode,
          stageState: _editTransition(s.stageState),
          acknowledgedWarnings: [],  // S1: clear all acks on meaningful edit
        }));
        _scheduleAssemble();
      },

      addDevice(row) {
        set(s => ({
          fleet: [...s.fleet, row],
          stageState: _editTransition(s.stageState),
          acknowledgedWarnings: [],  // S1: clear all acks on meaningful edit
        }));
        _scheduleAssemble();
      },

      updateDeviceCount(index, count) {
        set(s => {
          const fleet = s.fleet.map((r, i) => i === index ? { ...r, count } : r);
          return {
            fleet,
            stageState: _editTransition(s.stageState),
            acknowledgedWarnings: [],
          };
        });
        _scheduleAssemble();
      },

      updateDeviceFleetMw(index, mw) {
        set(s => {
          const fleet = s.fleet.map((r, i) => i === index ? { ...r, fleetCapacityMw: mw } : r);
          return {
            fleet,
            stageState: _editTransition(s.stageState),
            acknowledgedWarnings: [],
          };
        });
        _scheduleAssemble();
      },

      removeDevice(index) {
        set(s => ({
          fleet: s.fleet.filter((_, i) => i !== index),
          stageState: _editTransition(s.stageState),
          acknowledgedWarnings: [],
        }));
        _scheduleAssemble();
      },

      resolveDevice(index, resolved) {
        set(s => ({
          fleet: s.fleet.map((r, i) => i === index ? { ...r, ...resolved } : r),
        }));
        // resolveDevice is not a user edit; don't schedule assemble here
        // (the addDevice already scheduled it; resolving just enriches display fields)
      },

      acknowledgeWarning(ruleId) {
        set(s => {
          const acked = [...s.acknowledgedWarnings, ruleId];
          const nowComplete = _isNowComplete(s.lastValidation, acked) && !s.validationPending;
          return {
            acknowledgedWarnings: acked,
            stageState: nowComplete ? 'COMPLETE' : s.stageState,
          };
        });
      },

      receiveValidation(result) {
        set(s => {
          const nowComplete = _isNowComplete(result, s.acknowledgedWarnings);
          return {
            lastValidation: result,
            validationPending: false,
            assembleError: null,           // clear any prior assemble error on success
            stageState: nowComplete ? 'COMPLETE' : 'IN_PROGRESS',
          };
        });
      },

      setValidationPending(pending) {
        set(s => {
          const stageState = pending
            ? (s.stageState === 'IN_PROGRESS' || s.stageState === 'STALE' || s.stageState === 'COMPLETE'
                ? 'VALIDATING'
                : s.stageState)
            : s.stageState;
          return { validationPending: pending, stageState };
        });
      },

      receiveCoverage(result) {
        set({ coverageResult: result, coveragePending: false, coverageError: null });
      },

      setCoverageError(msg) {
        set({ coverageError: msg, coveragePending: false });
      },

      setSaveInProgress(v) {
        set({ saveInProgress: v });
      },

      setSaveError(msg) {
        set({ saveError: msg });
      },

      onSaveSuccess(configHash) {
        set({ stageState: 'COMPLETE', provenanceHash: configHash, saveInProgress: false, saveError: null });
      },

      retryAssemble() {
        // B6: clear the error and re-schedule the debounced assemble call
        set({ assembleError: null });
        _scheduleAssemble();
      },

      reset() {
        _clearDebounce();
        if (_activeController) { _activeController.abort(); _activeController = null; }
        set({
          stageState:               'FIRST_VISIT',
          siteName:                 '',
          province:                 '',
          tariffRegion:             '',
          tariffManuallyOverridden: false,
          location:                 null,
          weatherMode:              'synthetic',
          fleet:                    [],
          lastValidation:           null,
          acknowledgedWarnings:     [],
          validationPending:        false,
          coveragePending:          false,
          coverageResult:           null,
          coverageError:            null,
          saveInProgress:           false,
          saveError:                null,
          assembleError:            null,
          provenanceHash:           null,
        });
      },
    }),
    {
      name: 'energygo.stage1',
      // Persist form values and validation cache; NOT pending/in-progress flags
      partialize: (state) => ({
        stageState:               state.stageState,
        siteName:                 state.siteName,
        province:                 state.province,
        tariffRegion:             state.tariffRegion,
        tariffManuallyOverridden: state.tariffManuallyOverridden,
        location:                 state.location,
        weatherMode:              state.weatherMode,
        fleet:                    state.fleet,
        scenarioBasePowerActive:  state.scenarioBasePowerActive,
        lastValidation:           state.lastValidation,
        acknowledgedWarnings:     state.acknowledgedWarnings,
        provenanceHash:           state.provenanceHash,
      }),
      // S2: if rehydrated with COMPLETE, immediately downgrade to IN_PROGRESS
      // to force a fresh assemble call on next render.
      onRehydrateStorage: () => (hydratedState) => {
        if (hydratedState && hydratedState.stageState === 'COMPLETE') {
          useStageOneStore.setState({ stageState: 'IN_PROGRESS' });
        }
      },
    },
  ),
);
