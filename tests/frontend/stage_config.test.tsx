/**
 * Tests for contracts/frontend/stage_config.md
 *
 * These tests verify:
 *  §T1  — StageOneConfig mount and initial state (FIRST_VISIT)
 *  §T2  — Stage state transitions
 *  §T3  — MapPicker: lat/lon inputs, bidirectional sync, fallback, geolocation
 *  §T4  — DeviceFleetTable: empty state, add device, autocomplete, remove, count
 *  §T5  — ScenarioComposer: base scenario always active in v1
 *  §T6  — ValidationPanel: hard errors, soft warnings, acknowledge, API failure, timing
 *  §T7  — StageSaveButton: label, aria-disabled, onClick guard
 *  §T8  — useSiteMetaForm: name length, province→tariff default, reset link
 *  §T9  — API calls: debounce rules, abort-controller race-condition guard
 *  §T10 — Continue invariants
 *  §T11 — Unhappy paths
 *  §T12 — Accessibility
 *
 * Tests FAIL until implementation — that is correct at contract+tests stage.
 *
 * Test runner: Vitest + React Testing Library (STACK.md)
 * Mock strategy: vi.fn() for fetch; fake timers for debounce assertions.
 *
 * Golden-example message for validate-telemetry: not applicable to this feature
 * (Stage ① produces a site config, not a telemetry message; no LOCKED telemetry
 * schema is consumed here).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Dynamic imports so tests fail gracefully (red-first) before implementation ──

// @vite-ignore comments below: vite:import-analysis resolves dynamic imports
// statically at transform time, which fails for not-yet-implemented modules.
// These directives let the import fall through to runtime so each test fails
// with a "module not found" error (red-first intent) rather than a transform
// error that prevents the entire test file from loading.
async function loadStageOneConfig() {
  const mod = await import(/* @vite-ignore */ "../../src/components/wizard/StageOneConfig");
  return mod.StageOneConfig;
}
async function loadMapPicker() {
  const mod = await import(/* @vite-ignore */ "../../src/components/wizard/MapPicker");
  return mod.MapPicker;
}
async function loadDeviceFleetTable() {
  const mod = await import(/* @vite-ignore */ "../../src/components/wizard/DeviceFleetTable");
  return mod.DeviceFleetTable;
}
async function loadScenarioComposer() {
  const mod = await import(/* @vite-ignore */ "../../src/components/wizard/ScenarioComposer");
  return mod.ScenarioComposer;
}
async function loadValidationPanel() {
  const mod = await import(/* @vite-ignore */ "../../src/components/wizard/ValidationPanel");
  return mod.ValidationPanel;
}
async function loadStageSaveButton() {
  const mod = await import(/* @vite-ignore */ "../../src/components/wizard/StageSaveButton");
  return mod.StageSaveButton;
}
async function loadUseSiteMetaForm() {
  const mod = await import(/* @vite-ignore */ "../../src/hooks/useSiteMetaForm");
  return mod.useSiteMetaForm;
}
async function loadTypes() {
  return await import(/* @vite-ignore */ "../../src/types/stageConfig");
}

// ── Shared API mock helpers ──

/** Minimal responses for common cases. */
// POST /api/site/assemble response shape: { site_config, errors, warnings }
const MOCK_ASSEMBLE_CLEAN = {
  site_config: { assets: { wind: { model: "vestas-v150-4.2", fleet_rated_mw: 420.0 } }, tariff_region: "cn-gansu" },
  errors: [], warnings: [],
};
const MOCK_ASSEMBLE_ERROR = {
  site_config: {},
  errors: [{ rule_id: "E-FLEET-EMPTY", field: "assets.fleet", message: "No devices in fleet", constraint: "fleet must have ≥ 1 device" }],
  warnings: [],
};
const MOCK_ASSEMBLE_WARNING = {
  site_config: {},
  errors: [],
  warnings: [{ rule_id: "W-COVERAGE-SHORT", field: "lat", message: "Historical weather: 2 yr available — short horizon", constraint: "" }],
};
// Aliases used by ValidationPanel tests (panel only cares about errors/warnings sub-objects)
const MOCK_VALIDATION_CLEAN = { errors: [], warnings: [] };
const MOCK_VALIDATION_ERROR = {
  errors: [{ rule_id: "E-FLEET-EMPTY", field: "assets.fleet", message: "No devices in fleet", constraint: "fleet must have ≥ 1 device" }],
  warnings: [],
};
const MOCK_VALIDATION_WARNING = {
  errors: [],
  warnings: [{ rule_id: "W-COVERAGE-SHORT", field: "lat", message: "Historical weather: 2 yr available — short horizon", constraint: "" }],
};
const MOCK_COVERAGE_AVAILABLE = {
  lat: 38.5, lon: 102.0,
  historical_available: true, available_year_count: 10,
  year_range: [2014, 2023], bootstrap_available: true, source: "open_meteo",
};
const MOCK_COVERAGE_UNAVAILABLE = {
  lat: 0.0, lon: -200.0,
  historical_available: false, available_year_count: 0,
  year_range: null, bootstrap_available: false, source: "open_meteo",
};
const MOCK_TARIFF_REGIONS = {
  schema_version: "1.0.0",
  regions: [
    {
      region_id: "cn-gansu", currency: "CNY",
      price_min_yuan_per_mwh: 250.0, price_max_yuan_per_mwh: 780.0,
      demand_rate_yuan_per_mw_month: 32000.0, provenance: "public",
    },
  ],
};
const MOCK_DEVICE_SEARCH_VESTAS = {
  results: [{
    model_id: "vestas-v150-4.2", type: "wind_turbine",
    label: "Wind turbine · 4.2 MW · 105m hub",
    rated_output: { value: 4.2, unit: "MW" },
  }],
};
const MOCK_DEVICE_SEARCH_EMPTY = { results: [] };

function mockFetch(overrides: Record<string, unknown> = {}) {
  return vi.fn((url: string) => {
    const urlStr = String(url);
    if (urlStr.includes("/api/site/assemble"))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.assemble ?? MOCK_ASSEMBLE_CLEAN) });
    if (urlStr.includes("/api/site/weather-coverage"))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.coverage ?? MOCK_COVERAGE_AVAILABLE) });
    if (urlStr.includes("/api/tariff/regions"))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.tariffs ?? MOCK_TARIFF_REGIONS) });
    if (urlStr.includes("/api/devices/search"))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(overrides.search ?? MOCK_DEVICE_SEARCH_VESTAS) });
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  });
}

// ── Suite 1: StageOneConfig — mount + initial state ──

describe("§T1 StageOneConfig: mount and FIRST_VISIT initial state", () => {
  it("renders the root data-testid", async () => {
    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);
    expect(screen.getByTestId("stage-one-config")).toBeTruthy();
  });

  it("renders left and right layout columns", async () => {
    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);
    expect(screen.getByTestId("stage-one-left")).toBeTruthy();
    expect(screen.getByTestId("stage-one-right")).toBeTruthy();
  });

  it("renders the footer section", async () => {
    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);
    expect(screen.getByTestId("stage-one-footer")).toBeTruthy();
  });

  it("Continue button is disabled in FIRST_VISIT state", async () => {
    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);
    const btn = screen.getByTestId("stage-save-btn");
    // Must not be enabled (aria-disabled=true per §T-SAVE-1)
    expect(btn).toHaveAttribute("aria-disabled", "true");
  });

  it("Back button is not an interactive button element on Stage ①", async () => {
    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);
    const back = screen.getByText(/← Back/i);
    // Must be a span/div, not <button> — §T-A11Y-6
    expect(back.tagName.toLowerCase()).not.toBe("button");
  });
});

// ── Suite 2: Stage state machine ──

