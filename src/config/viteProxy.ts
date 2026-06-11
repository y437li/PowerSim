/**
 * viteProxy — Vite dev-server proxy config for /api and /ws.
 * Contract: contracts/frontend/app_integration.md §1
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
 */

type ProxyEntry = {
  target: string;
  changeOrigin?: boolean;
  ws?: boolean;
  rewrite?: (path: string) => string;
};

export const VITE_PROXY_CONFIG: Record<string, ProxyEntry> = {
  "/api": {
    target: "http://localhost:8000",
    changeOrigin: true,
    rewrite: (path: string) =>
      path.replace(/^\/api(\/.*)?$/, (_, rest) => rest || "/"),
  },
  "/ws": {
    target: "ws://localhost:8000",
    ws: true,
    // No rewrite — /ws/inference and /ws/training/stream pass through verbatim
  },
};
