/**
 * Test suite: inference_session (task #27)
 *
 * Framework: Vitest + React Testing Library
 * Contract:  contracts/frontend/inference_session.md
 * Spec refs: contracts/serving/inference_stream.md (session lifecycle, D24 speed)
 *            contracts/serving/rest_api.md (GET /runs/latest)
 *
 * Tests are intentionally RED before implementation.
 * Per contract-first-dev: no reviewer-approved test may be modified to make it pass.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

// ─── Mocks (module-level, hoisted by Vitest) ─────────────────────────────────

// Mock telemetryWsClient so we can spy on .send() without a real socket
vi.mock("../../src/clients/wsClientSingleton", () => ({
  telemetryWsClient: { connect: vi.fn(), disconnect: vi.fn(), send: vi.fn() },
  trainingWsClient:  { connect: vi.fn(), disconnect: vi.fn(), send: vi.fn() },
  TELEMETRY_WS_URL: "/ws/inference",
  TRAINING_WS_URL: "/ws/training/stream",
  handleEnvStep: vi.fn(),
  handleTrainMetrics: vi.fn(),
  handleStatusChange: vi.fn(),
}));

// Mock restClientSingleton so we can control getLatestRun responses
vi.mock("../../src/clients/restClientSingleton", () => ({
  restClient: {
    getRuns: vi.fn(),
    getLatestRun: vi.fn(),
    getSiteConfig: vi.fn(),
  },
}));

// Mock SiteScene and SceneMountPoint for SiteView rendering tests
vi.mock("../../src/scene/SiteScene", () => ({
  SiteScene: ({ containerEl }: { containerEl: HTMLDivElement | null }) => (
    <div data-testid="site-scene" data-container-set={containerEl !== null ? "true" : "false"} />
  ),
}));
vi.mock("../../src/components/SceneMountPoint", () => ({
  SceneMountPoint: ({ onReady }: { onReady?: (el: HTMLDivElement) => void }) => {
    const ref = (el: HTMLDivElement | null) => { if (el && onReady) onReady(el); };
    return <div data-testid="scene-mount-point" ref={ref} />;
  },
}));
vi.mock("../../src/routes/LiveDashboard", () => ({
  LiveDashboard: () => <div data-testid="live-dashboard" />,
}));

// ─── Golden fixtures (from inference_stream.md) ───────────────────────────────

const STATUS_READY = {
  kind: "status" as const,
  state: "ready" as const,
  session_id: null,
  step: 0,
  episode: 0,
  run_id: null,
  site_id: null,
};

const STATUS_RUNNING = {
  kind: "status" as const,
  state: "running" as const,
  session_id: "550e8400-e29b-41d4-a716-446655440000",
  step: 5,
  episode: 1,
  run_id: "run_001",
  site_id: "gansu",
};

const STATUS_PAUSED = {
  kind: "status" as const,
  state: "paused" as const,
  session_id: "550e8400-e29b-41d4-a716-446655440000",
  step: 12,
  episode: 1,
  run_id: "run_001",
  site_id: "gansu",
};

const STATUS_STOPPED = {
  kind: "status" as const,
  state: "stopped" as const,
  session_id: null,
  step: 42,
  episode: 1,
  run_id: null,
  site_id: null,
};

const ERROR_POLICY_NOT_FOUND = {
  kind: "error" as const,
  code: "policy_not_found" as const,
  message: "No policy.npz or policy.onnx found in run_001",
};

const ERROR_NO_SESSION = {
  kind: "error" as const,
  code: "no_session" as const,
  message: "No active session",
};

const RUN_INFO_LATEST = {
  id: "run_001",
  created_at: "2026-06-10T08:00:00Z",
  episodes_trained: 150,
  latest_eval_reward: -0.4321,
  has_policy: true,
};

// ─── §IS1–§IS5: WsClient send() + onServerStatus/onServerError ───────────────

describe("§IS1–§IS5 — WsClient send() and server frame routing", () => {
  let MockWebSocket: ReturnType<typeof vi.fn>;
  let mockWsInstance: {
    send: ReturnType<typeof vi.fn>;
    readyState: number;
    onopen: (() => void) | null;
    onmessage: ((e: MessageEvent) => void) | null;
    onerror: (() => void) | null;
    onclose: (() => void) | null;
  };

  beforeEach(() => {
    mockWsInstance = {
      send: vi.fn(),
      readyState: WebSocket.OPEN,
      onopen: null,
      onmessage: null,
      onerror: null,
      onclose: null,
    };
    MockWebSocket = vi.fn().mockImplementation(() => mockWsInstance);
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("§IS1 — createWsClient returns an object with send() method", async () => {
    const { createWsClient } = await vi.importActual<typeof import("../../src/clients/wsClient")>(
      "../../src/clients/wsClient"
    );
    const client = createWsClient({
      url: "ws://localhost/ws/inference",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    expect(typeof client.send).toBe("function");
  });

  it("§IS2 — send() is a no-op when not connected (ws === null)", async () => {
    const { createWsClient } = await vi.importActual<typeof import("../../src/clients/wsClient")>(
      "../../src/clients/wsClient"
    );
    const client = createWsClient({
      url: "ws://localhost/ws/inference",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    // DO NOT call connect() — ws is null
    expect(() => client.send({ cmd: "pause" })).not.toThrow();
    // MockWebSocket not instantiated → ws.send never called
    expect(MockWebSocket).not.toHaveBeenCalled();
  });

  it("§IS3 — send() calls ws.send(JSON.stringify(msg)) when connected", async () => {
    const { createWsClient } = await vi.importActual<typeof import("../../src/clients/wsClient")>(
      "../../src/clients/wsClient"
    );
    const client = createWsClient({
      url: "ws://localhost/ws/inference",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
    });
    client.connect();
    // Simulate open
    mockWsInstance.onopen?.();
    const cmd = { cmd: "start", run_id: "run_001", site_id: "gansu", speed: 1.0 };
    client.send(cmd);
    expect(mockWsInstance.send).toHaveBeenCalledOnce();
    expect(mockWsInstance.send).toHaveBeenCalledWith(JSON.stringify(cmd));
  });

  it("§IS4 — handleMessage dispatches kind='status' to onServerStatus callback", async () => {
    const { createWsClient } = await vi.importActual<typeof import("../../src/clients/wsClient")>(
      "../../src/clients/wsClient"
    );
    const onServerStatus = vi.fn();
    createWsClient({
      url: "ws://localhost/ws/inference",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
      onServerStatus,
    }).connect();
    mockWsInstance.onmessage?.({ data: JSON.stringify(STATUS_READY) } as MessageEvent);
    expect(onServerStatus).toHaveBeenCalledOnce();
    expect(onServerStatus.mock.calls[0][0]).toMatchObject({ kind: "status", state: "ready" });
  });

  it("§IS5 — handleMessage dispatches kind='error' to onServerError callback", async () => {
    const { createWsClient } = await vi.importActual<typeof import("../../src/clients/wsClient")>(
      "../../src/clients/wsClient"
    );
    const onServerError = vi.fn();
    createWsClient({
      url: "ws://localhost/ws/inference",
      onEnvStep: vi.fn(),
      onTrainMetrics: vi.fn(),
      onEvalCompare: vi.fn(),
      onStatusChange: vi.fn(),
      onServerError,
    }).connect();
    mockWsInstance.onmessage?.({ data: JSON.stringify(ERROR_POLICY_NOT_FOUND) } as MessageEvent);
    expect(onServerError).toHaveBeenCalledOnce();
    expect(onServerError.mock.calls[0][0]).toMatchObject({ kind: "error", code: "policy_not_found" });
  });
});

// ─── §IS6–§IS7: restClient.getLatestRun() ────────────────────────────────────

describe("§IS6–§IS7 — restClient.getLatestRun()", () => {
  beforeEach(() => vi.resetModules());
  afterEach(() => vi.restoreAllMocks());

  it("§IS6 — getLatestRun() calls GET /api/runs/latest", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => RUN_INFO_LATEST,
    } as Response);

    const { createRestClient } = await vi.importActual<typeof import("../../src/clients/restClient")>(
      "../../src/clients/restClient"
    );
    const client = createRestClient({ baseUrl: "/api" });
    const result = await client.getLatestRun();
    expect(fetchSpy).toHaveBeenCalledWith(expect.stringMatching(/\/api\/runs\/latest/));
    expect(result).toMatchObject({ id: "run_001" });
  });

  it("§IS7 — getLatestRun() throws Error('no_runs_found') on HTTP 404", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 404,
      url: "/api/runs/latest",
    } as Response);

    const { createRestClient } = await vi.importActual<typeof import("../../src/clients/restClient")>(
      "../../src/clients/restClient"
    );
    const client = createRestClient({ baseUrl: "/api" });
    await expect(client.getLatestRun()).rejects.toThrow("no_runs_found");
  });
});

// ─── §IS8–§IS18: inferenceSessionStore ───────────────────────────────────────

describe("§IS8–§IS18 — inferenceSessionStore", () => {
  // Import the store and mocked singletons fresh each test
  let store: typeof import("../../src/stores/inferenceSessionStore").inferenceSessionStore;
  let mockTelemetryWsClient: { send: ReturnType<typeof vi.fn> };
  let mockRestClient: { getLatestRun: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    vi.resetModules();
    // Re-import mocked deps after resetModules
    const singleton = await import("../../src/clients/wsClientSingleton");
    mockTelemetryWsClient = singleton.telemetryWsClient as unknown as { send: ReturnType<typeof vi.fn> };
    const restSingleton = await import("../../src/clients/restClientSingleton");
    mockRestClient = restSingleton.restClient as unknown as { getLatestRun: ReturnType<typeof vi.fn> };
    // Reset mocks
    vi.clearAllMocks();
    // Fresh store import (after resetModules — gets a brand-new Zustand instance)
    const mod = await import("../../src/stores/inferenceSessionStore");
    store = mod.inferenceSessionStore;
  });

  it("§IS8 — initial state: serverState='idle', speed=1.0, others null/0", () => {
    const state = store.getState();
    expect(state.serverState).toBe("idle");
    expect(state.speed).toBe(1.0);
    expect(state.runId).toBeNull();
    expect(state.siteId).toBeNull();
    expect(state.sessionId).toBeNull();
    expect(state.step).toBe(0);
    expect(state.episode).toBe(0);
    expect(state.errorMsg).toBeNull();
  });

  it("§IS9 — handleServerStatus(ready) sets serverState='ready' and triggers _autoStart", async () => {
    mockRestClient.getLatestRun.mockResolvedValue(RUN_INFO_LATEST);
    await act(async () => {
      store.getState().handleServerStatus(STATUS_READY);
      // Let the auto-start promise settle
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(store.getState().serverState).not.toBe("idle");
    // _autoStart must have called getLatestRun
    expect(mockRestClient.getLatestRun).toHaveBeenCalled();
  });

  it("§IS10 — _autoStart success: sends cmd:start with correct fields", async () => {
    mockRestClient.getLatestRun.mockResolvedValue(RUN_INFO_LATEST);
    await act(async () => {
      store.getState().handleServerStatus(STATUS_READY);
      await new Promise((r) => setTimeout(r, 0)); // flush microtasks
    });
    expect(mockTelemetryWsClient.send).toHaveBeenCalledWith(
      expect.objectContaining({
        cmd: "start",
        run_id: "run_001",
        site_id: "gansu",
        speed: 1.0,
      })
    );
  });

  it("§IS11 — _autoStart with no_runs_found: serverState='error', errorMsg set", async () => {
    mockRestClient.getLatestRun.mockRejectedValue(new Error("no_runs_found"));
    await act(async () => {
      store.getState().handleServerStatus(STATUS_READY);
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(store.getState().serverState).toBe("error");
    expect(store.getState().errorMsg).toBeTruthy();
  });

  it("§IS12 — _autoStart with other REST error: serverState='error', errorMsg set", async () => {
    mockRestClient.getLatestRun.mockRejectedValue(new Error("http_5xx: 503 /api/runs/latest"));
    await act(async () => {
      store.getState().handleServerStatus(STATUS_READY);
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(store.getState().serverState).toBe("error");
    expect(store.getState().errorMsg).toBeTruthy();
  });

  it("§IS13 — handleServerStatus(running) updates serverState, step, episode", () => {
    store.getState().handleServerStatus(STATUS_RUNNING);
    const s = store.getState();
    expect(s.serverState).toBe("running");
    expect(s.step).toBe(5);
    expect(s.episode).toBe(1);
    expect(s.runId).toBe("run_001");
    expect(s.siteId).toBe("gansu");
    expect(s.sessionId).toBe("550e8400-e29b-41d4-a716-446655440000");
  });

  it("§IS14 — handleServerStatus(paused) updates serverState to 'paused'", () => {
    store.getState().handleServerStatus(STATUS_PAUSED);
    expect(store.getState().serverState).toBe("paused");
    expect(store.getState().step).toBe(12);
  });

  it("§IS15 — pause() sends {cmd:'pause'} via telemetryWsClient", () => {
    store.getState().pause();
    expect(mockTelemetryWsClient.send).toHaveBeenCalledWith({ cmd: "pause" });
  });

  it("§IS16 — resume() sends {cmd:'resume'} via telemetryWsClient", () => {
    store.getState().resume();
    expect(mockTelemetryWsClient.send).toHaveBeenCalledWith({ cmd: "resume" });
  });

  it("§IS17 — setSpeed clamps to [0, 100]", () => {
    store.getState().setSpeed(150);
    expect(store.getState().speed).toBe(100);
    store.getState().setSpeed(-5);
    expect(store.getState().speed).toBe(0);
    store.getState().setSpeed(2.5);
    expect(store.getState().speed).toBe(2.5);
  });

  it("§IS18 — handleServerError sets serverState='error' and errorMsg with code", () => {
    store.getState().handleServerError(ERROR_POLICY_NOT_FOUND);
    expect(store.getState().serverState).toBe("error");
    expect(store.getState().errorMsg).toContain("policy_not_found");
  });
});

// ─── §IS19–§IS24: SessionControlStrip component ──────────────────────────────

describe("§IS19–§IS24 — SessionControlStrip", () => {
  // Mock inferenceSessionStore so each test controls state
  let mockStoreState: {
    serverState: string;
    step: number;
    episode: number;
    speed: number;
    errorMsg: string | null;
    pause: ReturnType<typeof vi.fn>;
    resume: ReturnType<typeof vi.fn>;
    setSpeed: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    mockStoreState = {
      serverState: "idle",
      step: 0,
      episode: 0,
      speed: 1.0,
      errorMsg: null,
      pause: vi.fn(),
      resume: vi.fn(),
      setSpeed: vi.fn(),
    };
    vi.resetModules();
  });

  afterEach(() => vi.restoreAllMocks());

  async function renderStrip(overrides: Partial<typeof mockStoreState> = {}) {
    // Apply overrides
    Object.assign(mockStoreState, overrides);
    // Mock the store at module level for this test
    vi.doMock("../../src/stores/inferenceSessionStore", () => ({
      inferenceSessionStore: {
        getState: () => mockStoreState,
        // For useStore hook subscription pattern
        subscribe: vi.fn(() => () => {}),
      },
      // Also export the hook if the component uses it
      useInferenceSessionStore: (sel: (s: typeof mockStoreState) => unknown) => sel(mockStoreState),
    }));
    const { SessionControlStrip } = await import("../../src/components/SessionControlStrip");
    return render(<SessionControlStrip />);
  }

  it("§IS19 — running state: renders pause button", async () => {
    await renderStrip({ serverState: "running", step: 5, episode: 1 });
    expect(screen.getByTestId("session-pause-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("session-resume-btn")).not.toBeInTheDocument();
  });

  it("§IS20 — paused state: renders resume button, no pause button", async () => {
    await renderStrip({ serverState: "paused", step: 12, episode: 1 });
    expect(screen.getByTestId("session-resume-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("session-pause-btn")).not.toBeInTheDocument();
  });

  it("§IS21 — error state: renders error message and retry button", async () => {
    await renderStrip({ serverState: "error", errorMsg: "policy_not_found: no policy" });
    expect(screen.getByTestId("session-retry-btn")).toBeInTheDocument();
    expect(screen.getByTestId("session-status-label")).toHaveTextContent("policy_not_found");
  });

  it("§IS22 — session-status-label present in all states", async () => {
    for (const state of ["idle", "ready", "running", "paused", "stopped", "error"]) {
      const overrides: Partial<typeof mockStoreState> = { serverState: state };
      if (state === "error") overrides.errorMsg = "some error";
      await renderStrip(overrides);
      expect(screen.getByTestId("session-status-label")).toBeInTheDocument();
      // Clean up between iterations
      screen.unmount?.();
    }
  });

  it("§IS23 — clicking pause button calls store.pause()", async () => {
    await renderStrip({ serverState: "running" });
    fireEvent.click(screen.getByTestId("session-pause-btn"));
    expect(mockStoreState.pause).toHaveBeenCalledOnce();
  });

  it("§IS24 — clicking resume button calls store.resume()", async () => {
    await renderStrip({ serverState: "paused" });
    fireEvent.click(screen.getByTestId("session-resume-btn"));
    expect(mockStoreState.resume).toHaveBeenCalledOnce();
  });
});

// ─── §IS25: SiteView renders SessionControlStrip ─────────────────────────────

describe("§IS25 — SiteView renders SessionControlStrip", () => {
  beforeEach(() => vi.resetModules());

  it("§IS25 — SiteView renders data-testid='session-control-strip'", async () => {
    // Mock SessionControlStrip for this test
    vi.doMock("../../src/components/SessionControlStrip", () => ({
      SessionControlStrip: () => <div data-testid="session-control-strip" />,
    }));
    // Mock inferenceSessionStore (SiteView doesn't use it directly, but imports may cascade)
    vi.doMock("../../src/stores/inferenceSessionStore", () => ({
      inferenceSessionStore: { getState: () => ({ serverState: "idle" }), subscribe: vi.fn(() => () => {}) },
      useInferenceSessionStore: (sel: (s: { serverState: string }) => unknown) => sel({ serverState: "idle" }),
    }));
    const { default: SiteView } = await import("../../src/routes/SiteView");
    const { MemoryRouter } = await import("react-router-dom");
    render(<MemoryRouter><SiteView /></MemoryRouter>);
    expect(screen.getByTestId("session-control-strip")).toBeInTheDocument();
  });
});