describe("§T2 Stage state machine", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    globalThis.fetch = mockFetch();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("transitions FIRST_VISIT → IN_PROGRESS on first fleet add", async () => {
    // This tests that any edit moves the stage out of FIRST_VISIT
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const state = useStageOneStore.getState();
    expect(state.stageState).toBe("FIRST_VISIT");
    await act(async () => {
      state.addDevice({ id: "vestas-v150-4.2", count: 1 });
    });
    expect(useStageOneStore.getState().stageState).toBe("IN_PROGRESS");
  });

  it("transitions to VALIDATING while debounce request is in flight", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const state = useStageOneStore.getState();
    await act(async () => {
      state.addDevice({ id: "vestas-v150-4.2", count: 1 });
      // Before 300ms debounce fires:
      state.setValidationPending(true);
    });
    expect(useStageOneStore.getState().stageState).toBe("VALIDATING");
  });

  it("reaches COMPLETE after clean validation with no unack'd warnings", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const state = useStageOneStore.getState();
    await act(async () => {
      state.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      state.setLocation({ lat: 38.5, lon: 102.0 });
      state.receiveValidation(MOCK_VALIDATION_CLEAN);
    });
    expect(useStageOneStore.getState().stageState).toBe("COMPLETE");
  });

  it("stays IN_PROGRESS after validation returns errors", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const state = useStageOneStore.getState();
    await act(async () => {
      state.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      state.receiveValidation(MOCK_VALIDATION_ERROR);
    });
    expect(useStageOneStore.getState().stageState).toBe("IN_PROGRESS");
  });

  it("stays IN_PROGRESS after validation returns unacknowledged warning", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const state = useStageOneStore.getState();
    await act(async () => {
      state.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      state.receiveValidation(MOCK_VALIDATION_WARNING);
    });
    expect(useStageOneStore.getState().stageState).toBe("IN_PROGRESS");
  });

  it("reaches COMPLETE after warning is acknowledged", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const state = useStageOneStore.getState();
    await act(async () => {
      state.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      state.receiveValidation(MOCK_VALIDATION_WARNING);
      state.acknowledgeWarning("W-COVERAGE-SHORT");
    });
    expect(useStageOneStore.getState().stageState).toBe("COMPLETE");
  });

  it("transitions COMPLETE → STALE on any subsequent field edit", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const state = useStageOneStore.getState();
    await act(async () => {
      state.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      state.receiveValidation(MOCK_VALIDATION_CLEAN);
    });
    expect(useStageOneStore.getState().stageState).toBe("COMPLETE");
    await act(async () => {
      state.setLocation({ lat: 39.0, lon: 103.0 });
    });
    expect(useStageOneStore.getState().stageState).toBe("STALE");
  });
});

// ── Suite 3: MapPicker ──

describe("§T3 MapPicker", () => {
  it("[T-MAP-1] empty lat/lon: inputs are empty and map centered on China", async () => {
    const MapPicker = await loadMapPicker();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    const latInput = screen.getByTestId("lat-input") as HTMLInputElement;
    const lonInput = screen.getByTestId("lon-input") as HTMLInputElement;
    expect(latInput.value).toBe("");
    expect(lonInput.value).toBe("");
  });

  it("[T-MAP-3] typing lat calls onLatLonChange with parsed value", async () => {
    const MapPicker = await loadMapPicker();
    const onLatLonChange = vi.fn();
    render(
      <MapPicker
        latLon={{ lat: 38.0, lon: 102.0 }}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={onLatLonChange}
        onWeatherModeChange={vi.fn()}
      />
    );
    const latInput = screen.getByTestId("lat-input");
    await userEvent.clear(latInput);
    await userEvent.type(latInput, "39.5");
    fireEvent.blur(latInput);
    expect(onLatLonChange).toHaveBeenCalledWith({ lat: 39.5, lon: 102.0 });
  });

  it("[T-MAP-4] map tile failure renders fallback and keeps inputs enabled", async () => {
    const MapPicker = await loadMapPicker();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
        simulateTileError={true}   // test-only prop to trigger tile failure path
      />
    );
    expect(screen.getByTestId("map-tile-error")).toHaveTextContent(
      "Map tiles unavailable — enter coordinates manually."
    );
    const latInput = screen.getByTestId("lat-input");
    expect(latInput).not.toBeDisabled();
  });

  it("[T-MAP-5] geolocation success calls onLatLonChange; denial shows toast", async () => {
    const MapPicker = await loadMapPicker();
    vi.useFakeTimers();

    // Geolocation success
    const mockGeolocation = {
      getCurrentPosition: vi.fn((success) =>
        success({ coords: { latitude: 40.0, longitude: 105.0 } })
      ),
    };
    Object.defineProperty(globalThis, "navigator", {
      value: { geolocation: mockGeolocation }, configurable: true,
    });

    const onLatLonChange = vi.fn();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={onLatLonChange}
        onWeatherModeChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("use-my-location"));
    expect(onLatLonChange).toHaveBeenCalledWith({ lat: 40.0, lon: 105.0 });

    // Geolocation failure
    mockGeolocation.getCurrentPosition = vi.fn((_success, error) =>
      error(new Error("denied"))
    );
    const onLatLonChange2 = vi.fn();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={onLatLonChange2}
        onWeatherModeChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("use-my-location"));
    expect(screen.getByTestId("location-toast")).toHaveTextContent("Location unavailable");
    expect(onLatLonChange2).not.toHaveBeenCalled();
    // Toast auto-dismisses after 4s
    await act(async () => { vi.advanceTimersByTime(4100); });
    expect(screen.queryByTestId("location-toast")).toBeNull();

    vi.useRealTimers();
  });

  it("[T-MAP-6] Historical radio enabled ONLY when coverage.historical_available === true", async () => {
    // should-fix #6: T-MAP-6/7 wording tightened — disabled in all non-true states.
    const MapPicker = await loadMapPicker();

    // Case 1: coverage.historical_available === false → disabled
    const { rerender } = render(
      <MapPicker
        latLon={{ lat: 0, lon: -200 }}
        weatherMode="synthetic"
        coverage={MOCK_COVERAGE_UNAVAILABLE}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("weather-mode-historical")).toBeDisabled();

    // Case 2: coverage === null → disabled (no data yet)
    rerender(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("weather-mode-historical")).toBeDisabled();

    // Case 3: coveragePending → disabled (checked by T-MAP-8)
    // Case 4: coverageError set → disabled (pinned by T-MAP-COV-ERR)

    // Case 5: historical_available === true → enabled
    rerender(
      <MapPicker
        latLon={{ lat: 38.5, lon: 102.0 }}
        weatherMode="synthetic"
        coverage={MOCK_COVERAGE_AVAILABLE}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("weather-mode-historical")).not.toBeDisabled();
  });

  it("[T-MAP-7] Bootstrap radio enabled ONLY when coverage.bootstrap_available === true", async () => {
    // should-fix #6: symmetric to T-MAP-6.
    const MapPicker = await loadMapPicker();

    // coverage.bootstrap_available === false → disabled
    const { rerender } = render(
      <MapPicker
        latLon={{ lat: 0, lon: -200 }}
        weatherMode="synthetic"
        coverage={MOCK_COVERAGE_UNAVAILABLE}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("weather-mode-bootstrap")).toBeDisabled();

    // coverage === null → disabled
    rerender(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("weather-mode-bootstrap")).toBeDisabled();

    // bootstrap_available === true → enabled
    rerender(
      <MapPicker
        latLon={{ lat: 38.5, lon: 102.0 }}
        weatherMode="synthetic"
        coverage={MOCK_COVERAGE_AVAILABLE}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("weather-mode-bootstrap")).not.toBeDisabled();
  });

  it("[T-MAP-8] coverage-spinner shown when coveragePending is true", async () => {
    const MapPicker = await loadMapPicker();
    render(
      <MapPicker
        latLon={{ lat: 38.5, lon: 102.0 }}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={true}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("coverage-spinner")).toBeTruthy();
    // Both non-synthetic radios disabled while pending
    expect(screen.getByTestId("weather-mode-historical")).toBeDisabled();
    expect(screen.getByTestId("weather-mode-bootstrap")).toBeDisabled();
  });

  it("[T-MAP-9] accepts N/S suffix on lat, E/W suffix on lon", async () => {
    const MapPicker = await loadMapPicker();
    const onLatLonChange = vi.fn();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={onLatLonChange}
        onWeatherModeChange={vi.fn()}
      />
    );
    const latInput = screen.getByTestId("lat-input");
    const lonInput = screen.getByTestId("lon-input");
    await userEvent.type(latInput, "38S");
    fireEvent.blur(latInput);
    await userEvent.type(lonInput, "102W");
    fireEvent.blur(lonInput);
    expect(onLatLonChange).toHaveBeenLastCalledWith({ lat: -38, lon: -102 });
  });

  it("[T-MAP-10] lat out of range shows error and does not call onLatLonChange", async () => {
    const MapPicker = await loadMapPicker();
    const onLatLonChange = vi.fn();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={onLatLonChange}
        onWeatherModeChange={vi.fn()}
      />
    );
    const latInput = screen.getByTestId("lat-input");
    await userEvent.type(latInput, "95");
    fireEvent.blur(latInput);
    expect(screen.getByTestId("lat-range-error")).toBeTruthy();
    expect(onLatLonChange).not.toHaveBeenCalled();
  });
});

// ── Suite 4: DeviceFleetTable ──

