/** Shapes mirroring the backend's API responses. */

export type FreshnessStatus =
  | "LIVE" | "HEALTHY" | "DEGRADED" | "STALE" | "UNAVAILABLE";

export type OperatingMode = "ADVISORY" | "PAPER_AUTO" | "LIVE_AUTO";

export type SessionName = "PRE_MARKET" | "REGULAR" | "AFTER_HOURS" | "CLOSED";

export type MarketRegime =
  | "STRONG_BULL" | "BULL" | "NEUTRAL" | "HIGH_VOLATILITY"
  | "CORRECTION" | "RECOVERY" | "RISK_OFF";

/** The compact per-entity visual state (spec 77). Deliberately lean: this is
 *  pushed on every tick, so it carries only what the scene branches on. */
export interface UniverseEntity {
  id: string;
  type: "stock";
  name: string;
  sector: string;
  subsector: string;
  position: [number, number, number];
  size: number;
  orbit_speed: number;
  intensity: number;
  price_change: number;
  volume_ratio: number;
  price: number | null;
  live: boolean;
  watchlist: boolean;
  signal?: {
    active: boolean;
    score: number;
    strategy: string;
    executable: boolean;
    pulse: "subtle" | "moderate" | "strong" | null;
  };
  portfolio?: { held: boolean; pnl_pct: number; warmth: number };
  political?: {
    active: boolean;
    count: number;
    consensus: number;
    purchases: number;
    sales: number;
  };
}

export interface UniverseSector {
  id: string;
  type: "sector";
  label: string;
  short: string;
  hue: number;
  position: [number, number, number];
  member_count: number;
  performance: number;
  relative_strength: number;
  rs_label: string;
  breadth: number;
  regime: MarketRegime;
  news_sentiment: number;
  signal_count: number;
  recommended_strategy: string | null;
}

export interface UniverseSubsector {
  id: string;
  type: "subsector";
  label: string;
  sector: string;
  position: [number, number, number];
  member_count: number;
}

/** Sector-rotation arcs. `inferred` is always true: this is derived from
 *  relative strength, never observed capital flow (spec 51). */
export interface FlowArc {
  from: string;
  to: string;
  strength: number;
  inferred: true;
  basis: string;
}

export interface UniversePayload {
  entities: UniverseEntity[];
  sectors: UniverseSector[];
  subsectors: UniverseSubsector[];
  flows: FlowArc[];
}

export interface SignalScore {
  technical: number;
  sentiment: number;
  fundamental: number;
  political: number | null;
  total: number;
}

export interface TradeParams {
  entry: number;
  stop: number;
  target: number;
  max_position_value: number;
  risk_per_share: number;
  reward_per_share: number;
  reward_risk: number;
}

export interface ExecutionDecision {
  allowed: boolean;
  reasons: string[];
  notes: string[];
  quantity: number | null;
  position_value: number | null;
}

export interface Signal {
  signal_id: string;
  ticker: string;
  strategy_id: string;
  strategy_label?: string;
  strategy_kind: "standard" | "political";
  sector: string;
  subsector: string;
  direction: string;
  generated_at: string;
  score: SignalScore;
  trade: TradeParams;
  market: {
    regime: MarketRegime;
    sector_regime: MarketRegime;
    strategy_match: number;
  };
  freshness: {
    market_data: FreshnessStatus;
    news: FreshnessStatus;
    fundamentals: FreshnessStatus;
    political: FreshnessStatus | null;
    details: Record<string, number>;
  };
  execution: ExecutionDecision;
  evidence: Record<string, unknown>;
  invalidation: string;
  confidence: number;
  tier?: string;
  regime_match?: number;
}

export interface SectorRecommendation {
  sector_id: string;
  regime: MarketRegime;
  session_performance: number;
  relative_strength: number;
  rs_label: string;
  breadth: number;
  news_sentiment: number;
  signal_count: number;
  political_activity: number;
  recommended_strategy: string | null;
  recommended_strategy_label?: string | null;
  confidence: number;
  rationale: string[];
}

export interface Recommendation {
  trading_day: string;
  generated_at: string;
  primary_strategy: string;
  primary_strategy_label: string;
  confidence: number;
  market_regime: MarketRegime;
  rationale: string[];
  sector_recommendations: SectorRecommendation[];
  alternatives: { strategy: string; label: string; fit: number }[];
  active_strategy: string | null;
  overridden: boolean;
  regime_inputs: Record<string, number | boolean | null>;
}

export interface StrategyInfo {
  id: string;
  label: string;
  kind: "standard" | "political";
  enabled: boolean;
  minimum_score: number;
  config: Record<string, unknown>;
  signals_today: number;
  gate: string;
  is_active: boolean;
}

export interface DataSourceHealth {
  name: string;
  status: FreshnessStatus;
  connected: boolean;
  latency_ms: number | null;
  last_success_at: string | null;
  quota_used: number | null;
  quota_limit: number | null;
  queue_depth: number | null;
  detail: string | null;
}

