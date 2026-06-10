import type { TelemetryEnvelope } from "../types/telemetry";

// ─── Public API ──────────────────────────────────────────────────────────────

export interface WsClientOptions {
  url: string;
  onEnvStep: (msg: TelemetryEnvelope) => void;
  onTrainMetrics: (msg: TelemetryEnvelope) => void;
  onEvalCompare: (msg: TelemetryEnvelope) => void;
  onStatusChange: (status: "connecting" | "connected" | "disconnected" | "stale") => void;
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
}

// ─── Implementation ──────────────────────────────────────────────────────────

const SUPPORTED_MAJOR = 1;

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

    // §4.3: Missing required envelope fields → discard
    if (typeof msg.kind !== "string" || msg.payload === undefined) {
      console.warn("[wsClient] Discarding message with missing kind or payload");
      return;
    }

    // Schema version check: major > supported → reject and mark disconnected
    if (typeof msg.schema_version === "string") {
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

    // Dispatch by kind
    const envelope = msg as TelemetryEnvelope;
    switch (envelope.kind) {
      case "env_step":
        onEnvStep(envelope);
        break;
      case "train_metrics":
        onTrainMetrics(envelope);
        break;
      case "eval_compare":
        onEvalCompare(envelope);
        break;
      default:
        console.warn(`[wsClient] Unknown message kind: ${(envelope as any).kind}`);
        break;
    }
  }

  function open() {
    if (ws !== null) return; // already connecting/connected

    intentionalClose = false;
    versionRejected = false;
    ws = new WebSocket(url);

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
  };
}