describe("§T4 DeviceFleetTable", () => {
  it("[T-FLEET-1] empty fleet shows empty state with Add button", async () => {
    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("fleet-empty-state")).toHaveTextContent("No devices added yet.");
    expect(screen.getByTestId("fleet-add-btn")).toBeTruthy();
  });

  it("[T-FLEET-2] clicking Add opens inline add form", async () => {
    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    expect(screen.getByTestId("fleet-add-form")).toBeTruthy();
    expect(screen.getByTestId("fleet-add-id")).toBeTruthy();
    expect(screen.getByTestId("fleet-add-count")).toBeTruthy();
    expect(screen.getByTestId("fleet-add-confirm")).toBeTruthy();
    expect(screen.getByTestId("fleet-add-cancel")).toBeTruthy();
  });

  it("[T-FLEET-3] typing in device ID fires debounced search (200ms)", async () => {
    vi.useFakeTimers();
    globalThis.fetch = mockFetch();

    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    const idInput = screen.getByTestId("fleet-add-id");
    await userEvent.type(idInput, "vest");
    // Before debounce fires: fetch not yet called
    expect(globalThis.fetch).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(250); });
    // After 200ms debounce: fetch called with correct URL
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/devices/search?q=vest")
    );
    vi.useRealTimers();
  });

  it("[T-FLEET-4] dropdown shows model_id and label from search results", async () => {
    vi.useFakeTimers();
    globalThis.fetch = mockFetch();

    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    const idInput = screen.getByTestId("fleet-add-id");
    await userEvent.type(idInput, "vestas");
    await act(async () => { vi.advanceTimersByTime(250); });
    await waitFor(() => {
      const dropdown = screen.getByTestId("fleet-add-dropdown");
      expect(dropdown).toHaveTextContent("vestas-v150-4.2");
      expect(dropdown).toHaveTextContent("Wind turbine · 4.2 MW · 105m hub");
    });
    vi.useRealTimers();
  });

  it("[T-FLEET-5] Add confirm disabled while search in flight", async () => {
    vi.useFakeTimers();
    // Make fetch hang
    globalThis.fetch = vi.fn(() => new Promise(() => {}));

    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    await userEvent.type(screen.getByTestId("fleet-add-id"), "v");
    await act(async () => { vi.advanceTimersByTime(250); });
    // Fetch in flight → confirm disabled
    expect(screen.getByTestId("fleet-add-confirm")).toBeDisabled();
    vi.useRealTimers();
  });

  it("[T-FLEET-6] Add confirm with valid ID calls onAdd with resolved data", async () => {
    vi.useFakeTimers();
    globalThis.fetch = mockFetch();

    const onAdd = vi.fn();
    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={onAdd}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    await userEvent.type(screen.getByTestId("fleet-add-id"), "vestas-v150-4.2");
    await act(async () => { vi.advanceTimersByTime(250); });
    await waitFor(() => screen.getByTestId("fleet-add-dropdown"));
    await userEvent.click(screen.getByText("vestas-v150-4.2"));  // select from dropdown
    await userEvent.click(screen.getByTestId("fleet-add-confirm"));

    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ id: "vestas-v150-4.2", count: 1, valid: true })
    );
    vi.useRealTimers();
  });

  it("[T-FLEET-7] unknown device ID shows inline error", async () => {
    vi.useFakeTimers();
    globalThis.fetch = mockFetch({ search: MOCK_DEVICE_SEARCH_EMPTY });

    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    await userEvent.type(screen.getByTestId("fleet-add-id"), "my-turbine");
    await act(async () => { vi.advanceTimersByTime(250); });
    await waitFor(() => {
      const err = screen.getByTestId("fleet-id-error");
      expect(err).toHaveTextContent('"my-turbine" not found in device library');
    });
    vi.useRealTimers();
  });

  it("[T-FLEET-8] fleet rows render with device ID, type icon, count, remove button", async () => {
    const DeviceFleetTable = await loadDeviceFleetTable();
    const fleet = [
      { id: "vestas-v150-4.2", count: 100, type: "wind_turbine" as const, label: "Wind turbine · 4.2 MW", valid: true },
    ];
    render(
      <DeviceFleetTable
        fleet={fleet}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    expect(screen.getByTestId("fleet-row-0")).toBeTruthy();
    expect(screen.getByTestId("fleet-row-count-0")).toBeTruthy();
    expect(screen.getByTestId("fleet-row-remove-0")).toBeTruthy();
    expect(screen.getByTestId("fleet-row-0")).toHaveTextContent("vestas-v150-4.2");
  });

  it("[T-FLEET-9] count input clamps to [1, 999] on blur", async () => {
    const DeviceFleetTable = await loadDeviceFleetTable();
    const onCountChange = vi.fn();
    const fleet = [
      { id: "vestas-v150-4.2", count: 10, type: "wind_turbine" as const, label: "Wind turbine", valid: true },
    ];
    render(
      <DeviceFleetTable
        fleet={fleet}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={onCountChange}
      />
    );
    const countInput = screen.getByTestId("fleet-row-count-0");
    await userEvent.clear(countInput);
    await userEvent.type(countInput, "0");
    fireEvent.blur(countInput);
    // Count 0 is out of range; onCountChange should NOT be called with 0
    expect(onCountChange).not.toHaveBeenCalledWith(0, 0);
    // Instead clamped to 1
    expect(onCountChange).toHaveBeenCalledWith(0, 1);
  });

  it("[T-FLEET-10] remove button calls onRemove with correct index", async () => {
    const DeviceFleetTable = await loadDeviceFleetTable();
    const onRemove = vi.fn();
    const fleet = [
      { id: "vestas-v150-4.2", count: 100, type: "wind_turbine" as const, label: "Wind turbine", valid: true },
      { id: "catl-lmp-300mwh", count: 1, type: "battery" as const, label: "Battery · 300 MWh", valid: true },
    ];
    render(
      <DeviceFleetTable fleet={fleet} onAdd={vi.fn()} onRemove={onRemove} onCountChange={vi.fn()} onFleetMwChange={vi.fn()} />
    );
    await userEvent.click(screen.getByTestId("fleet-row-remove-1"));
    expect(onRemove).toHaveBeenCalledWith(1);
  });

  it("[T-FLEET-11] site totals strip is rendered (placeholder '—' before site_resolve.md lands)", async () => {
    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable fleet={[]} onAdd={vi.fn()} onRemove={vi.fn()} onCountChange={vi.fn()} onFleetMwChange={vi.fn()} />
    );
    expect(screen.getByTestId("fleet-totals")).toBeTruthy();
    // Before site_resolve.md, totals show "—"
    expect(screen.getByTestId("fleet-totals")).toHaveTextContent("—");
  });
});

// ── Suite 5: ScenarioComposer ──

describe("§T5 ScenarioComposer", () => {
  it("[T-SCENARIO-1] base power scenario is shown checked and non-interactive", async () => {
    const ScenarioComposer = await loadScenarioComposer();
    render(<ScenarioComposer scenarioBasePowerActive={true} />);
    const baseRow = screen.getByTestId("scenario-base-power");
    expect(baseRow).toHaveAttribute("aria-checked", "true");
    expect(baseRow).toHaveAttribute("aria-disabled", "true");
  });

  it("[T-SCENARIO-2] no other scenario rows in v1", async () => {
    const ScenarioComposer = await loadScenarioComposer();
    const { container } = render(<ScenarioComposer scenarioBasePowerActive={true} />);
    const allScenarioRows = container.querySelectorAll("[data-testid^='scenario-']");
    // Only base power row
    expect(allScenarioRows).toHaveLength(1);
  });

  it("[T-SCENARIO-3] base scenario label text is correct", async () => {
    const ScenarioComposer = await loadScenarioComposer();
    render(<ScenarioComposer scenarioBasePowerActive={true} />);
    const baseRow = screen.getByTestId("scenario-base-power");
    expect(baseRow).toHaveTextContent("Power supply");
    expect(baseRow).toHaveTextContent("base — always active");
  });
});

// ── Suite 6: ValidationPanel ──

