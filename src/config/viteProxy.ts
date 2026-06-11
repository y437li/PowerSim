/**
 * viteProxy — Vite dev-server proxy config for /api and /ws.
 * Contract: contracts/frontend/app_integration.md §1
 *
 * Extracted to a plain TS module so it can be imported by both vite.config.ts
 * (build-time) and tests (jsdom) without triggering esbuild environment checks.
 *
 * STUB — implementation pending gate approval (PR #45).
 * Exported shape must match the acceptance criterion in contracts/frontend/app_integration.md §T1.
 */

export const VITE_PROXY_CONFIG = {} as Record<
  string,
  { target?: string; ws?: boolean; changeOrigin?: boolean; rewrite?: (path: string) => string }
>;
