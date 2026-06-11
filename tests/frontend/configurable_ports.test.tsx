/**
 * tests/frontend/configurable_ports.test.tsx
 * Contract: contracts/frontend/configurable_ports.md §7 (§T_CP)
 *
 * Tests for env-driven dev ports:
 *  - buildViteProxy(port?) — explicit port or ENERGY_GO_BACKEND_PORT env var
 *  - VITE_PROXY_CONFIG — module-level const (backward compat, defaults :8000)
 *
 * Strategy: import buildViteProxy and call it directly with explicit ports (CP.1–CP.4)
 * to avoid env-var manipulation. For env-driven tests (CP.5–CP.7) we save/restore
 * process.env.ENERGY_GO_BACKEND_PORT around the call — safe because buildViteProxy()
 * reads the env at call time, not module-load time.
 *
 * The rewrite tests (CP.10–CP.11) call the rewrite function extracted from the returned
 * config to assert path-stripping behaviour is independent of port.
 */

import { describe, it, expect, afterEach } from "vitest";
import { buildViteProxy, VITE_PROXY_CONFIG } from "../../src/config/viteProxy";

// Helper: ProxyEntry shape (mirrors viteProxy.ts internal type)
type ProxyEntry = {
  target: string;
  changeOrigin?: boolean;
  ws?: boolean;
  rewrite?: (path: string) => string;
};

// ─── Save / restore ENERGY_GO_BACKEND_PORT between env-driven tests ───────────
const ORIGINAL_BACKEND_PORT = process.env.ENERGY_GO_BACKEND_PORT;
afterEach(() => {
  if (ORIGINAL_BACKEND_PORT === undefined) {
    delete process.env.ENERGY_GO_BACKEND_PORT;
  } else {
    process.env.ENERGY_GO_BACKEND_PORT = ORIGINAL_BACKEND_PORT;
  }
});

// ─── CP.1/CP.2: explicit port 8000 ───────────────────────────────────────────
describe("CP.1 — buildViteProxy(8000) → /api target", () => {
  it("is http://localhost:8000", () => {
    const config = buildViteProxy(8000);
    expect((config["/api"] as ProxyEntry).target).toBe("http://localhost:8000");
  });
});

describe("CP.2 — buildViteProxy(8000) → /ws target", () => {
  it("is ws://localhost:8000", () => {
    const config = buildViteProxy(8000);
    expect((config["/ws"] as ProxyEntry).target).toBe("ws://localhost:8000");
  });
});

// ─── CP.3/CP.4: explicit alternate port 8801 ─────────────────────────────────
describe("CP.3 — buildViteProxy(8801) → /api target", () => {
  it("is http://localhost:8801", () => {
    const config = buildViteProxy(8801);
    expect((config["/api"] as ProxyEntry).target).toBe("http://localhost:8801");
  });
});

describe("CP.4 — buildViteProxy(8801) → /ws target", () => {
  it("is ws://localhost:8801", () => {
    const config = buildViteProxy(8801);
    expect((config["/ws"] as ProxyEntry).target).toBe("ws://localhost:8801");
  });
});

// ─── CP.5: env unset → default :8000 ─────────────────────────────────────────
describe("CP.5 — buildViteProxy() with ENERGY_GO_BACKEND_PORT unset → /api target", () => {
  it("defaults to http://localhost:8000", () => {
    delete process.env.ENERGY_GO_BACKEND_PORT;
    const config = buildViteProxy();
    expect((config["/api"] as ProxyEntry).target).toBe("http://localhost:8000");
  });
});

// ─── CP.6/CP.7: env set to "9001" ────────────────────────────────────────────
describe("CP.6 — buildViteProxy() with ENERGY_GO_BACKEND_PORT='9001' → /api target", () => {
  it("is http://localhost:9001", () => {
    process.env.ENERGY_GO_BACKEND_PORT = "9001";
    const config = buildViteProxy();
    expect((config["/api"] as ProxyEntry).target).toBe("http://localhost:9001");
  });
});

describe("CP.7 — buildViteProxy() with ENERGY_GO_BACKEND_PORT='9001' → /ws target", () => {
  it("is ws://localhost:9001", () => {
    process.env.ENERGY_GO_BACKEND_PORT = "9001";
    const config = buildViteProxy();
    expect((config["/ws"] as ProxyEntry).target).toBe("ws://localhost:9001");
  });
});

// ─── CP.8/CP.9: option flags ──────────────────────────────────────────────────
describe("CP.8 — /api has changeOrigin: true", () => {
  it("for buildViteProxy(8000)", () => {
    const config = buildViteProxy(8000);
    expect((config["/api"] as ProxyEntry).changeOrigin).toBe(true);
  });
});

describe("CP.9 — /ws has ws: true", () => {
  it("for buildViteProxy(8000)", () => {
    const config = buildViteProxy(8000);
    expect((config["/ws"] as ProxyEntry).ws).toBe(true);
  });
});

// ─── CP.10/CP.11: /api rewrite rule (unchanged with custom port) ──────────────
describe("CP.10 — /api rewrite: /api/sites → /sites (port-agnostic)", () => {
  it("strips /api prefix and preserves sub-path", () => {
    const config = buildViteProxy(8801);
    const rewrite = (config["/api"] as ProxyEntry).rewrite;
    expect(rewrite).toBeDefined();
    expect(rewrite!("/api/sites")).toBe("/sites");
  });
});

describe("CP.11 — /api rewrite: bare /api → /", () => {
  it("maps bare /api to root /", () => {
    const config = buildViteProxy(8801);
    const rewrite = (config["/api"] as ProxyEntry).rewrite;
    expect(rewrite).toBeDefined();
    expect(rewrite!("/api")).toBe("/");
  });
});

// ─── CP.12: VITE_PROXY_CONFIG module const backward compat ───────────────────
describe("CP.12 — VITE_PROXY_CONFIG module const defaults to :8000 when env unset", () => {
  it("/api target is http://localhost:8000 (module-load default)", () => {
    // VITE_PROXY_CONFIG is buildViteProxy() evaluated at import time.
    // In this test environment ENERGY_GO_BACKEND_PORT is not set, so it defaults to 8000.
    // This asserts backward compatibility: existing consumers of VITE_PROXY_CONFIG are unaffected.
    expect((VITE_PROXY_CONFIG["/api"] as ProxyEntry).target).toBe("http://localhost:8000");
  });
});

// ─── reviewer (frontend-reviewer): CP.13 — explicit arg precedence over a SET env var ──
// CP.3/CP.4 pass an explicit port but with the env var UNSET, so they don't prove §2.1's
// rule that an explicit `backendPort` arg WINS over `ENERGY_GO_BACKEND_PORT`. An env-first
// impl (`env ? parseInt(env) : (arg ?? 8000)`) would pass all 12 CP tests yet violate it.
// This pins precedence: env=9001 AND buildViteProxy(8801) → 8801 (arg wins, env ignored).
describe("CP.13 (reviewer) — explicit arg takes precedence over a set ENERGY_GO_BACKEND_PORT (§2.1)", () => {
  it("env='9001' + buildViteProxy(8801) → /api target is :8801 (explicit wins, env ignored)", () => {
    process.env.ENERGY_GO_BACKEND_PORT = "9001";
    const config = buildViteProxy(8801);
    expect((config["/api"] as ProxyEntry).target).toBe("http://localhost:8801");
    expect((config["/ws"] as ProxyEntry).target).toBe("ws://localhost:8801");
  });
});