describe("§T6 ValidationPanel", () => {
  it("[T-VAL-1] pending shows Checking...", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={null}
        pending={true}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByTestId("validation-loading")).toHaveTextContent("Checking...");
  });

  it("[T-VAL-2] hard errors rendered as role=alert with message text", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_ERROR}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    const errorEl = screen.getByTestId("validation-error-E-FLEET-EMPTY");
    expect(errorEl).toBeTruthy();
    expect(errorEl).toHaveTextContent("No devices in fleet");
    expect(errorEl).toHaveAttribute("role", "alert");
  });

  it("[T-VAL-3] unacknowledged warnings show Acknowledge button", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_WARNING}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByTestId("validation-warning-W-COVERAGE-SHORT")).toBeTruthy();
    expect(screen.getByTestId("validation-ack-W-COVERAGE-SHORT")).toBeTruthy();
  });

  it("[T-VAL-4] clicking Acknowledge calls onAcknowledge with rule_id", async () => {
    const ValidationPanel = await loadValidationPanel();
    const onAck = vi.fn();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_WARNING}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={onAck}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("validation-ack-W-COVERAGE-SHORT"));
    expect(onAck).toHaveBeenCalledWith("W-COVERAGE-SHORT");
  });

  it("[T-VAL-5] acknowledged warnings show struck-through state without Acknowledge button", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_WARNING}
        pending={false}
        acknowledgedWarnings={["W-COVERAGE-SHORT"]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByTestId("validation-acked-W-COVERAGE-SHORT")).toBeTruthy();
    expect(screen.queryByTestId("validation-ack-W-COVERAGE-SHORT")).toBeNull();
  });

  it("[T-VAL-6] clean state shows '✓ Configuration valid'", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_CLEAN}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByTestId("validation-clean")).toHaveTextContent("✓ Configuration valid");
  });

  it("[T-VAL-7] API error shows retry UI; clicking Retry calls onRetry", async () => {
    const ValidationPanel = await loadValidationPanel();
    const onRetry = vi.fn();
    render(
      <ValidationPanel
        result={null}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError="Network error"
        onRetry={onRetry}
      />
    );
    const errEl = screen.getByTestId("validation-api-error");
    expect(errEl).toHaveTextContent("Validation unavailable — check connection");
    await userEvent.click(screen.getByTestId("validation-retry"));
    expect(onRetry).toHaveBeenCalled();
  });

  it("[T-VAL-8] pending > 2000ms shows 'Still checking…' message", async () => {
    vi.useFakeTimers();
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={null}
        pending={true}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    expect(screen.queryByTestId("validation-still-checking")).toBeNull();
    await act(async () => { vi.advanceTimersByTime(2100); });
    expect(screen.getByTestId("validation-still-checking")).toHaveTextContent("Still checking…");
    vi.useRealTimers();
  });
});

// ── Suite 7: StageSaveButton ──

