/**
 * viteProxy — Vite dev-server proxy config for /api and /ws.
 * Contract: contracts/frontend/app_integration.md §1
 *          contracts/frontend/configurable_ports.md §2 (env-driven port)
 *
 * Extracted to a plain TS module so it can be imported by both vite.config.ts
 * (build-time) and tests (jsdom) without triggering esbuild environment checks.
 *
 * Rewrite rule (§1): /^\/api(\/.*)?$/ → $1 || '/'
 *   /api/sites → /sites   (strip prefix, keep sub-path)
 *   /api       → /         (bare /api → root)
 *   /api/      → /         (trailing slash → root)
 *
 * The backend (FastAPI/uvicorn) exposes routes WITHOUT the /api prefix.
 * /ws proxies verbatim — /ws/inference and /ws/training/stream pass through unchanged.
 *
 * Port resolution (§2.1):
 *   1. Explicit `backendPort` argument — takes precedence, env var ignored.
 *   2. ENERGY_GO_BACKEND_PORT env var (parsed at call time, not module-load time).
 *   3. Default: 8000.
 */

type ProxyEntry = {
  target: string;
  changeOrigin?: boolean;
  ws?: boolean;
  rewrite?: (path: string) => string;
};

/**
 * Build the Vite dev-server proxy config for a given backend port.
 *
 * @param backendPort - Explicit port (1–65535). When provided, ENERGY_GO_BACKEND_PORT
 *                      is ignored. When omitted, reads process.env.ENERGY_GO_BACKEND_PORT
 *                      at call time and falls back to 8000 when the var is absent.
 */
export function buildViteProxy(backendPort?: number): Record<string, ProxyEntry> {
  const port =
    backendPort ??
    parseInt(process.env.ENERGY_GO_BACKEND_PORT ?? "8000", 10);

  return {
    "/api": {
      target: `http://localhost:${port}`,
      changeOrigin: true,
      rewrite: (path: string) =>
        path.replace(/^\/api(\/.*)?$/, (_, rest) => rest || "/"),
    },
    "/ws": {
      target: `ws://localhost:${port}`,
      ws: true,
      // No rewrite — /ws/inference and /ws/training/stream pass through verbatim
    },
  };
}

/**
 * Module-level constant — evaluated once at Vite startup, reads
 * ENERGY_GO_BACKEND_PORT from the process environment at that moment.
 *
 * Backward compatible: existing consumers (vite.config.ts, app_integration tests)
 * continue to work unchanged; when ENERGY_GO_BACKEND_PORT is not set this is
 * identical to the previous hardcoded `http://localhost:8000` / `ws://localhost:8000`.
 *
 * Contract: contracts/frontend/configurable_ports.md §2.2
 */
export const VITE_PROXY_CONFIG: Record<string, ProxyEntry> = buildViteProxy();
