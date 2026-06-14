// src/components/wizard/StageOneConfig.tsx
// Root wizard Stage ① component.
// Contract: contracts/frontend/stage_config.md §4.1

import React, { useEffect, useRef } from "react";
import { useStageOneStore } from "../../stores/stageOneStore";
import { useSiteMetaForm } from "../../hooks/useSiteMetaForm";
import { MapPicker }          from "./MapPicker";
import { DeviceFleetTable }   from "./DeviceFleetTable";
import { ScenarioComposer }   from "./ScenarioComposer";
import { ValidationPanel }    from "./ValidationPanel";
import { StageSaveButton }    from "./StageSaveButton";
import type { LatLon, WeatherMode } from "../../types/stageConfig";
import { TOKEN } from "../../styles/tokenValues";

export function StageOneConfig() {
  const store    = useStageOneStore();
  const metaForm = useSiteMetaForm(store);

  // ── Coverage 500ms debounce (§5.2) ──────────────────────────────────────
  const coverageTimerRef   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coverageAbortRef   = useRef<AbortController | null>(null);
  const prevLocationRef    = useRef<LatLon | null>(null);

  useEffect(() => {
    const loc = store.location;

    // Skip if location is same object or both null
    const prev = prevLocationRef.current;
    const changed = loc !== prev && (
      !loc || !prev || loc.lat !== prev.lat || loc.lon !== prev.lon
    );
    prevLocationRef.current = loc;

    if (!changed) return;

    // Clear any pending coverage check
    if (coverageTimerRef.current) { clearTimeout(coverageTimerRef.current); coverageTimerRef.current = null; }
    if (coverageAbortRef.current) { coverageAbortRef.current.abort(); coverageAbortRef.current = null; }

    if (!loc) {
      useStageOneStore.setState({ coverageResult: null, coverageError: null, coveragePending: false });
      return;
    }

    useStageOneStore.setState({ coveragePending: true, coverageError: null });

    coverageTimerRef.current = setTimeout(async () => {
      coverageTimerRef.current = null;
      const ctrl = new AbortController();
      coverageAbortRef.current = ctrl;
      const { lat, lon } = loc;
      try {
        const resp = await fetch(
          `/api/site/weather-coverage?lat=${lat}&lon=${lon}`,
          { signal: ctrl.signal },
        );
        coverageAbortRef.current = null;
        if (!resp.ok) throw new Error(`${resp.status}`);
        const data = await resp.json();
        useStageOneStore.getState().receiveCoverage({
          historical_available: data.historical_available,
          available_year_count: data.available_year_count,
          year_range:           data.year_range,
          bootstrap_available:  data.bootstrap_available,
        });
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        coverageAbortRef.current = null;
        useStageOneStore.getState().setCoverageError(
          (err as Error).message || "Coverage check failed",
        );
      }
    }, 500);

    return () => {
      if (coverageTimerRef.current) { clearTimeout(coverageTimerRef.current); coverageTimerRef.current = null; }
      if (coverageAbortRef.current) { coverageAbortRef.current.abort(); coverageAbortRef.current = null; }
    };
  }, [store.location]);

  // ── Derived state ─────────────────────────────────────────────────────────
  const validFleet    = store.fleet.filter(r => r.valid === true);
  const tariffRequired = validFleet.length > 0 && store.tariffRegion === "";

  // ── Event handlers ────────────────────────────────────────────────────────
  function handleLatLonChange(loc: LatLon | null) {
    store.setLocation(loc);
  }

  function handleWeatherModeChange(mode: WeatherMode) {
    store.setWeatherMode(mode);
  }

  function handleSave() {
    // TODO: wire to save endpoint (task #8+)
    store.setSaveInProgress(true);
  }

  function handleRetry() {
    // B6: clear assemble error and re-fire the debounced assemble call
    store.retryAssemble();
  }

  return (
    <div
      data-testid="stage-one-config"
      style={{
        display:        "flex",
        flexDirection:  "column",
        gap:            "0",
        minHeight:      "100vh",
        background:     TOKEN.bgApp,
        color:          TOKEN.textPrimary,
        fontFamily:     "system-ui, sans-serif",
      }}
    >
      {/* Wizard header */}
      <header style={{ padding: "16px 24px", borderBottom: `1px solid ${TOKEN.borderDefault}`, display: "flex", alignItems: "center", gap: "12px" }}>
        {/* Back button: span (not button) per T-A11Y-6 — Stage ① has no previous stage */}
        <span
          style={{ color: TOKEN.textFaint, fontSize: "14px", cursor: "default" }}
          aria-disabled="true"
        >
          ← Back
        </span>
        <h2 style={{ margin: 0, fontSize: "16px", fontWeight: 600 }}>
          Stage ① · Site Configuration
        </h2>
      </header>

      {/* Main content: two columns */}
      <div style={{ display: "flex", flex: 1, gap: "0" }}>
        {/* Left column — location + fleet */}
        <div
          data-testid="stage-one-left"
          style={{
            flex:         1,
            padding:      "24px",
            borderRight:  `1px solid ${TOKEN.borderDefault}`,
            display:      "flex",
            flexDirection:"column",
            gap:          "24px",
          }}
        >
          {/* Site metadata */}
          <section>
            <h3 style={{ color: TOKEN.textMuted, fontSize: "11px", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "10px" }}>
              Site Details
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <div>
                <label style={{ fontSize: "12px", color: TOKEN.textMuted, display: "block", marginBottom: "3px" }}>
                  Site name
                </label>
                <input
                  type="text"
                  value={metaForm.siteName}
                  onChange={e => metaForm.setSiteName(e.target.value)}
                  placeholder="e.g. Gansu Wind Farm Phase II"
                  style={{ width: "100%", boxSizing: "border-box", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgSurface, color: TOKEN.textPrimary }}
                />
                {metaForm.siteNameError && (
                  <div style={{ fontSize: "11px", color: TOKEN.accentErrorText, marginTop: "2px" }}>{metaForm.siteNameError}</div>
                )}
              </div>
              <div>
                <label style={{ fontSize: "12px", color: TOKEN.textMuted, display: "block", marginBottom: "3px" }}>
                  Province
                </label>
                <input
                  type="text"
                  value={metaForm.province}
                  onChange={e => metaForm.setProvince(e.target.value)}
                  placeholder="e.g. Gansu"
                  style={{ width: "100%", boxSizing: "border-box", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgSurface, color: TOKEN.textPrimary }}
                />
              </div>
            </div>
          </section>

          {/* Map + weather mode */}
          <section>
            <h3 style={{ color: TOKEN.textMuted, fontSize: "11px", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "10px" }}>
              Location & Weather
            </h3>
            <MapPicker
              latLon={store.location}
              weatherMode={store.weatherMode}
              coverage={store.coverageResult}
              coveragePending={store.coveragePending}
              coverageError={store.coverageError}
              onLatLonChange={handleLatLonChange}
              onWeatherModeChange={handleWeatherModeChange}
            />
          </section>

          {/* Device fleet */}
          <section>
            <h3 style={{ color: TOKEN.textMuted, fontSize: "11px", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "10px" }}>
              Device Fleet
            </h3>
            <DeviceFleetTable
              fleet={store.fleet}
              onAdd={store.addDevice}
              onRemove={store.removeDevice}
              onCountChange={store.updateDeviceCount}
              onFleetMwChange={store.updateDeviceFleetMw}
            />
          </section>
        </div>

        {/* Right column — tariff, scenarios, validation */}
        <div
          data-testid="stage-one-right"
          style={{
            width:         "340px",
            padding:       "24px",
            display:       "flex",
            flexDirection: "column",
            gap:           "24px",
          }}
        >
          {/* Tariff region */}
          <section>
            <h3 style={{ color: TOKEN.textMuted, fontSize: "11px", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "10px" }}>
              Tariff Region
            </h3>
            <select
              value={metaForm.tariffRegion}
              onChange={e => metaForm.setTariffRegion(e.target.value, true)}
              style={{ width: "100%", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgSurface, color: TOKEN.textPrimary }}
            >
              <option value="">— Select tariff region —</option>
              {metaForm.availableTariffs.map(t => (
                <option
                  key={t.region_id}
                  value={t.region_id}
                  data-testid={`tariff-region-option-${t.region_id}`}
                >
                  {t.region_id} · ¥{t.price_min_yuan_per_mwh}–{t.price_max_yuan_per_mwh}/MWh · 12×24 TOU
                </option>
              ))}
            </select>
            {metaForm.showTariffResetLink && (
              <button
                onClick={metaForm.resetTariffToProvinceDefault}
                style={{ fontSize: "11px", color: TOKEN.accentBlue, background: "none", border: "none", cursor: "pointer", marginTop: "4px", padding: 0 }}
              >
                Reset to province default
              </button>
            )}
          </section>

          {/* Scenarios */}
          <ScenarioComposer scenarioBasePowerActive={store.scenarioBasePowerActive} />

          {/* Validation */}
          <section>
            <h3 style={{ color: TOKEN.textMuted, fontSize: "11px", fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", marginBottom: "6px" }}>
              Validation
            </h3>
            <ValidationPanel
              result={store.lastValidation}
              pending={store.validationPending}
              acknowledgedWarnings={store.acknowledgedWarnings}
              onAcknowledge={store.acknowledgeWarning}
              apiError={store.assembleError ?? null}
              onRetry={handleRetry}
              tariffRequired={tariffRequired}
            />
          </section>
        </div>
      </div>

      {/* Footer */}
      <footer
        data-testid="stage-one-footer"
        style={{
          padding:       "16px 24px",
          borderTop:     `1px solid ${TOKEN.borderDefault}`,
          display:       "flex",
          alignItems:    "center",
          justifyContent:"flex-end",
          gap:           "12px",
        }}
      >
        <StageSaveButton
          stageState={store.stageState}
          saveInProgress={store.saveInProgress}
          onClick={handleSave}
        />
      </footer>
    </div>
  );
}