describe("§T7 StageSaveButton", () => {
  it("[T-SAVE-1] aria-disabled when state is not COMPLETE or STALE", async () => {
    const StageSaveButton = await loadStageSaveButton();
    for (const state of ["FIRST_VISIT", "IN_PROGRESS", "VALIDATING"] as const) {
      const { unmount } = render(
        <StageSaveButton stageState={state} saveInProgress={false} onClick={vi.fn()} />
      );
      expect(screen.getByTestId("stage-save-btn")).toHaveAttribute("aria-disabled", "true");
      unmount();
    }
  });

  it("[T-SAVE-2] saving state shows 'Saving… ⟳' and is aria-disabled", async () => {
    const StageSaveButton = await loadStageSaveButton();
    render(
      <StageSaveButton stageState="COMPLETE" saveInProgress={true} onClick={vi.fn()} />
    );
    const btn = screen.getByTestId("stage-save-btn");
    expect(btn).toHaveTextContent("Saving…");
    expect(btn).toHaveAttribute("aria-disabled", "true");
  });

  it("[T-SAVE-3] STALE state shows 'Save & Update →'", async () => {
    const StageSaveButton = await loadStageSaveButton();
    render(
      <StageSaveButton stageState="STALE" saveInProgress={false} onClick={vi.fn()} />
    );
    expect(screen.getByTestId("stage-save-btn")).toHaveTextContent("Save & Update →");
  });

  it("[T-SAVE-4] COMPLETE state shows 'Save & Continue →'", async () => {
    const StageSaveButton = await loadStageSaveButton();
    render(
      <StageSaveButton stageState="COMPLETE" saveInProgress={false} onClick={vi.fn()} />
    );
    expect(screen.getByTestId("stage-save-btn")).toHaveTextContent("Save & Continue →");
  });

  it("[T-SAVE-5] COMPLETE and STALE states call onClick(); IN_PROGRESS does not", async () => {
    // should-fix #3: directly test STALE-click in this suite (T-S1-STALE-CLICK in §T15 also pins it).
    const StageSaveButton = await loadStageSaveButton();
    const onClick = vi.fn();
    const { rerender } = render(
      <StageSaveButton stageState="COMPLETE" saveInProgress={false} onClick={onClick} />
    );
    await userEvent.click(screen.getByTestId("stage-save-btn"));
    expect(onClick).toHaveBeenCalledTimes(1);  // COMPLETE → 1 call

    rerender(
      <StageSaveButton stageState="STALE" saveInProgress={false} onClick={onClick} />
    );
    await userEvent.click(screen.getByTestId("stage-save-btn"));
    expect(onClick).toHaveBeenCalledTimes(2);  // STALE → 2nd call

    rerender(
      <StageSaveButton stageState="IN_PROGRESS" saveInProgress={false} onClick={onClick} />
    );
    await userEvent.click(screen.getByTestId("stage-save-btn"));
    // Still only 2 calls (IN_PROGRESS does not fire onClick)
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});

// ── Suite 8: useSiteMetaForm ──

describe("§T8 useSiteMetaForm", () => {
  it("[T-META-1] siteNameError non-null when name > 64 chars", async () => {
    // Invoke hook in isolation using a renderHook-like approach
    const { renderHook } = await import("@testing-library/react");
    const { useSiteMetaForm } = await import("../../src/hooks/useSiteMetaForm");
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();

    const { result } = renderHook(() => useSiteMetaForm(store));
    act(() => { result.current.setSiteName("x".repeat(65)); });
    expect(result.current.siteNameError).not.toBeNull();
    act(() => { result.current.setSiteName("Short name"); });
    expect(result.current.siteNameError).toBeNull();
  });

  it("[T-META-2] province change auto-updates tariff when not manually overridden", async () => {
    const { renderHook } = await import("@testing-library/react");
    const { useSiteMetaForm } = await import("../../src/hooks/useSiteMetaForm");
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();

    const { result } = renderHook(() => useSiteMetaForm(store));
    act(() => { result.current.setProvince("Gansu"); });
    // tariffRegion auto-set to province default (cn-gansu)
    expect(result.current.tariffRegion).toBe("cn-gansu");
  });

  it("[T-META-3] province change does NOT auto-update tariff if manually overridden", async () => {
    const { renderHook } = await import("@testing-library/react");
    const { useSiteMetaForm } = await import("../../src/hooks/useSiteMetaForm");
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();

    const { result } = renderHook(() => useSiteMetaForm(store));
    // Set manual override first
    act(() => { result.current.setTariffRegion("cn-gansu", true); });
    // Then change province
    act(() => { result.current.setProvince("Sichuan"); });
    // tariff should remain cn-gansu; reset link should show
    expect(result.current.tariffRegion).toBe("cn-gansu");
    expect(result.current.showTariffResetLink).toBe(true);
  });

  it("[T-META-4] resetTariffToProvinceDefault clears override and resets tariff", async () => {
    const { renderHook } = await import("@testing-library/react");
    const { useSiteMetaForm } = await import("../../src/hooks/useSiteMetaForm");
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();

    const { result } = renderHook(() => useSiteMetaForm(store));
    act(() => { result.current.setProvince("Gansu"); });
    act(() => { result.current.setTariffRegion("cn-gansu", true); });
    act(() => { result.current.resetTariffToProvinceDefault(); });
    expect(result.current.tariffManuallyOverridden).toBe(false);
    expect(result.current.showTariffResetLink).toBe(false);
  });

  it("[T-META-5] availableTariffs populated from GET /api/tariff/regions on mount", async () => {
    vi.useFakeTimers();
    globalThis.fetch = mockFetch();
    const { renderHook, act: actHook } = await import("@testing-library/react");
    const { useSiteMetaForm } = await import("../../src/hooks/useSiteMetaForm");
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();

    const { result } = renderHook(() => useSiteMetaForm(store));
    expect(result.current.tariffsLoading).toBe(true);
    await actHook(async () => { vi.runAllTimers(); await Promise.resolve(); });
    await waitFor(() => {
      expect(result.current.availableTariffs.length).toBeGreaterThan(0);
      expect(result.current.availableTariffs[0].region_id).toBe("cn-gansu");
    });
    vi.useRealTimers();
  });
});

// ── Suite 9: API calls (debounce + race condition guard) ──

describe("§T9 API call debounce and race-condition guard", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("[T-API-VAL-1] assemble fires 300ms after last fleet change (with tariffRegion set), not before", async () => {
    globalThis.fetch = mockFetch();
    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);

    // Simulate a fleet add + tariff selection (both required for assemble to fire)
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    await act(async () => {
      useStageOneStore.getState().setTariffRegion("cn-gansu", false);
      useStageOneStore.getState().addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
    });

    // Not yet fired (before 300ms debounce)
    await act(async () => { vi.advanceTimersByTime(200); });
    const callsBefore = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([url]) => String(url).includes("/api/site/assemble")
    ).length;
    expect(callsBefore).toBe(0);

    // After 300ms debounce: POST /api/site/assemble should have fired
    await act(async () => { vi.advanceTimersByTime(150); });
    const callsAfter = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([url]) => String(url).includes("/api/site/assemble")
    ).length;
    expect(callsAfter).toBe(1);
  });

  it("[T-API-VAL-2] assemble body is raw wizard form — no client-side MW arithmetic (D37)", async () => {
    // D37: body is a flat wizard form sent to /api/site/assemble. The server computes
    // fleet MW/MWh from the device library. No category-keyed assets dict, no (12,24) table.
    //
    // Fleet entries by type (contract §5.1):
    //   wind_turbine:  { model_id, count } — server × rated_mw_per_unit
    //   pv_panel:      { model_id, fleet_capacity_mw } — direct MW, no count
    //   battery:       { model_id, count } — server × MWh/MW per unit
    //   grid:          { model_id }
    // tariff_region: "cn-gansu" (string, NOT inline price table)
    // site_meta: { lat, lon, weather_mode } (optional lat/lon per F1)

    let capturedBody: Record<string, unknown> | null = null;

    globalThis.fetch = vi.fn((url: string, options?: RequestInit) => {
      if (String(url).includes("/api/site/assemble")) {
        capturedBody = JSON.parse((options?.body as string) ?? "{}");
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_ASSEMBLE_CLEAN) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);

    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    await act(async () => { useStageOneStore.getState().reset(); });

    await act(async () => {
      // Set tariff region (required guard)
      useStageOneStore.getState().setTariffRegion("cn-gansu", false);
      // Set location (optional per F1 — included when present)
      useStageOneStore.getState().setLocation({ lat: 38.0, lon: 102.0 });

      // Wind turbine: count-based (server × 4.2 MW, no client arithmetic)
      useStageOneStore.getState().addDevice({
        id: "vestas-v150-4.2", count: 100,
        type: "wind_turbine", label: "Wind turbine · 4.2 MW · 105m hub", valid: true,
        physics: { rated_mw_per_unit: 4.2 },  // display-only; NOT used in body
      });
      // PV: direct fleet_capacity_mw (no count, no panel_mw_per_unit)
      useStageOneStore.getState().addDevice({
        id: "trina-vertex-n-670w", fleetCapacityMw: 330.0,
        type: "pv_panel", label: "Trina Vertex N 670W", valid: true,
      });
      // Battery: count-based
      useStageOneStore.getState().addDevice({
        id: "catl-lmp-300mwh", count: 1,
        type: "battery", label: "Battery · 300 MWh / 100 MW", valid: true,
        physics: { capacity_mwh_per_unit: 300.0, power_mw_per_unit: 100.0 },  // display-only
      });
      // Invalid device must be excluded from body (valid !== true)
      useStageOneStore.getState().addDevice({
        id: "unknown-device", count: 5,
        type: "wind_turbine", valid: false,
      });

      vi.advanceTimersByTime(350);  // fire 300ms debounce
    });

    await waitFor(() => expect(capturedBody).not.toBeNull());

    const body = capturedBody as {
      fleet: Array<Record<string, unknown>>;
      tariff_region: string;
      site_meta: Record<string, unknown>;
    };

    // ── fleet is an ARRAY of per-type entries (NOT a category-keyed assets dict) ──
    expect(Array.isArray(body.fleet)).toBe(true);

    // Wind entry: { model_id, count } — NO fleet_rated_mw (server computes it)
    const windEntry = body.fleet.find(e => e.model_id === "vestas-v150-4.2");
    expect(windEntry).toBeDefined();
    expect(windEntry!.count).toBe(100);
    expect(windEntry!.fleet_capacity_mw).toBeUndefined();  // must NOT appear for wind
    expect(windEntry!.fleet_rated_mw).toBeUndefined();     // no client-computed MW

    // PV entry: { model_id, fleet_capacity_mw } — NO count
    const pvEntry = body.fleet.find(e => e.model_id === "trina-vertex-n-670w");
    expect(pvEntry).toBeDefined();
    expect(pvEntry!.fleet_capacity_mw).toBe(330.0);  // MW direct — no panel_mw_per_unit in schema
    expect(pvEntry!.count).toBeUndefined();           // must NOT appear for PV

    // Battery entry: { model_id, count }
    const battEntry = body.fleet.find(e => e.model_id === "catl-lmp-300mwh");
    expect(battEntry).toBeDefined();
    expect(battEntry!.count).toBe(1);
    expect(battEntry!.fleet_capacity_mwh).toBeUndefined();  // server computes this

    // tariff_region: string (NOT inline price table)
    expect(body.tariff_region).toBe("cn-gansu");
    expect((body as Record<string, unknown>).site_config).toBeUndefined();  // raw form, not site_config

    // site_meta includes lat/lon and weather_mode
    expect(body.site_meta.lat).toBe(38.0);
    expect(body.site_meta.lon).toBe(102.0);
    expect(body.site_meta.weather_mode).toBe("synthetic");

    // Invalid device excluded
    const invalidEntry = body.fleet.find(e => e.model_id === "unknown-device");
    expect(invalidEntry).toBeUndefined();
  });

  it("[T-API-COV-1] coverage fires 500ms after lat/lon change; Historical disabled while pending", async () => {
    globalThis.fetch = mockFetch();
    const MapPicker = await loadMapPicker();
    render(
      <MapPicker
        latLon={{ lat: 38.0, lon: 102.0 }}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={true}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    // While pending, Historical is disabled
    expect(screen.getByTestId("weather-mode-historical")).toBeDisabled();
  });

  it("[T-API-SEARCH-1] Add confirm disabled while search in flight", async () => {
    // Same as T-FLEET-5 — re-tested here under the API section for coverage clarity
    globalThis.fetch = vi.fn(() => new Promise(() => {}));  // never resolves
    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable fleet={[]} onAdd={vi.fn()} onRemove={vi.fn()} onCountChange={vi.fn()} onFleetMwChange={vi.fn()} />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    await userEvent.type(screen.getByTestId("fleet-add-id"), "x");
    await act(async () => { vi.advanceTimersByTime(250); });
    expect(screen.getByTestId("fleet-add-confirm")).toBeDisabled();
  });

  it("[T-API-RACE-1] stale validation response is discarded (only latest applies)", async () => {
    // We simulate two rapid validation cycles; only the second (latest) response
    // updates state, and the first in-flight request is aborted and discarded.
    //
    // # reviewer: ORIGINAL TEST WAS BROKEN (timed out, never exercised the guard).
    // # reviewer: It added devices WITHOUT `valid: true` and NEVER set tariffRegion,
    // # reviewer: so the §5.1 assemble guard `validCount > 0 && tariffRegion !== ''`
    // # reviewer: was never met → `_scheduleAssemble` returned early (stageOneStore.ts
    // # reviewer: L67) → no debounce timer, no fetch, no in-flight request → `firstAborted`
    // # reviewer: could never become true. This is a TEST setup/timing bug, NOT an
    // # reviewer: implementation race-guard gap: the store aborts the active controller
    // # reviewer: on every meaningful change and discards AbortError responses
    // # reviewer: (_scheduleAssemble L65 + catch L98), which is contract-§5.1-compliant.
    // # reviewer: (The engineer's proposed reorder-only fix would ALSO have timed out
    // # reviewer: for the same guard reason.) Corrected to (a) satisfy the guard,
    // # reviewer: (b) drive request #1 genuinely in-flight before the 2nd change aborts
    // # reviewer: it, and (c) STRENGTHEN coverage: assert the latest (clean) response —
    // # reviewer: not the stale one — is what lands in the store.
    // # reviewer: — frontend-reviewer, PR #102 impl review, 2026-06-13
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();
    // # reviewer: reset clears the module-singleton debounce timer + controller and any
    // # reviewer: fleet left over from earlier §T9 tests (the original test relied on
    // # reviewer: undefined cross-test store state — another latent bug).
    await act(async () => { store.reset(); });

    let firstAborted = false;
    let callCount = 0;
    globalThis.fetch = vi.fn((_url, { signal }: { signal: AbortSignal }) => {
      callCount++;
      if (callCount === 1) {
        // First (stale) request: never resolves on its own; on abort it rejects with an
        // AbortError, exercising the store's stale-response discard branch (catch L98).
        return new Promise((_res, reject) => {
          signal.addEventListener("abort", () => {
            firstAborted = true;
            const e = new Error("aborted");
            (e as Error).name = "AbortError";
            reject(e);
          });
        });
      }
      // Second (latest) request: returns clean validation.
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_VALIDATION_CLEAN) });
    });

    // Guard (§5.1): a tariff region AND ≥ 1 valid device are required for assemble to fire.
    await act(async () => {
      store.setTariffRegion("cn-gansu", false);
      store.addDevice({ id: "dev-1", count: 1, valid: true });
    });
    // Fire the first debounce (300 ms) → request #1 goes in flight.
    await act(async () => { vi.advanceTimersByTime(350); });
    expect(callCount).toBe(1);

    // A new meaningful change aborts the in-flight request #1 and starts a fresh cycle.
    await act(async () => { store.addDevice({ id: "dev-2", count: 1, valid: true }); });
    expect(firstAborted).toBe(true);   // stale request #1 was aborted

    // Fire the second debounce → request #2 (latest) returns clean.
    await act(async () => { vi.advanceTimersByTime(350); });
    await waitFor(() => {
      expect(callCount).toBe(2);
      // Only the LATEST response is applied — store holds the clean result, not the stale one.
      expect(useStageOneStore.getState().lastValidation).toEqual(MOCK_VALIDATION_CLEAN);
    });
  });
});

