import type { TelemetryEnvelope, ServerStatusFrame, ServerErrorFrame } from "../types/telemetry";
import { validate } from "../validators/telemetryValidator";
import { useTelemetryStore } from "../stores/telemetryStore";
import type { FrameError } from "../stores/telemetryStore";

// ─── Public API ──────────────────────────────────────────────────────────────

export interface WsClientOptions {
  url: string;
  onEnvStep: (msg: TelemetryEnvelope) => void;
  onTrainMetrics: (msg: TelemetryEnvelope) => void;
  onEvalCompare: (msg: TelemetryEnvelope) => void;
  onStatusChange: (status: "connecting" | "connected" | "disconnected" | "stale") => void;
  /** Called when the server sends a kind="status" control frame. */
  onServerStatus?: (frame: ServerStatusFrame) => void;
  /** Called when the server sends a kind="error" control frame. */
  onServerError?: (frame: ServerErrorFrame) => void;
  /** Mark status 'stale' after this many ms with no messages. Default: 10_000 */
  staleAfterMs?: number;
  /** Base delay for exponential-backoff reconnect. Default: 1_000 */
  reconnectBaseMs?: number;
  /** Maximum reconnect delay. Default: 30_000 */
  reconnectMaxMs?: number;
}

export interface WsClient {
  connect: () => void;
  disconnect: () => void;
  /**
   * Send a JSON-serializable message to the server.
   * No-op if the WebSocket is not connected (ws === null) — callers should
   * wait for status:ready before sending commands.
   */
  send: (msg: unknown) => void;
}

// ─── Implementation ──────────────────────────────────────────────────────────

const SUPPORTED_MAJOR = 1;

/**
 * Build a FrameError from a raw (possibly malformed) message and a list of
 * error/warning codes. Falls back gracefully when envelope fields are absent.
 */
function buildFrameError(msg: unknown, errors: string[]): FrameError {
  const m = msg as Record<string, unknown> | null;
  return {
    ts_utc: typeof m?.ts_utc === "string" ? m.ts_utc : new Date().toISOString(),
    kind: typeof m?.kind === "string" ? m.kind : "unknown",
    seq: typeof m?.seq === "number" ? m.seq : -1,
    errors,
  };
}

/**
 * Convert a relative WebSocket path to an absolute ws:// / wss:// URL.
 *
 * `new WebSocket(url)` requires an absolute URL in jsdom and older browsers.
 * Vite's dev proxy rewrites `/ws/*` to `ws://localhost:8000/*`, so the
 * browser connects to the dev server which proxies to the backend — correct.
 *
 * Already-absolute URLs (ws:// or wss://) are returned unchanged so existing
 * test fixtures that pass absolute URLs continue to work.
 */
