import type { RunInfo, SiteConfig } from "../types/telemetry";

// ─── Public API ──────────────────────────────────────────────────────────────

export interface RestClientOptions {
  baseUrl: string;
  /** Request timeout in ms. Default: 30_000. Uses Promise.race for fake-timer compat. */
  timeoutMs?: number;
}

export interface RestClient {
  getRuns: () => Promise<RunInfo[]>;
  getSiteConfig: (siteId: string) => Promise<SiteConfig>;
}

// ─── Implementation ──────────────────────────────────────────────────────────

function makeTimeoutPromise(ms: number, url: string): Promise<never> {
  return new Promise((_, reject) => {
    setTimeout(() => {
      reject(new Error(`timeout: ${url} did not respond within ${ms}ms`));
    }, ms);
  });
}

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const fetchPromise = fetch(url);
  return Promise.race([fetchPromise, makeTimeoutPromise(timeoutMs, url)]);
}

async function fetchJson<T>(url: string, timeoutMs: number): Promise<T> {
  let response: Response;
  try {
    response = await fetchWithTimeout(url, timeoutMs);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    // Re-throw timeout errors as-is so they match /timeout/
    if (msg.startsWith("timeout:")) {
      throw err;
    }
    throw new Error(`network_error: ${msg}`);
  }

  if (!response.ok) {
    const statusClass = Math.floor(response.status / 100);
    if (statusClass === 4) {
      throw new Error(`http_4xx: ${response.status} ${response.url}`);
    }
    if (statusClass === 5) {
      throw new Error(`http_5xx: ${response.status} ${response.url}`);
    }
    throw new Error(`http_error: ${response.status} ${response.url}`);
  }

  return response.json() as Promise<T>;
}

/**
 * Factory that creates a typed REST client for the Energy GO serving API.
 * All ¥/MW/MWh fields are returned as-is from the wire; no conversion is done here.
 */
export function createRestClient(opts: RestClientOptions): RestClient {
  const { baseUrl, timeoutMs = 30_000 } = opts;

  return {
    getRuns(): Promise<RunInfo[]> {
      return fetchJson<RunInfo[]>(`${baseUrl}/runs`, timeoutMs);
    },

    getSiteConfig(siteId: string): Promise<SiteConfig> {
      return fetchJson<SiteConfig>(`${baseUrl}/site/${encodeURIComponent(siteId)}/config`, timeoutMs);
    },
  };
}