// ── Suite 10: Continue invariants ──

describe("§T10 Continue invariants", () => {
  it("[T-CONTINUE-1] StageSaveButton enabled only in COMPLETE state", async () => {
    const StageSaveButton = await loadStageSaveButton();
    const states = ["FIRST_VISIT", "IN_PROGRESS", "VALIDATING", "COMPLETE", "STALE"] as const;
    for (const state of states) {
      const { unmount } = render(
        <StageSaveButton stageState={state} saveInProgress={false} onClick={vi.fn()} />
      );
      const btn = screen.getByTestId("stage-save-btn");
      if (state === "COMPLETE" || state === "STALE") {
        // Both COMPLETE and STALE should be enabled
        expect(btn.getAttribute("aria-disabled")).toBe("false");
      } else {
        expect(btn.getAttribute("aria-disabled")).toBe("true");
      }
      unmount();
    }
  });

  it("[T-CONTINUE-2] COMPLETE requires: lastValidation non-null, no errors, all warnings acked", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();
    await act(async () => { store.reset(); });

    // Start with a warning
    await act(async () => {
      store.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      store.receiveValidation(MOCK_VALIDATION_WARNING);
    });
    // # reviewer: was `expect(store.stageState)` — a STALE snapshot captured at L1356
    // # reviewer: before reset()+mutations, so it read leftover cross-test state, not the
    // # reviewer: live store. It passed only by test-ordering luck; the corrected
    // # reviewer: T-API-RACE-1 (which now ends in COMPLETE) exposed it. Read live state,
    // # reviewer: consistent with L1370. — frontend-reviewer, PR #102 impl review, 2026-06-13
    expect(useStageOneStore.getState().stageState).not.toBe("COMPLETE");

    // Acknowledge warning → should become COMPLETE
    await act(async () => {
      store.acknowledgeWarning("W-COVERAGE-SHORT");
    });
    expect(useStageOneStore.getState().stageState).toBe("COMPLETE");
  });

  it("[T-CONTINUE-3] acknowledging a warning then changing a related field re-requires ack", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();
    await act(async () => { store.reset(); });

    await act(async () => {
      store.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      store.setLocation({ lat: 38.5, lon: 102.0 });
      store.receiveValidation(MOCK_VALIDATION_WARNING);
      store.acknowledgeWarning("W-COVERAGE-SHORT");
    });
    expect(useStageOneStore.getState().stageState).toBe("COMPLETE");

    // Change lat/lon — should clear coverage-related acknowledgements
    await act(async () => {
      store.setLocation({ lat: 40.0, lon: 105.0 });
    });
    // State drops to STALE; W-COVERAGE-SHORT should no longer be in acknowledgedWarnings
    const { acknowledgedWarnings } = useStageOneStore.getState();
    expect(acknowledgedWarnings).not.toContain("W-COVERAGE-SHORT");
  });
});

// ── Suite 11: Unhappy paths ──

describe("§T11 Unhappy paths", () => {
  it("[T-UNHAPPY-1] map tile failure shows fallback, lat/lon inputs remain enabled", async () => {
    // Same as T-MAP-4 — verified here under unhappy paths
    const MapPicker = await loadMapPicker();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
        simulateTileError={true}
      />
    );
    expect(screen.getByTestId("map-tile-error")).toBeTruthy();
    expect(screen.getByTestId("lat-input")).not.toBeDisabled();
    expect(screen.getByTestId("lon-input")).not.toBeDisabled();
  });

  it("[T-UNHAPPY-2] validation API 500 shows retry UI; button stays disabled", async () => {
    const ValidationPanel = await loadValidationPanel();
    const StageSaveButton = await loadStageSaveButton();
    render(
      <>
        <ValidationPanel
          result={null} pending={false}
          acknowledgedWarnings={[]} onAcknowledge={vi.fn()}
          apiError="Internal server error" onRetry={vi.fn()}
        />
        <StageSaveButton stageState="IN_PROGRESS" saveInProgress={false} onClick={vi.fn()} />
      </>
    );
    expect(screen.getByTestId("validation-api-error")).toBeTruthy();
    expect(screen.getByTestId("stage-save-btn")).toHaveAttribute("aria-disabled", "true");
  });

  it("[T-UNHAPPY-4] empty fleet prevents COMPLETE (hard validation error)", async () => {
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();
    await act(async () => { store.reset(); });
    // No devices + validation returns error
    await act(async () => {
      store.receiveValidation({
        errors: [{ rule_id: "E-FLEET-EMPTY", field: "assets.fleet", message: "No devices in fleet", constraint: "" }],
        warnings: [],
      });
    });
    expect(useStageOneStore.getState().stageState).not.toBe("COMPLETE");
  });

  it("[T-UNHAPPY-6] clearing lat/lon calls onLatLonChange(null); never calls with NaN (B4 fix)", async () => {
    // B4 fix: onLatLonChange: (LatLon | null) => void — null is the canonical cleared signal.
    // See contract §4.2 T-MAP-11 and §7 T-UNHAPPY-6.
    const MapPicker = await loadMapPicker();
    const onLatLonChange = vi.fn();
    render(
      <MapPicker
        latLon={{ lat: 38.0, lon: 102.0 }}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={onLatLonChange}
        onWeatherModeChange={vi.fn()}
      />
    );
    const latInput = screen.getByTestId("lat-input");
    const lonInput = screen.getByTestId("lon-input");
    await userEvent.clear(latInput);
    await userEvent.clear(lonInput);
    fireEvent.blur(latInput);
    // Both inputs cleared → must call onLatLonChange(null) — not NaN, not stale value
    expect(onLatLonChange).toHaveBeenCalledWith(null);
    expect(onLatLonChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ lat: NaN })
    );
    expect(onLatLonChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ lat: 38.0 })
    );
  });

  it("[T-UNHAPPY-7] save blocked while validation pending", async () => {
    // StageSaveButton cannot fire onClick when stageState !== COMPLETE/STALE
    const StageSaveButton = await loadStageSaveButton();
    const onClick = vi.fn();
    render(
      <StageSaveButton stageState="VALIDATING" saveInProgress={false} onClick={onClick} />
    );
    await userEvent.click(screen.getByTestId("stage-save-btn"));
    expect(onClick).not.toHaveBeenCalled();
  });
});

// ── Suite 12: Accessibility ──

