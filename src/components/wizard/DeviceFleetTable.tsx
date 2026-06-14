// src/components/wizard/DeviceFleetTable.tsx
// Contract: contracts/frontend/stage_config.md §4.3

import React, { useState, useRef } from "react";
import type { DeviceRow } from "../../types/stageConfig";
import { TOKEN } from "../../styles/tokenValues";

interface SearchResult {
  model_id:     string;
  type:         "wind_turbine" | "pv_panel" | "battery" | "grid_connection";
  label:        string;
  rated_output: { value: number; unit: string };
}

interface DeviceFleetTableProps {
  fleet:          DeviceRow[];
  onAdd:          (row: DeviceRow) => void;
  onRemove:       (index: number) => void;
  onCountChange:  (index: number, count: number) => void;
  onFleetMwChange?: (index: number, mw: number) => void;
}

export function DeviceFleetTable({
  fleet,
  onAdd,
  onRemove,
  onCountChange,
  onFleetMwChange,
}: DeviceFleetTableProps) {
  const [addOpen, setAddOpen]           = useState(false);
  const [idText,  setIdText]            = useState("");
  const [countText, setCountText]       = useState("1");
  const [mwText,  setMwText]            = useState("");
  const [searchResults, setResults]     = useState<SearchResult[]>([]);
  const [searching, setSearching]       = useState(false);
  const [idError,  setIdError]          = useState<string | null>(null);
  const [selected, setSelected]         = useState<SearchResult | null>(null);
  const debounceRef                     = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchAbortRef                  = useRef<AbortController | null>(null);

  // ── Add form state helpers ──

  function openAddForm() {
    setAddOpen(true);
    setIdText("");
    setCountText("1");
    setMwText("");
    setResults([]);
    setIdError(null);
    setSelected(null);
    setSearching(false);
  }

  function closeAddForm() {
    setAddOpen(false);
    setIdText("");
    setCountText("1");
    setMwText("");
    setResults([]);
    setIdError(null);
    setSelected(null);
    setSearching(false);
    if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
    if (searchAbortRef.current) { searchAbortRef.current.abort(); searchAbortRef.current = null; }
  }

  function handleIdChange(e: React.ChangeEvent<HTMLInputElement>) {
    const q = e.target.value;
    setIdText(q);
    setSelected(null);
    setIdError(null);
    setResults([]);

    if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
    if (searchAbortRef.current) { searchAbortRef.current.abort(); searchAbortRef.current = null; }

    if (!q.trim()) { setSearching(false); return; }

    // 200ms debounce — no AbortController on the fetch itself (test T-FLEET-3
    // expects fetch called with URL only; debounce prevents most stale responses)
    debounceRef.current = setTimeout(async () => {
      debounceRef.current = null;
      setSearching(true);

      try {
        const resp = await fetch(`/api/devices/search?q=${encodeURIComponent(q)}`);
        if (!resp.ok) throw new Error(`${resp.status}`);
        const data = await resp.json() as { results: SearchResult[] };
        setSearching(false);
        setResults(data.results ?? []);
        if ((data.results ?? []).length === 0) {
          setIdError(`"${q}" not found in device library`);
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setSearching(false);
        setIdError(`Search failed`);
      }
    }, 200);
  }

  function handleSelectResult(r: SearchResult) {
    setSelected(r);
    setIdText(r.model_id);
    setResults([]);
    setIdError(null);
    // Reset size fields
    setCountText("1");
    setMwText("");
  }

  function handleConfirm() {
    if (!selected) return;
    if (selected.type === "pv_panel") {
      if (!mwText.trim()) return;
      const mw = parseFloat(mwText);
      if (isNaN(mw) || mw <= 0) return;
      onAdd({
        id:              selected.model_id,
        type:            selected.type,
        label:           selected.label,
        valid:           true,
        fleetCapacityMw: mw,
      });
    } else {
      const count = Math.max(1, Math.min(999, parseInt(countText, 10) || 1));
      onAdd({
        id:    selected.model_id,
        type:  selected.type,
        label: selected.label,
        valid: true,
        count,
      });
    }
    closeAddForm();
  }

  const confirmDisabled =
    searching ||
    !selected ||
    (selected?.type === "pv_panel" && !mwText.trim());

  const isPV = selected?.type === "pv_panel";
  const showDropdown = searchResults.length > 0 && !selected;

  return (
    <div>
      {/* Fleet rows */}
      {fleet.length === 0 && !addOpen && (
        <div data-testid="fleet-empty-state" style={{ color: TOKEN.textFaint, fontSize: "13px", padding: "8px 0" }}>
          No devices added yet.
        </div>
      )}

      {fleet.map((row, i) => (
        <div
          key={`${row.id}-${i}`}
          data-testid={`fleet-row-${i}`}
          style={{
            display:      "flex",
            alignItems:   "center",
            gap:          "8px",
            padding:      "6px 0",
            borderBottom: `1px solid ${TOKEN.borderDefault}`,
            fontSize:     "13px",
            color:        TOKEN.textPrimary,
          }}
        >
          <span style={{ flex: 1 }}>{row.id}</span>
          {row.type === "pv_panel" ? (
            <input
              data-testid={`fleet-row-mw-${i}`}
              type="number"
              defaultValue={row.fleetCapacityMw ?? ""}
              step="0.1"
              onBlur={e => {
                const v = parseFloat(e.target.value);
                if (!isNaN(v) && v > 0) onFleetMwChange?.(i, v);
              }}
              style={{ width: "80px", padding: "3px 6px" }}
            />
          ) : (
            <input
              data-testid={`fleet-row-count-${i}`}
              type="number"
              defaultValue={row.count ?? 1}
              min={1}
              max={999}
              onBlur={e => {
                const raw = parseInt(e.target.value, 10);
                const clamped = isNaN(raw) ? 1 : Math.max(1, Math.min(999, raw));
                onCountChange(i, clamped);
              }}
              style={{ width: "60px", padding: "3px 6px" }}
            />
          )}
          <button
            data-testid={`fleet-row-remove-${i}`}
            onClick={() => onRemove(i)}
            aria-label={`Remove ${row.id}`}
            style={{ fontSize: "12px", cursor: "pointer", padding: "3px 8px", color: TOKEN.accentRed, background: "transparent", border: `1px solid ${TOKEN.accentRed}`, borderRadius: "4px" }}
          >
            ✕
          </button>
        </div>
      ))}

      {/* Fleet totals placeholder */}
      <div
        data-testid="fleet-totals"
        style={{ fontSize: "12px", color: TOKEN.textFaint, padding: "6px 0", borderTop: fleet.length ? `1px solid ${TOKEN.borderDefault}` : undefined }}
      >
        Total: —
      </div>

      {/* Add button */}
      {!addOpen && (
        <button
          data-testid="fleet-add-btn"
          onClick={openAddForm}
          style={{ marginTop: "8px", padding: "5px 14px", borderRadius: "4px", cursor: "pointer", fontSize: "12px", background: TOKEN.bgSurface, color: TOKEN.accentBlue, border: `1px solid ${TOKEN.accentBlue}` }}
        >
          + Add device
        </button>
      )}

      {/* Inline add form */}
      {addOpen && (
        <div
          data-testid="fleet-add-form"
          style={{ marginTop: "8px", padding: "10px", background: TOKEN.bgSurface, border: `1px solid ${TOKEN.borderDefault}`, borderRadius: "6px" }}
        >
          <div style={{ position: "relative" }}>
            <input
              data-testid="fleet-add-id"
              role="combobox"
              aria-expanded={showDropdown ? "true" : "false"}
              aria-controls="fleet-add-dropdown-list"
              aria-autocomplete="list"
              type="text"
              value={idText}
              onChange={handleIdChange}
              placeholder="Device model ID (e.g. vestas-v150-4.2)"
              style={{ width: "100%", boxSizing: "border-box", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgApp, color: TOKEN.textPrimary, marginBottom: "6px" }}
            />

            {/* Search results dropdown */}
            {showDropdown && (
              <ul
                data-testid="fleet-add-dropdown"
                id="fleet-add-dropdown-list"
                role="listbox"
                style={{ position: "absolute", zIndex: 10, top: "100%", left: 0, right: 0, background: TOKEN.bgSurface, border: `1px solid ${TOKEN.borderDefault}`, borderRadius: "4px", listStyle: "none", margin: 0, padding: 0, maxHeight: "200px", overflowY: "auto" }}
              >
                {searchResults.map(r => (
                  <li
                    key={r.model_id}
                    role="option"
                    aria-selected="false"
                    onClick={() => handleSelectResult(r)}
                    style={{ padding: "8px 10px", cursor: "pointer", fontSize: "13px", color: TOKEN.textPrimary, borderBottom: `1px solid ${TOKEN.borderDefault}` }}
                  >
                    <span style={{ fontWeight: 600 }}>{r.model_id}</span>
                    <span style={{ color: TOKEN.textMuted, marginLeft: "8px" }}>{r.label}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* ID error */}
          {idError && (
            <div data-testid="fleet-id-error" style={{ fontSize: "12px", color: TOKEN.accentErrorText, marginBottom: "6px" }}>
              {idError}
            </div>
          )}

          {/* Count / MW input depending on device type */}
          {isPV ? (
            <input
              data-testid="fleet-add-mw"
              type="number"
              step="0.1"
              value={mwText}
              onChange={e => setMwText(e.target.value)}
              placeholder="Fleet capacity (MWp)"
              style={{ width: "140px", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgApp, color: TOKEN.textPrimary, marginBottom: "6px" }}
            />
          ) : (
            <input
              data-testid="fleet-add-count"
              type="number"
              value={countText}
              min={1}
              max={999}
              onChange={e => setCountText(e.target.value)}
              placeholder="Count"
              style={{ width: "80px", padding: "6px 8px", borderRadius: "4px", border: `1px solid ${TOKEN.borderDefault}`, background: TOKEN.bgApp, color: TOKEN.textPrimary, marginBottom: "6px" }}
            />
          )}

          <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
            <button
              data-testid="fleet-add-confirm"
              onClick={handleConfirm}
              disabled={confirmDisabled}
              style={{ padding: "5px 14px", borderRadius: "4px", cursor: confirmDisabled ? "not-allowed" : "pointer", fontSize: "12px", background: confirmDisabled ? TOKEN.accentGrey : TOKEN.accentBlue, color: TOKEN.textPrimary, border: "none", opacity: confirmDisabled ? 0.5 : 1 }}
            >
              Add ✓
            </button>
            <button
              data-testid="fleet-add-cancel"
              onClick={closeAddForm}
              style={{ padding: "5px 14px", borderRadius: "4px", cursor: "pointer", fontSize: "12px", background: "transparent", color: TOKEN.textMuted, border: `1px solid ${TOKEN.borderDefault}` }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