function resolveWsUrl(url: string): string {
  if (/^wss?:\/\//.test(url)) return url;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${url}`;
}

/** Parse the major version from a semver string, e.g. "1.5.0" → 1. */
function parseMajor(version: string): number {
  const parts = version.split(".");
  return parseInt(parts[0], 10);
}

/**
 * Factory that creates a managed WebSocket client with:
 *  - Schema-version rejection (major > SUPPORTED_MAJOR → disconnected)
 *  - Minor-version forward compatibility (ignore unknown fields in 1.x)
 *  - Stale detection (no message after staleAfterMs → 'stale')
 *  - Stale recovery (next message after stale → 'connected')
 *  - Exponential-backoff reconnect (±10% jitter, capped at reconnectMaxMs)
 *  - Clean disconnect
 */
export function createWsClient(opts: WsClientOptions): WsClient {
  const {
    url,
    onEnvStep,
    onTrainMetrics,
    onEvalCompare,
    onStatusChange,
    onServerStatus,
    onServerError,
    staleAfterMs = 10_000,
    reconnectBaseMs = 1_000,
    reconnectMaxMs = 30_000,
  } = opts;

  let ws: WebSocket | null = null;
  let staleTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempt = 0;
  let intentionalClose = false;
  let versionRejected = false;
  let currentStatus: "connecting" | "connected" | "disconnected" | "stale" = "disconnected";

  function setStatus(status: typeof currentStatus) {
    currentStatus = status;
    onStatusChange(status);
  }

  function clearStaleTimer() {
    if (staleTimer !== null) {
      clearTimeout(staleTimer);
      staleTimer = null;
    }
  }

  function resetStaleTimer() {
    clearStaleTimer();
    if (staleAfterMs > 0) {
      staleTimer = setTimeout(() => {
        setStatus("stale");
      }, staleAfterMs);
    }
  }

  function handleMessage(event: MessageEvent) {
    // If version was rejected on this socket, discard all further messages
    if (versionRejected) return;

    // Stale recovery: receiving a message resets status to 'connected'
    if (currentStatus === "stale") {
      setStatus("connected");
    }
    resetStaleTimer();

    let msg: any;
    try {
      msg = JSON.parse(event.data as string);
    } catch {
      console.warn("[wsClient] Discarding invalid JSON message");
      return;
    }

    // §4.3: Missing kind → discard always.
    if (typeof msg.kind !== "string") {
      console.warn("[wsClient] Discarding message with missing kind");
      return;
    }

    // Control frames (status, error) do NOT carry a payload wrapper — dispatch them
    // directly.  Data frames (env_step, train_metrics, eval_compare) MUST have a payload;
    // a missing payload on a data frame is dropped (D18 load-bearing guard).
    const isControlFrame = msg.kind === "status" || msg.kind === "error";
    if (!isControlFrame && msg.payload === undefined) {
      console.warn("[wsClient] Discarding data frame with missing payload");
      return;
    }

    // Schema version check applies to data frames only (control frames have no schema_version).
    if (!isControlFrame && typeof msg.schema_version === "string") {
      const major = parseMajor(msg.schema_version);
      if (major > SUPPORTED_MAJOR) {
        console.error(
          `[wsClient] Unsupported schema major version ${major} (supported: ${SUPPORTED_MAJOR}). Disconnecting.`
        );
        versionRejected = true;
        setStatus("disconnected");
        return;
      }
      // Minor forward compat: major === SUPPORTED_MAJOR but minor > 0 → accepted with unknown fields ignored
    }

    // §10 (D26 gate): call validate() on all data frames before dispatch.
    // Control frames (status, error) bypass — they carry no payload and
    // validate() would always reject them with missing_field:payload.
    if (!isControlFrame) {
      let vResult: ReturnType<typeof validate>;
      try {
        vResult = validate(msg);
      } catch {
        // §10.2: exception → treat as ok:false, errors:["validate_threw"]
        const err = buildFrameError(msg, ["validate_threw"]);
        console.warn(
          `[wsClient] INVALID frame dropped kind=${err.kind} seq=${err.seq}: [validate_threw]`
        );
        useTelemetryStore.getState().pushFrameError(err);
        return;
      }
      if (!vResult.ok) {
        const err = buildFrameError(msg, vResult.errors);
        console.warn(
          `[wsClient] INVALID frame dropped kind=${err.kind} seq=${err.seq}: [${vResult.errors.join(", ")}]`
        );
        useTelemetryStore.getState().pushFrameError(err);
        return;
      }
      // ok:true with warnings → dispatch AND record (§10.3)
      if (vResult.warnings.length > 0) {
        useTelemetryStore.getState().pushFrameError(buildFrameError(msg, vResult.warnings));
      }
    }

    // Dispatch by kind
    switch (msg.kind) {
      case "env_step":
        onEnvStep(msg as TelemetryEnvelope);
        break;
      case "train_metrics":
        onTrainMetrics(msg as TelemetryEnvelope);
        break;
      case "eval_compare":
        onEvalCompare(msg as TelemetryEnvelope);
        break;
      case "status":
        onServerStatus?.(msg as ServerStatusFrame);
        break;
      case "error":
        onServerError?.(msg as ServerErrorFrame);
        break;
      default:
        console.warn(`[wsClient] Unknown message kind: ${msg.kind}`);
        break;
    }
  }

  function open() {
    if (ws !== null) return; // already connecting/connected

    intentionalClose = false;
    versionRejected = false;
    ws = new WebSocket(resolveWsUrl(url));

    ws.onopen = () => {
      reconnectAttempt = 0;
      setStatus("connected");
      resetStaleTimer();
    };

    ws.onmessage = handleMessage;

    ws.onerror = (_ev) => {
      // Error will be followed by onclose — handle reconnect there
      console.warn("[wsClient] WebSocket error");
    };

    ws.onclose = () => {
      clearStaleTimer();
      ws = null;
      if (!intentionalClose) {
        setStatus("disconnected");
        scheduleReconnect();
      }
    };
  }

  function scheduleReconnect() {
    if (intentionalClose || versionRejected) return;

    // Exponential backoff: base * 2^attempt, ±10% jitter, capped at max
    const baseDelay = Math.min(
      reconnectBaseMs * Math.pow(2, reconnectAttempt),
      reconnectMaxMs
    );
    const jitter = baseDelay * 0.1 * (Math.random() * 2 - 1); // ±10%
    const delay = Math.max(0, baseDelay + jitter);
    reconnectAttempt++;

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, delay);
  }

  return {
    connect() {
      open();
    },

    disconnect() {
      intentionalClose = true;
      clearStaleTimer();
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (ws !== null) {
        ws.close();
        ws = null;
      }
    },

    send(msg: unknown) {
      // No-op when not connected — callers wait for status:ready before sending commands.
      if (ws === null) return;
      ws.send(JSON.stringify(msg));
    },
  };
}