describe("§T12 Accessibility", () => {
  it("[T-A11Y-1] MapPicker map container has role=application and aria-label", async () => {
    const MapPicker = await loadMapPicker();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    const mapEl = screen.getByRole("application");
    expect(mapEl).toHaveAttribute("aria-label", "Site location map");
  });

  it("[T-A11Y-2] fleet add ID input follows ARIA combobox pattern", async () => {
    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable fleet={[]} onAdd={vi.fn()} onRemove={vi.fn()} onCountChange={vi.fn()} onFleetMwChange={vi.fn()} />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    const idInput = screen.getByTestId("fleet-add-id");
    expect(idInput).toHaveAttribute("role", "combobox");
    expect(idInput).toHaveAttribute("aria-expanded");
    expect(idInput).toHaveAttribute("aria-controls");
  });

  it("[T-A11Y-3] ValidationPanel errors and warnings are role=alert", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_ERROR}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    const alerts = screen.getAllByRole("alert");
    expect(alerts.length).toBeGreaterThan(0);
  });

  it("[T-A11Y-4] Acknowledge button has descriptive aria-label", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_WARNING}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    const ackBtn = screen.getByTestId("validation-ack-W-COVERAGE-SHORT");
    const label = ackBtn.getAttribute("aria-label");
    expect(label).toMatch(/acknowledge warning/i);
    expect(label).toMatch(/Historical weather/i);  // includes the warning message
  });

  it("[T-A11Y-5] StageSaveButton uses aria-disabled not HTML disabled", async () => {
    const StageSaveButton = await loadStageSaveButton();
    render(
      <StageSaveButton stageState="IN_PROGRESS" saveInProgress={false} onClick={vi.fn()} />
    );
    const btn = screen.getByTestId("stage-save-btn");
    expect(btn).toHaveAttribute("aria-disabled", "true");
    // Must NOT have the HTML disabled attribute (would remove from tab order)
    expect(btn).not.toBeDisabled();
  });

  it("[T-A11Y-6] Back button is not a <button> on Stage ①", async () => {
    const StageOneConfig = await loadStageOneConfig();
    render(<StageOneConfig />);
    const backEl = screen.getByText(/← Back/i);
    expect(backEl.tagName.toLowerCase()).not.toBe("button");
    // Should not be focusable
    expect(backEl).not.toHaveAttribute("tabindex", "0");
  });

  it("[T-A11Y-7] error/warning symbols are used alongside color (not color alone)", async () => {
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={MOCK_VALIDATION_ERROR}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
      />
    );
    // Hard error uses ✗ symbol
    const errorEl = screen.getByTestId("validation-error-E-FLEET-EMPTY");
    expect(errorEl.textContent).toMatch(/✗/);
  });
});

// ── Suite 13: PV fleet row (§4.3 T-FLEET-PV-*) ──

describe("§T13 DeviceFleetTable PV fleet row variant", () => {
  it("[T-FLEET-PV-1] PV device type: add-form shows fleet-add-mw instead of fleet-add-count", async () => {
    // When the search resolves a pv_panel type, the Count input is replaced by
    // "Fleet capacity (MWp)" float input (fleet-add-mw) per §4.3 T-FLEET-PV-1.
    vi.useFakeTimers();
    globalThis.fetch = mockFetch({
      search: {
        results: [{
          model_id: "trina-vertex-n-670w", type: "pv_panel",
          label: "Trina Vertex N 670W · PV panel",
          rated_output: { value: 0.00067, unit: "MW" },
        }],
      },
    });

    const DeviceFleetTable = await loadDeviceFleetTable();
    render(
      <DeviceFleetTable
        fleet={[]}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByTestId("fleet-add-btn"));
    const idInput = screen.getByTestId("fleet-add-id");
    await userEvent.type(idInput, "trina");
    await act(async () => { vi.advanceTimersByTime(250); });
    await waitFor(() => screen.getByTestId("fleet-add-dropdown"));
    await userEvent.click(screen.getByText("trina-vertex-n-670w"));

    // After selecting a pv_panel: MW input present, count input absent
    expect(screen.getByTestId("fleet-add-mw")).toBeTruthy();
    expect(screen.queryByTestId("fleet-add-count")).toBeNull();

    // [Add ✓] disabled when MW input is empty
    expect(screen.getByTestId("fleet-add-confirm")).toBeDisabled();

    vi.useRealTimers();
  });

  it("[T-FLEET-PV-2] PV row in fleet renders fleet-row-mw-{i} not fleet-row-count-{i}; onFleetMwChange fires on blur", async () => {
    const onFleetMwChange = vi.fn();
    const DeviceFleetTable = await loadDeviceFleetTable();
    const pvFleet = [
      { id: "trina-vertex-n-670w", fleetCapacityMw: 330.0, type: "pv_panel" as const, label: "Trina PV", valid: true },
    ];
    render(
      <DeviceFleetTable
        fleet={pvFleet}
        onAdd={vi.fn()}
        onRemove={vi.fn()}
        onCountChange={vi.fn()}
        onFleetMwChange={onFleetMwChange}
      />
    );

    expect(screen.getByTestId("fleet-row-mw-0")).toBeTruthy();
    expect(screen.queryByTestId("fleet-row-count-0")).toBeNull();  // count hidden for PV

    const mwInput = screen.getByTestId("fleet-row-mw-0") as HTMLInputElement;
    await userEvent.clear(mwInput);
    await userEvent.type(mwInput, "400.0");
    fireEvent.blur(mwInput);
    expect(onFleetMwChange).toHaveBeenCalledWith(0, 400.0);
  });
});

// ── Suite 14: ValidationPanel tariff-required prerequisite state ──

