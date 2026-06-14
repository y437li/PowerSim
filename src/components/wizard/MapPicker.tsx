// src/components/wizard/MapPicker.tsx
// Contract: contracts/frontend/stage_config.md §4.2
// No MapLibre dependency — uses text inputs + placeholder map area.
// simulateTileError is a test-only prop to exercise the tile-error fallback path.

import React, { useState, useEffect, useRef } from "react";
import type { LatLon, WeatherMode, WeatherCoverage } from "../../types/stageConfig";
import { TOKEN } from "../../styles/tokenValues";

interface MapPickerProps {
  latLon:              LatLon | null;
  weatherMode:         WeatherMode;
  coverage:            WeatherCoverage | null;
  coveragePending:     boolean;
  coverageError:       string | null;
  onLatLonChange:      (v: LatLon | null) => void;
  onWeatherModeChange: (mode: WeatherMode) => void;
  simulateTileError?:  boolean;   // test-only prop
}

// Parse a coordinate string that may have an N/S or E/W suffix.
function parseCoord(text: string): number | null {
  const s = text.trim().toUpperCase();
  if (!s) return null;
  let sign = 1;
  let num  = s;
  if (s.endsWith("S") || s.endsWith("W")) { sign = -1; num = s.slice(0, -1); }
  else if (s.endsWith("N") || s.endsWith("E"))    { num = s.slice(0, -1); }
  const v = parseFloat(num);
  if (isNaN(v)) return null;
  return sign * v;
}

