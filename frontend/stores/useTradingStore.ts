/** Trading state: signals, strategy, portfolio, health, panels.
 *
 *  Deliberately separate from the render store (spec 78) so a quote tick does
 *  not re-render the trade log, and a panel toggle does not touch the scene.
 */

import { create } from "zustand";
import { api } from "@/lib/api";
import type {
  Briefing, PanelId, Portfolio, Recommendation, Signal, StrategyInfo,
  SystemHealth, WatchlistEntry,
} from "@/lib/types";

interface TradingState {
  signals: Signal[];
  signalsGeneratedAt: string | null;
  activeStrategy: string | null;
  strategies: StrategyInfo[];
  recommendation: Recommendation | null;
  portfolio: Portfolio | null;
  health: SystemHealth | null;
  briefing: Briefing | null;
  watchlist: WatchlistEntry[];

  openPanel: PanelId | null;
  chartTicker: string | null;
  loading: boolean;
  error: string | null;

  setSignals: (signals: Signal[], generatedAt: string | null) => void;
  setHealth: (health: SystemHealth) => void;
  setBriefing: (briefing: Briefing) => void;
  /** Only one left-side card is expanded at a time (spec 34). */
  togglePanel: (panel: PanelId) => void;
  closePanel: () => void;
  openChartFor: (ticker: string) => void;

  refreshAll: () => Promise<void>;
  refreshStrategies: () => Promise<void>;
  refreshPortfolio: () => Promise<void>;
  refreshWatchlist: () => Promise<void>;
  acceptRecommendation: () => Promise<void>;
  overrideStrategy: (strategyId: string) => Promise<void>;
  setKillSwitch: (engage: boolean) => Promise<void>;
}

export const useTradingStore = create<TradingState>((set, get) => ({
  signals: [],
  signalsGeneratedAt: null,
  activeStrategy: null,
  strategies: [],
  recommendation: null,
  portfolio: null,
  health: null,
  briefing: null,
  watchlist: [],

  openPanel: null,
  chartTicker: null,
  loading: false,
  error: null,

  setSignals: (signals, signalsGeneratedAt) => set({ signals, signalsGeneratedAt }),
  setHealth: (health) => set({ health }),
  setBriefing: (briefing) => set({ briefing }),

  togglePanel: (panel) =>
    set((s) => ({ openPanel: s.openPanel === panel ? null : panel })),
  closePanel: () => set({ openPanel: null }),
  openChartFor: (ticker) => set({ chartTicker: ticker, openPanel: "charts" }),

  refreshAll: async () => {
    set({ loading: true, error: null });
    try {
      const [signals, strategies, portfolio, health, briefing, watchlist] =
        await Promise.all([
          api.signals({ limit: 200 }),
          api.strategies(),
          api.portfolio(),
          api.health(),
          api.briefing(),
          api.watchlist(),
        ]);
      set({
        signals: signals.signals,
        signalsGeneratedAt: signals.generated_at,
        activeStrategy: signals.active_strategy,
        strategies: strategies.strategies,
        portfolio,
        health,
        briefing,
        watchlist: watchlist.watchlist,
      });
      // The recommendation 404s until the first scan completes; that is an
      // expected state, not an error worth surfacing.
      try {
        set({ recommendation: await api.recommendation() });
      } catch {
        set({ recommendation: null });
      }
    } catch (error) {
      set({ error: error instanceof Error ? error.message : "request failed" });
    } finally {
      set({ loading: false });
    }
  },

  refreshStrategies: async () => {
    const data = await api.strategies();
    set({ strategies: data.strategies, activeStrategy: data.active_strategy });
  },

  refreshPortfolio: async () => set({ portfolio: await api.portfolio() }),

  refreshWatchlist: async () => {
    const data = await api.watchlist();
    set({ watchlist: data.watchlist });
  },

  acceptRecommendation: async () => {
    const result = await api.acceptRecommendation();
    set({ activeStrategy: result.active_strategy });
    await get().refreshStrategies();
  },

  overrideStrategy: async (strategyId) => {
    const result = await api.overrideStrategy(strategyId);
    set({ activeStrategy: result.active_strategy });
    await get().refreshStrategies();
  },

  setKillSwitch: async (engage) => {
    await api.killSwitch(engage);
    set({ health: await api.health() });
  },
}));
