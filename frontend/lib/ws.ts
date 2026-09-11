/** WebSocket client with automatic reconnect and exponential backoff.
 *
 *  The socket carries the high-frequency visualization payload, so a dropped
 *  connection must recover silently rather than leaving a frozen scene that
 *  looks live. `connected` is surfaced so the UI can say so honestly.
 */

export type Channel = "universe" | "signals" | "system" | "briefing";

export interface Envelope<T = unknown> {
  channel: Channel;
  at: string;
  data: T;
}

type Handler = (envelope: Envelope) => void;

/** Resolved at call time, not module load: NEXT_PUBLIC_* values are inlined at
 *  build time, and the Next dev/start proxy only rewrites HTTP - a WebSocket
 *  through it would hang. So by default the socket goes straight to the
 *  backend on its own port, on whichever host served the page. */
function resolveWsUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (typeof window === "undefined") return "ws://127.0.0.1:8000/ws";
  const secure = window.location.protocol === "https:";
  return `${secure ? "wss" : "ws"}://${window.location.hostname}:8000/ws`;
}

export class UniverseSocket {
  private socket: WebSocket | null = null;
  private handlers = new Set<Handler>();
  private statusHandlers = new Set<(connected: boolean) => void>();
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(private readonly channels: Channel[] = [
    "universe", "signals", "system", "briefing",
  ]) {}

  connect(): void {
    if (typeof window === "undefined") return;
    this.closed = false;
    const url = `${resolveWsUrl()}?channels=${this.channels.join(",")}`;

    try {
      this.socket = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.socket.onopen = () => {
      this.attempt = 0;
      this.statusHandlers.forEach((h) => h(true));
    };
    this.socket.onmessage = (event) => {
      try {
        const envelope = JSON.parse(event.data) as Envelope;
        this.handlers.forEach((h) => h(envelope));
      } catch {
        // A malformed frame is not worth tearing the connection down for.
      }
    };
    this.socket.onclose = () => {
      this.statusHandlers.forEach((h) => h(false));
      if (!this.closed) this.scheduleReconnect();
    };
    this.socket.onerror = () => this.socket?.close();
  }

  private scheduleReconnect(): void {
    if (this.timer) clearTimeout(this.timer);
    // 1s, 2s, 4s... capped at 30s so a long outage does not hammer the server.
    const delay = Math.min(30_000, 1000 * 2 ** this.attempt);
    this.attempt += 1;
    this.timer = setTimeout(() => this.connect(), delay);
  }

  /** Ask the server to push a fresh payload immediately. */
  refresh(): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send("refresh");
  }

  onMessage(handler: Handler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onStatus(handler: (connected: boolean) => void): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  close(): void {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.socket?.close();
    this.socket = null;
  }
}