export function MapPicker({
  latLon,
  weatherMode,
  coverage,
  coveragePending,
  coverageError,
  onLatLonChange,
  onWeatherModeChange,
  simulateTileError = false,
}: MapPickerProps) {
  const [latText, setLatText]   = useState(latLon != null ? String(latLon.lat) : "");
  const [lonText, setLonText]   = useState(latLon != null ? String(latLon.lon) : "");
  const [latError, setLatError] = useState<string | null>(null);
  const [lonError, setLonError] = useState<string | null>(null);
  const [toast, setToast]       = useState<string | null>(null);
  const toastTimerRef           = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync inputs when latLon prop changes (e.g. geolocation update from parent).
  useEffect(() => {
    setLatText(latLon != null ? String(latLon.lat) : "");
    setLonText(latLon != null ? String(latLon.lon) : "");
  }, [latLon]);

  function commitCoords(newLatText: string, newLonText: string) {
    const bothEmpty = !newLatText.trim() && !newLonText.trim();
    if (bothEmpty) { onLatLonChange(null); return; }

    // Validate lat
    if (newLatText.trim()) {
      const v = parseCoord(newLatText);
      if (v === null || v < -90 || v > 90) {
        setLatError("Latitude must be between -90 and 90");
        return;
      }
      setLatError(null);
    }

    // Validate lon
    if (newLonText.trim()) {
      const v = parseCoord(newLonText);
      if (v === null || v < -180 || v > 180) {
        setLonError("Longitude must be between -180 and 180");
        return;
      }
      setLonError(null);
    }

    // Both valid — fire callback
    const parsedLat = parseCoord(newLatText);
    const parsedLon = parseCoord(newLonText);
    if (parsedLat !== null && parsedLon !== null) {
      onLatLonChange({ lat: parsedLat, lon: parsedLon });
    }
  }

  function handleLatBlur() {
    // Validate lat range inline
    if (latText.trim()) {
      const v = parseCoord(latText);
      if (v === null || v < -90 || v > 90) {
        setLatError("Latitude must be between -90 and 90");
        return;
      }
      setLatError(null);
    }
    commitCoords(latText, lonText);
  }

  function handleLonBlur() {
    if (lonText.trim()) {
      const v = parseCoord(lonText);
      if (v === null || v < -180 || v > 180) {
        setLonError("Longitude must be between -180 and 180");
        return;
      }
      setLonError(null);
    }
    commitCoords(latText, lonText);
  }

  function handleUseMyLocation() {
    if (!navigator.geolocation) {
      showToast("Location unavailable");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        onLatLonChange({ lat: pos.coords.latitude, lon: pos.coords.longitude });
      },
      () => {
        showToast("Location unavailable");
      },
    );
  }

  function showToast(msg: string) {
    setToast(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(null), 4000);
  }

  // Coverage availability guards
  const historicalEnabled = !coveragePending && !coverageError && coverage?.historical_available === true;
  const bootstrapEnabled  = !coveragePending && !coverageError && coverage?.bootstrap_available  === true;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      {/* Map area */}
      {simulateTileError ? (
        <div
          data-testid="map-tile-error"
          style={{
            padding:      "12px",
            background:   TOKEN.bgError,
            border:       `1px solid ${TOKEN.accentRed}`,
            borderRadius: "6px",
            color:        TOKEN.accentErrorText,
            fontSize:     "13px",
          }}
        >
          Map tiles unavailable — enter coordinates manually.
        </div>
      ) : (
        <div
          role="application"
          aria-label="Site location map"
          style={{
            height:       "180px",
            background:   TOKEN.bgSurface,
            border:       `1px solid ${TOKEN.borderDefault}`,
            borderRadius: "6px",
            display:      "flex",
            alignItems:   "center",
            justifyContent: "center",
            color:        TOKEN.textFaint,
            fontSize:     "13px",
          }}
        >
          Map view (lat/lon required for tile load)
        </div>
      )}

      {/* Coordinate inputs */}
      <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: "12px", color: TOKEN.textMuted, display: "block", marginBottom: "4px" }}>
            Latitude
          </label>
          <input
            data-testid="lat-input"
            type="text"
            value={latText}
            onChange={e => { setLatText(e.target.value); setLatError(null); }}
            onBlur={handleLatBlur}
            placeholder="e.g. 38.5 or 38.5N"
            style={{ width: "100%", boxSizing: "border-box", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgSurface, color: TOKEN.textPrimary }}
          />
          {latError && (
            <div data-testid="lat-range-error" style={{ fontSize: "11px", color: TOKEN.accentErrorText, marginTop: "2px" }}>
              {latError}
            </div>
          )}
        </div>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: "12px", color: TOKEN.textMuted, display: "block", marginBottom: "4px" }}>
            Longitude
          </label>
          <input
            data-testid="lon-input"
            type="text"
            value={lonText}
            onChange={e => { setLonText(e.target.value); setLonError(null); }}
            onBlur={handleLonBlur}
            placeholder="e.g. 102.0 or 102.0E"
            style={{ width: "100%", boxSizing: "border-box", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgSurface, color: TOKEN.textPrimary }}
          />
          {lonError && (
            <div data-testid="lon-range-error" style={{ fontSize: "11px", color: TOKEN.accentErrorText, marginTop: "2px" }}>
              {lonError}
            </div>
          )}
        </div>
        <div style={{ paddingTop: "20px" }}>
          <button
            data-testid="use-my-location"
            onClick={handleUseMyLocation}
            style={{ padding: "6px 12px", borderRadius: "4px", cursor: "pointer", fontSize: "12px", background: TOKEN.bgSurface, color: TOKEN.textMuted, border: `1px solid ${TOKEN.borderDefault}` }}
          >
            Use my location
          </button>
        </div>
      </div>

      {/* Location toast */}
      {toast && (
        <div
          data-testid="location-toast"
          role="status"
          style={{
            padding:      "8px 12px",
            background:   TOKEN.bgError,
            border:       `1px solid ${TOKEN.accentRed}`,
            borderRadius: "4px",
            color:        TOKEN.accentErrorText,
            fontSize:     "13px",
          }}
        >
          {toast}
        </div>
      )}

      {/* Weather mode */}
      <div>
        <div style={{ fontSize: "12px", color: TOKEN.textMuted, marginBottom: "6px", fontWeight: 600 }}>
          Weather Mode
        </div>
        <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
          {(["synthetic", "historical", "bootstrap"] as WeatherMode[]).map(mode => {
            const disabled =
              mode === "historical" ? !historicalEnabled :
              mode === "bootstrap"  ? !bootstrapEnabled  :
              false;
            return (
              <label
                key={mode}
                style={{
                  display:    "flex",
                  alignItems: "center",
                  gap:        "6px",
                  cursor:     disabled ? "not-allowed" : "pointer",
                  color:      disabled ? TOKEN.textFaint : TOKEN.textPrimary,
                  fontSize:   "13px",
                }}
              >
                <input
                  data-testid={`weather-mode-${mode}`}
                  type="radio"
                  name="weather-mode"
                  value={mode}
                  checked={weatherMode === mode}
                  disabled={disabled}
                  onChange={() => !disabled && onWeatherModeChange(mode)}
                />
                {mode.charAt(0).toUpperCase() + mode.slice(1)}
              </label>
            );
          })}
        </div>

        {/* Coverage info */}
        {coveragePending && (
          <div data-testid="coverage-spinner" style={{ marginTop: "6px", fontSize: "12px", color: TOKEN.textMuted }}>
            ⟳ Checking weather coverage…
          </div>
        )}
        {coverage && !coveragePending && !coverageError && coverage.historical_available && (
          <div style={{ marginTop: "6px", fontSize: "12px", color: TOKEN.textFaint }}>
            {coverage.available_year_count} years available
            {coverage.year_range ? ` (${coverage.year_range[0]}–${coverage.year_range[1]})` : ""}
          </div>
        )}
        {coverageError && (
          <div style={{ marginTop: "6px", fontSize: "12px", color: TOKEN.accentErrorText }}>
            {coverageError}
          </div>
        )}
      </div>
    </div>
  );
}