export interface FreshnessState {
  source: string;
  status: FreshnessStatus;
  age_seconds: number | null;
  warn_age_seconds: number | null;
  max_age_seconds: number | null;
  blocking: boolean;
  detail: string | null;
}

export interface SystemHealth {
  as_of: string;
  overall: FreshnessStatus;
  sources: DataSourceHealth[];
  freshness: FreshnessState[];
  kill_switch_engaged: boolean;
  auto_trade_enabled: boolean;
  operating_mode: OperatingMode;
  trading_env: "PAPER" | "REAL";
  allow_real_orders: boolean;
  read_only: boolean;
  database_healthy: boolean;
  scanner_running: boolean;
  open_orders: number;
  rejected_orders_today: number;
  last_scan_at: string | null;
  last_sync_at: string | null;
  session: SessionName;
  strategy_gates: Record<string, string>;
}

export interface Position {
  ticker: string;
  name?: string;
  sector?: string;
  quantity: number;
  avg_entry: number;
  current_price: number;
  stop: number | null;
  target: number | null;
  strategy_id: string | null;
  strategy_label?: string | null;
  opened_at: string | null;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  r_multiple: number | null;
}

export interface Portfolio {
  as_of: string;
  cash: number;
  buying_power: number;
  positions: Position[];
  realized_pnl_today: number;
  realized_pnl_total: number;
  paper: boolean;
  total_exposure: number;
  portfolio_value: number;
  unrealized_pnl: number;
  open_position_count: number;
  remaining_position_slots: number;
  remaining_daily_entries: number;
  max_open_positions: number;
  max_new_trades_per_day: number;
  sector_exposure: Record<string, number>;
  strategy_exposure: Record<string, number>;
  broker: string;
}

export interface Trade {
  trade_id: string;
  ticker: string;
  strategy_id: string;
  strategy_label?: string;
  sector: string;
  entry: number;
  stop: number;
  target: number;
  quantity: number;
  exit_price: number | null;
  opened_at: string;
  closed_at: string | null;
  exit_reason: string | null;
  operating_mode: OperatingMode;
  execution_source: string;
  paper: boolean;
  result: "OPEN" | "WIN" | "LOSS" | "BREAKEVEN";
  realized_pnl: number | null;
  r_multiple: number | null;
  market_regime: string | null;
}

export interface PoliticalTransaction {
  transaction_id: string;
  politician: string;
  chamber: "HOUSE" | "SENATE";
  party: string | null;
  state: string | null;
  owner: string;
  ticker: string;
  sector?: string;
  in_universe?: boolean;
  asset_description: string | null;
  transaction_type: string;
  amount_low: number;
  amount_high: number;
  transaction_date: string;
  disclosure_date: string;
  detected_at: string;
}

export interface WatchlistEntry {
  ticker: string;
  name?: string;
  sector?: string;
  note: string | null;
  pinned: boolean;
  alert_above: number | null;
  alert_below: number | null;
  added_at: string;
  price?: number | null;
  tier?: string;
  political_activity?: number;
  signal?: { score: number; strategy: string; executable: boolean } | null;
}

export interface Briefing {
  as_of: string;
  market_regime: string;
  regime_confidence?: number;
  primary_strategy: string | null;
  primary_strategy_label: string | null;
  confidence: number;
  rationale: string[];
  strongest_sectors: {
    sector: string;
    relative_strength: number;
    label: string;
    recommended_strategy: string | null;
  }[];
  weakest_sectors: { sector: string; relative_strength: number; label: string }[];
  high_confidence_signals: {
    ticker: string;
    score: number;
    strategy: string;
    strategy_label: string;
    executable: boolean;
  }[];
  signal_counts?: { total: number; executable: number; rejected: number };
  political_activity: Record<string, unknown>;
  portfolio: Record<string, number>;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandleResponse {
  ticker: string;
  interval: string;
  candles: Candle[];
  overlays: Record<string, number | null>;
  markers: {
    time: number;
    entry: number;
    stop: number;
    target: number;
    strategy: string;
    score: number;
    executable: boolean;
  }[];
}

export interface SearchResult {
  type: "stock" | "sector" | "subsector";
  id: string;
  label: string;
  sublabel: string;
  sector?: string;
  score: number;
}

export interface QuestionAnswer {
  intent: string;
  answer: string;
  ticker?: string;
  sector?: string;
  strategy?: string;
  tickers?: string[];
  supported?: string[];
  signal?: Signal;
  failed_checks?: string[];
}

/** Visualization filters are emphasis layers over one scene, never separate
 *  scenes (spec 56). */
export type UniverseFilter =
  | "MARKET" | "SECTORS" | "SIGNALS" | "POLITICAL" | "PORTFOLIO" | "WATCHLIST";

export type PanelId =
  | "parameters" | "trades" | "watchlist" | "charts"
  | "politicians" | "signals" | "portfolio" | "system";
