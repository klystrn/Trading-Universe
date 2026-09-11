/** Typed API client. Every call funnels through `request` so errors surface
 *  consistently rather than as unhandled rejections deep in a component. */

import type {
  Briefing, CandleResponse, PoliticalTransaction, Portfolio, QuestionAnswer,
  Recommendation, SearchResult, Signal, StrategyInfo, SystemHealth, Trade,
  UniversePayload, WatchlistEntry,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** True when the failure means the backend is still starting rather than
 *  broken: a network refusal while the container boots, the hosting
 *  provider's 502/504 while it routes to a waking instance, or our own 503
 *  "warming up" while the first scan runs. */
export function isWakingError(error: unknown): boolean {
  if (error instanceof ApiError) return [502, 503, 504].includes(error.status);
  return error instanceof TypeError; // fetch() rejects with TypeError on network failure
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // A non-JSON error body is not worth failing over.
    }
    throw new ApiError(detail, response.status, path);
  }
  return response.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | boolean | undefined>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const out = search.toString();
  return out ? `?${out}` : "";
};

export const api = {
  // --- universe ----------------------------------------------------------
  universe: () => request<UniversePayload>("/api/universe"),
  briefing: () => request<Briefing>("/api/universe/briefing"),
  sectors: () => request<unknown[]>("/api/universe/sectors"),
  stock: (ticker: string) =>
    request<Record<string, unknown>>(`/api/universe/stock/${ticker}`),
  candles: (ticker: string, interval = "1d", limit = 260) =>
    request<CandleResponse>(
      `/api/universe/candles/${ticker}${qs({ interval, limit })}`,
    ),

  // --- signals ------------------------------------------------------------
  signals: (params: {
    strategy?: string;
    sector?: string;
    min_score?: number;
    executable_only?: boolean;
    limit?: number;
  } = {}) =>
    request<{
      generated_at: string | null;
      count: number;
      active_strategy: string | null;
      signals: Signal[];
    }>(`/api/signals${qs(params)}`),
  rejectedSignals: (limit = 100) =>
    request<{ count: number; signals: Record<string, unknown>[] }>(
      `/api/signals/rejected${qs({ limit })}`,
    ),
  nearMisses: (limit = 50) =>
    request<{
      count: number;
      near_misses: {
        ticker: string;
        strategy: string;
        failed: string[];
        passed: string[];
      }[];
    }>(`/api/signals/near-misses${qs({ limit })}`),
  thesis: (signalId: string) =>
    request<Record<string, unknown>>(`/api/signals/${signalId}/thesis`),

  // --- strategy ------------------------------------------------------------
  strategies: () =>
    request<{ active_strategy: string | null; strategies: StrategyInfo[] }>(
      "/api/strategy",
    ),
  recommendation: () => request<Recommendation>("/api/strategy/recommendation"),
  sectorRecommendations: () =>
    request<{ execution_model: string; sectors: unknown[] }>(
      "/api/strategy/sector-recommendations",
    ),
  acceptRecommendation: () =>
    request<{ active_strategy: string; overridden: boolean }>(
      "/api/strategy/accept",
      { method: "POST" },
    ),
  overrideStrategy: (strategyId: string) =>
    request<{ active_strategy: string | null; overridden: boolean }>(
      "/api/strategy/override",
      { method: "POST", body: JSON.stringify({ strategy_id: strategyId }) },
    ),

  // --- portfolio and trades ---------------------------------------------------
  portfolio: () => request<Portfolio>("/api/portfolio"),
  capacity: () => request<Record<string, number | boolean>>("/api/portfolio/capacity"),
  trades: (params: Record<string, string | number | boolean | undefined> = {}) =>
    request<{ count: number; trades: Trade[] }>(`/api/trades${qs(params)}`),
  tradeFilters: () =>
    request<{
      strategies: { id: string; label: string }[];
      sectors: { id: string; label: string }[];
      results: string[];
      execution_sources: string[];
    }>("/api/trades/filters/options"),
  tradeThesis: (tradeId: string) =>
    request<Record<string, unknown>>(`/api/trades/${tradeId}/thesis`),

  // --- political -------------------------------------------------------------
  political: (params: Record<string, string | number | undefined> = {}) =>
    request<{ count: number; transactions: PoliticalTransaction[] }>(
      `/api/political/transactions${qs(params)}`,
    ),
  politicalSummary: () =>
    request<Record<string, unknown>>("/api/political/summary"),
  politicians: () =>
    request<{ politicians: Record<string, unknown>[] }>("/api/political/politicians"),
  consensus: () =>
    request<{ tickers: Record<string, unknown>[] }>("/api/political/consensus"),

  // --- watchlist ---------------------------------------------------------------
  watchlist: () =>
    request<{ count: number; watchlist: WatchlistEntry[]; note: string }>(
      "/api/watchlist",
    ),
  addWatchlist: (ticker: string, note?: string) =>
    request<{ watchlist: string[] }>("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker, note }),
    }),
  removeWatchlist: (ticker: string) =>
    request<{ watchlist: string[] }>(`/api/watchlist/${ticker}`, {
      method: "DELETE",
    }),

  // --- system -------------------------------------------------------------------
  health: () => request<SystemHealth>("/api/system/health"),
  status: () =>
    request<{
      bootstrap?: { ready: boolean; stage: string; error: string | null };
      [key: string]: unknown;
    }>("/api/system/status"),
  freshness: () =>
    request<{
      overall: string;
      sources: unknown[];
      strategy_gates: Record<string, string>;
    }>("/api/system/freshness"),
  killSwitch: (engage: boolean) =>
    request<{ kill_switch_engaged: boolean }>(
      `/api/system/kill-switch${qs({ engage })}`,
      { method: "POST" },
    ),
  setMode: (mode: string) =>
    request<Record<string, unknown>>(`/api/system/mode${qs({ mode })}`, {
      method: "POST",
    }),
  armAutoTrade: (armed: boolean) =>
    request<{ auto_trade_armed: boolean }>(`/api/system/arm${qs({ armed })}`, {
      method: "POST",
    }),
  scan: (execute = false) =>
    request<Record<string, unknown>>(`/api/system/scan${qs({ execute })}`, {
      method: "POST",
    }),

  // --- config --------------------------------------------------------------------
  riskConfig: () => request<Record<string, unknown>>("/api/config/risk"),
  patchRisk: (updates: Record<string, unknown>) =>
    request<{ applied: Record<string, unknown>; risk: Record<string, unknown> }>(
      "/api/config/risk",
      { method: "PATCH", body: JSON.stringify(updates) },
    ),
  patchStrategy: (strategyId: string, updates: Record<string, unknown>) =>
    request<{ strategy: string; config: Record<string, unknown> }>(
      `/api/config/strategies/${strategyId}`,
      { method: "PATCH", body: JSON.stringify(updates) },
    ),

  // --- search ------------------------------------------------------------------------
  search: (q: string) =>
    request<{ query: string; results: SearchResult[] }>(`/api/search${qs({ q })}`),
  ask: (q: string) => request<QuestionAnswer>(`/api/search/ask${qs({ q })}`),

  // --- analytics -----------------------------------------------------------------------
  performance: () => request<Record<string, unknown>>("/api/analytics/performance"),
  rejectionAnalytics: () => request<Record<string, unknown>>("/api/analytics/rejected"),
};