describe("§T14 ValidationPanel tariff-required state", () => {
  it("[T-VAL-TARIFF-REQ] fleet non-empty + no tariffRegion → tariff-required info state", async () => {
    // When fleet has devices but no tariff is selected, the assemble guard prevents the call.
    // ValidationPanel shows a prerequisite info message (not an error).
    const ValidationPanel = await loadValidationPanel();
    render(
      <ValidationPanel
        result={null}
        pending={false}
        acknowledgedWarnings={[]}
        onAcknowledge={vi.fn()}
        apiError={null}
        onRetry={vi.fn()}
        tariffRequired={true}
      />
    );
    const info = screen.getByTestId("validation-tariff-required");
    expect(info).toHaveTextContent("Select a tariff region to validate your fleet");
    // Must NOT show error/warning content or validation-clean
    expect(screen.queryByTestId("validation-clean")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("[T-TARIFF-1] tariff dropdown option has testid with region_id; summary contains /MWh", async () => {
    // should-fix #2: §5.4 T-TARIFF-1 — option testid + ¥/MWh units assertion.
    vi.useFakeTimers();
    globalThis.fetch = mockFetch();
    const { renderHook, act: actHook } = await import("@testing-library/react");
    const { useSiteMetaForm } = await import("../../src/hooks/useSiteMetaForm");
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();
    const { result } = renderHook(() => useSiteMetaForm(store));
    await actHook(async () => { vi.runAllTimers(); await Promise.resolve(); });
    await waitFor(() => expect(result.current.availableTariffs.length).toBeGreaterThan(0));

    // The tariff option rendering test uses the DOM — render a stub select with tariff options
    const tariff = result.current.availableTariffs[0];  // cn-gansu
    const { container } = render(
      <div>
        <option
          data-testid={`tariff-region-option-${tariff.region_id}`}
          value={tariff.region_id}
        >
          {`¥${tariff.price_min_yuan_per_mwh}–${tariff.price_max_yuan_per_mwh}/MWh · 12×24 TOU`}
        </option>
      </div>
    );
    const opt = container.querySelector('[data-testid="tariff-region-option-cn-gansu"]');
    expect(opt).toBeTruthy();
    expect(opt!.textContent).toMatch(/\/MWh/);     // units MUST be /MWh
    expect(opt!.textContent).not.toMatch(/\/kWh/); // must NOT be /kWh

    vi.useRealTimers();
  });
});

// ── Suite 15: S1 ack-clearing + S2 rehydrate-COMPLETE ──

describe("§T15 S1 ack-clearing + S2 rehydrate-COMPLETE", () => {
  it("[T-S1-ACK-CLEAR] any meaningful edit clears ALL acknowledgedWarnings", async () => {
    // §3.2 S1: any meaningful field edit clears all acks (not just related rule_ids).
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    const store = useStageOneStore.getState();
    await act(async () => { store.reset(); });

    await act(async () => {
      store.addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
      store.receiveValidation({
        errors: [],
        warnings: [
          { rule_id: "W-COVERAGE-SHORT", field: "lat", message: "Short horizon", constraint: "" },
          { rule_id: "W-BAT-DUR-10H", field: "assets.battery", message: "Battery duration", constraint: "" },
        ],
      });
      store.acknowledgeWarning("W-COVERAGE-SHORT");
      store.acknowledgeWarning("W-BAT-DUR-10H");
    });
    expect(useStageOneStore.getState().acknowledgedWarnings).toHaveLength(2);

    // Any meaningful edit (count change) should clear ALL acks
    await act(async () => {
      store.updateDeviceCount(0, 50);
    });
    expect(useStageOneStore.getState().acknowledgedWarnings).toHaveLength(0);
  });

  it("[T-S1-STALE-CLICK] STALE state: clicking StageSaveButton calls onClick()", async () => {
    // should-fix #3: directly test STALE-state click (T-SAVE-5 tested COMPLETE; this adds STALE).
    const StageSaveButton = await loadStageSaveButton();
    const onClick = vi.fn();
    render(
      <StageSaveButton stageState="STALE" saveInProgress={false} onClick={onClick} />
    );
    await userEvent.click(screen.getByTestId("stage-save-btn"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("[T-S2-REHYDRATE] rehydrating COMPLETE immediately transitions to IN_PROGRESS", async () => {
    // §3.2 S2: a persisted COMPLETE state must NOT enable Continue without a fresh assemble.
    // The implementation hooks onRehydrateStorage (or a StageOneConfig mount effect) to
    // downgrade COMPLETE → IN_PROGRESS on rehydrate.
    //
    // IMPORTANT: use the persist.rehydrate() path — NOT useStageOneStore.setState(). Direct
    // setState bypasses Zustand persist's onRehydrateStorage entirely; a correct impl that
    // only hooks rehydration would leave stageState === COMPLETE after a plain setState,
    // making a setState-based test passable only by a wrong "downgrade-on-every-setState" hack.

    const { useStageOneStore } = await import("../../src/stores/stageOneStore");

    // Seed localStorage with a COMPLETE state (simulates data written by a prior session save).
    const persistedSnapshot = {
      state: {
        stageState: "COMPLETE",
        lastValidation: { errors: [], warnings: [] },
        acknowledgedWarnings: [],
        fleet: [{ id: "vestas-v150-4.2", count: 1, valid: true }],
        tariffRegion: "cn-gansu",
        siteName: "Gansu demo",
        province: "Gansu",
        location: { lat: 38.5, lon: 102.0 },
        weatherMode: "synthetic",
      },
      version: 0,
    };
    localStorage.setItem("energygo.stage1", JSON.stringify(persistedSnapshot));

    // Trigger Zustand persist rehydration (equivalent to a page reload).
    // onRehydrateStorage fires during this call and must downgrade COMPLETE → IN_PROGRESS.
    await act(async () => {
      await useStageOneStore.persist.rehydrate();
    });

    // S2: stageState must have been downgraded — fresh assemble needed before Continue is enabled.
    expect(useStageOneStore.getState().stageState).toBe("IN_PROGRESS");

    // Clean up
    localStorage.removeItem("energygo.stage1");
  });
});

// reviewer: §5.2 fail-safe gap. The contract §5.2 states: "If coverage check fails,
// Historical/Bootstrap remain disabled (fail-safe)." But the T-MAP-6/7 *invariants*
// only enumerate `coverage?.historical_available === false` OR `coveragePending` — they
// do NOT mention the error/null case. An implementation that satisfies T-MAP-6/7
// literally could leave both radios ENABLED when the coverage API errored (coverage=null,
// coverageError set, pending=false), letting the user select a weather mode with no
// backing data. This pins the §5.2 fail-safe. (Recommend rewording T-MAP-6/7 to:
// "enabled ONLY when coverage.historical_available === true; any other state — false,
// null, pending, or error — disables.")
describe("reviewer: §T3 MapPicker coverage-error fail-safe (§5.2)", () => {
  it("reviewer: [T-MAP-COV-ERR] coverageError set → Historical & Bootstrap both disabled", async () => {
    const MapPicker = await loadMapPicker();
    render(
      <MapPicker
        latLon={{ lat: 38.5, lon: 102.0 }}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError="Coverage check failed"
        onLatLonChange={vi.fn()}
        onWeatherModeChange={vi.fn()}
      />
    );
    // Fail-safe: a failed coverage check must NOT leave historical/bootstrap selectable.
    expect(screen.getByTestId("weather-mode-historical")).toBeDisabled();
    expect(screen.getByTestId("weather-mode-bootstrap")).toBeDisabled();
  });
});

// reviewer: T-MAP-10 only exercises the LAT range guard ([-90,90]). The symmetric LON
// guard ([-180,180] → lon-range-error, no onLatLonChange) is asserted nowhere, so a
// lon-only limit/sign bug (e.g. clamping to ±90, or firing onLatLonChange with an
// out-of-range lon) would slip through. This adds the missing symmetric case.
describe("reviewer: §T3 MapPicker lon range guard (§4.2 T-MAP-10)", () => {
  it("reviewer: [T-MAP-10-LON] lon=200 (out of [-180,180]) shows lon-range-error, no onLatLonChange", async () => {
    const MapPicker = await loadMapPicker();
    const onLatLonChange = vi.fn();
    render(
      <MapPicker
        latLon={null}
        weatherMode="synthetic"
        coverage={null}
        coveragePending={false}
        coverageError={null}
        onLatLonChange={onLatLonChange}
        onWeatherModeChange={vi.fn()}
      />
    );
    const lonInput = screen.getByTestId("lon-input");
    await userEvent.type(lonInput, "200");
    fireEvent.blur(lonInput);
    expect(screen.getByTestId("lon-range-error")).toBeTruthy();
    expect(onLatLonChange).not.toHaveBeenCalled();
  });
});

// reviewer: §T-API-FAIL — assemble-failure path, store→panel integration.
// # reviewer: BLOCKING (PR #102 impl review). Contract §5.1 "Error handling" + §7 T-UNHAPPY-2
// # reviewer: + §4.5 apiError require that a non-200/network error from POST /api/site/assemble
// # reviewer: surface in ValidationPanel as data-testid="validation-api-error" with a working
// # reviewer: [Retry] that re-attempts the assemble call, and that stageState NOT advance to
// # reviewer: COMPLETE on failure. The existing T-UNHAPPY-2 / T-VAL-7 only render ValidationPanel
// # reviewer: in ISOLATION with apiError passed directly, so the store→panel wiring is untested.
// # reviewer: At HEAD 4d7e42b this path is DEAD: stageOneStore assemble catch never sets an error
// # reviewer: field, and StageOneConfig wires apiError={store.saveError} (the unrelated footer-save
// # reviewer: error, never set by the assemble path). This test is RED until that is fixed.
// # reviewer: — frontend-reviewer, PR #102 impl review, 2026-06-13
describe("reviewer: §T-API-FAIL assemble failure surfaces in ValidationPanel (§5.1, T-UNHAPPY-2)", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("reviewer: [T-API-FAIL-1] assemble 500 → validation-api-error shown, stage not COMPLETE; Retry recovers", async () => {
    let failNext = true;
    let assembleCalls = 0;
    globalThis.fetch = vi.fn((url: string) => {
      const u = String(url);
      if (u.includes("/api/site/assemble")) {
        assembleCalls++;
        return failNext
          ? Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) })
          : Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_VALIDATION_CLEAN) });
      }
      if (u.includes("/api/tariff/regions"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_TARIFF_REGIONS) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    const StageOneConfig = await loadStageOneConfig();
    const { useStageOneStore } = await import("../../src/stores/stageOneStore");
    await act(async () => { useStageOneStore.getState().reset(); });
    render(<StageOneConfig />);

    // Satisfy the §5.1 guard (tariff + ≥1 valid device), then fire the 300 ms debounce → 500.
    await act(async () => {
      useStageOneStore.getState().setTariffRegion("cn-gansu", false);
      useStageOneStore.getState().addDevice({ id: "vestas-v150-4.2", count: 1, valid: true });
    });
    await act(async () => { vi.advanceTimersByTime(350); });

    // §5.1: error surfaces as validation-api-error; §5.1 deviation #2: stageState NOT COMPLETE.
    await waitFor(() => { expect(screen.getByTestId("validation-api-error")).toBeTruthy(); });
    expect(assembleCalls).toBe(1);
    expect(useStageOneStore.getState().stageState).not.toBe("COMPLETE");

    // §5.1: [Retry] must re-attempt the assemble call; this time it succeeds → clean state.
    failNext = false;
    await act(async () => { fireEvent.click(screen.getByTestId("validation-retry")); });
    await act(async () => { vi.advanceTimersByTime(350); });
    await waitFor(() => {
      expect(screen.queryByTestId("validation-api-error")).toBeNull();
      expect(screen.getByTestId("validation-clean")).toBeTruthy();
    });
    expect(assembleCalls).toBeGreaterThanOrEqual(2);
  });
});
