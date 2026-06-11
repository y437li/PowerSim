/**
 * Tests: frontend/error_boundary_reset_key
 * Contract: contracts/frontend/error_boundary_reset_key.md
 * Task: #30
 *
 * EB.RK.1–EB.RK.7: ErrorBoundary resetKey self-heal after non-telemetry render crashes.
 *
 * RED until:
 *   - ErrorBoundary gains `resetKey?: string | number` prop + getDerivedStateFromProps
 *     reset logic (§2)
 *   - App.tsx wires `resetKey={runId ?? ""}` to the top-level ErrorBoundary (§3)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen, cleanup, act } from "@testing-library/react";

// Static import — ErrorBoundary does not need per-test isolation (no doMock).
import { ErrorBoundary } from "../../src/components/ErrorBoundary";
import { useTelemetryStore } from "../../src/stores/telemetryStore";

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** A child that throws on render when `shouldThrow` is true. */
function MaybeThrow({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("simulated non-telemetry render crash");
  return <div data-testid="child-ok">OK</div>;
}

beforeEach(() => {
  // Suppress React's console.error for caught errors (keeps test output clean).
  vi.spyOn(console, "error").mockImplementation(() => {});
  // Reset telemetryStore between tests.
  useTelemetryStore.getState().clearHistory();
  useTelemetryStore.getState().setWsStatus("disconnected");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// ─── EB.RK.1: Existing behaviour unchanged when resetKey is absent ────────────

describe("EB.RK.1 — resetKey absent: sticky error (existing behaviour preserved)", () => {
  it("crash → error UI shown; no resetKey → boundary stays in error state on rerender", () => {
    const { rerender } = render(
      <ErrorBoundary>
        <MaybeThrow shouldThrow={true} />
      </ErrorBoundary>
    );
    // Error UI shown — child not rendered
    expect(screen.queryByTestId("child-ok")).toBeNull();
    expect(screen.getByRole("alert")).toBeDefined();

    // No resetKey — rerender with fixed child: boundary is sticky, error persists
    rerender(
      <ErrorBoundary>
        <MaybeThrow shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.queryByTestId("child-ok")).toBeNull();
  });
});

// ─── EB.RK.2: resetKey change resets boundary ────────────────────────────────

describe("EB.RK.2 — resetKey change: crash → new key → children re-render", () => {
  it("crash with key='a' → fix child + change key to 'b' → child-ok visible", () => {
    let shouldThrow = true;
    const ThrowOnMount = () => {
      if (shouldThrow) throw new Error("simulated crash");
      return <div data-testid="child-ok">OK</div>;
    };

    const { rerender } = render(
      <ErrorBoundary resetKey="session-a">
        <ThrowOnMount />
      </ErrorBoundary>
    );
    // Crash → error UI
    expect(screen.queryByTestId("child-ok")).toBeNull();
    expect(screen.getByRole("alert")).toBeDefined();

    // Fix the child, then change the key → boundary must reset
    shouldThrow = false;
    rerender(
      <ErrorBoundary resetKey="session-b">
        <ThrowOnMount />
      </ErrorBoundary>
    );
    expect(screen.getByTestId("child-ok")).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// ─── EB.RK.3: Same resetKey value does NOT reset ─────────────────────────────

describe("EB.RK.3 — same resetKey: crash → same key rerender → error UI persists", () => {
  it("crash with key='a' → rerender with key='a' → still in error state", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="session-a">
        <MaybeThrow shouldThrow={true} />
      </ErrorBoundary>
    );
    expect(screen.queryByTestId("child-ok")).toBeNull();

    // Same key → no reset (child fixed but boundary stuck)
    rerender(
      <ErrorBoundary resetKey="session-a">
        <MaybeThrow shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.queryByTestId("child-ok")).toBeNull();
  });
});

// ─── EB.RK.4: resetKey change while NOT in error state — no flash ─────────────

describe("EB.RK.4 — resetKey change with no error: children render normally throughout", () => {
  it("no crash, key='a' → key='b' → child-ok still visible (no flash of error UI)", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="session-a">
        <MaybeThrow shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.getByTestId("child-ok")).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();

    rerender(
      <ErrorBoundary resetKey="session-b">
        <MaybeThrow shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.getByTestId("child-ok")).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// ─── EB.RK.5: Re-crash after reset — boundary catches again ───────────────────

describe("EB.RK.5 — re-crash after reset: boundary catches the second crash too", () => {
  it("crash → reset key → child still throws → boundary catches again, error UI shown", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="session-a">
        <MaybeThrow shouldThrow={true} />
      </ErrorBoundary>
    );
    expect(screen.queryByTestId("child-ok")).toBeNull();

    // Change key but child STILL throws → boundary should catch again
    rerender(
      <ErrorBoundary resetKey="session-b">
        <MaybeThrow shouldThrow={true} />
      </ErrorBoundary>
    );
    // After reset + re-crash, error UI shown again (not stale pre-reset state)
    expect(screen.queryByTestId("child-ok")).toBeNull();
    expect(screen.getByRole("alert")).toBeDefined();
  });
});

// ─── EB.RK.6: Wiring via telemetryStore.runId ────────────────────────────────
//
// Tests the behavioral contract: an ErrorBoundary whose resetKey is wired to
// telemetryStore.runId self-heals when runId advances.
// This mirrors the App.tsx wiring without needing to render the full app tree.

describe("EB.RK.6 — runId-wired ErrorBoundary: runId change triggers self-heal (§3)", () => {
  it("crash → runId advances in store → consumer re-renders with new resetKey → boundary resets", () => {
    // A consumer that reads runId and passes it as resetKey — mirrors App.tsx §3 pattern.
    // resetKey={runId ?? ""} means initial null → "", then actual run_id values.
    let shouldThrow = true;
    const ThrowOnMount = () => {
      if (shouldThrow) throw new Error("simulated crash");
      return <div data-testid="child-ok">OK</div>;
    };

    function RunIdBoundary() {
      const runId = useTelemetryStore((s) => s.runId);
      return (
        <ErrorBoundary resetKey={runId ?? ""}>
          <ThrowOnMount />
        </ErrorBoundary>
      );
    }

    render(<RunIdBoundary />);
    // Crash → error UI
    expect(screen.queryByTestId("child-ok")).toBeNull();
    expect(screen.getByRole("alert")).toBeDefined();

    // Simulate new run arriving: update runId in store, fix child.
    // act() ensures React processes the Zustand re-render triggered by the store update.
    shouldThrow = false;
    act(() => {
      useTelemetryStore.getState().receiveEnvStep({
      kind: "env_step",
      ts_utc: "2026-06-11T00:00:00Z",
      run_id: "run-xyz-001",
      seq: 0,
      schema_version: "1.0.0",
        payload: {} as any,  // store only reads run_id/seq from the envelope
      });
    });

    // The boundary's resetKey is now "run-xyz-001" (changed from "")
    // → boundary must reset and re-render children
    expect(screen.getByTestId("child-ok")).toBeDefined();
  });
});

// ─── EB.RK.7: prevResetKey tracking prevents double-reset ────────────────────

describe("EB.RK.7 — prevResetKey tracking: re-render with same new key does not re-reset", () => {
  it("crash → change key 'a'→'b' → rerender with key='b' again → children still visible", () => {
    let shouldThrow = true;
    const ThrowOnMount = () => {
      if (shouldThrow) throw new Error("simulated crash");
      return <div data-testid="child-ok">OK</div>;
    };

    const { rerender } = render(
      <ErrorBoundary resetKey="session-a">
        <ThrowOnMount />
      </ErrorBoundary>
    );
    expect(screen.queryByTestId("child-ok")).toBeNull();

    // Reset: fix child + change key
    shouldThrow = false;
    rerender(
      <ErrorBoundary resetKey="session-b">
        <ThrowOnMount />
      </ErrorBoundary>
    );
    expect(screen.getByTestId("child-ok")).toBeDefined();

    // Re-render with the SAME new key — prevResetKey is now "session-b",
    // so no reset should occur and children remain visible
    rerender(
      <ErrorBoundary resetKey="session-b">
        <ThrowOnMount />
      </ErrorBoundary>
    );
    expect(screen.getByTestId("child-ok")).toBeDefined();
  });
});
