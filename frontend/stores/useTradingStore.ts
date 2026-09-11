/** Trading state: signals, strategy, portfolio, health, panels.
 *
 *  Deliberately separate from the render store (spec 78) so a quote tick does
 *  not re-render the trade log, and a panel toggle does not touch the scene.
 */

import { create } from "zustand";
import { api, isWakingError } from "@/lib/api";
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
  /** The backend is starting (container boot or first scan); not an error. */
  waking: boolean;
  wakeStage: string | null;
  wakeSince: number | null;

  setSignals: (signals: Signal[], generatedAt: string | null) => void;
  setHealth: (health: SystemHealth) => void;
  setBriefing: (briefing: Briefing) => void;
  /** Only one left-side card is expanded at a time (spec 34). */
  togglePanel: (panel: PanelId) => void;
  closePanel: () => void;
  openChartFor: (ticker: string) => void;

  /** First load: ask /api/system/status whether the scan has landed before
   *  firing six requests that would all 503 on a cold instance. */
  boot: () => Promise<void>;
  refreshAll: () => Promise<void>;
  /** Poll /api/system/status until the first scan lands, then refresh. */
  waitForBackend: () => Promise<void>;
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
  waking: false,
  wakeStage: null,
  wakeSince: null,

  setSignals: (signals, signalsGeneratedAt) => set({ signals, signalsGeneratedAt }),
  setHealth: (health) => set({ health }),
  setBriefing: (briefing) => set({ briefing }),

  togglePanel: (panel) =>
    set((s) => ({ openPanel: s.openPanel === panel ? null : panel })),
  closePanel: () => set({ openPanel: null }),
  openChartFor: (ticker) => set({ chartTicker: ticker, openPanel: "charts" }),

  boot: async () => {
    try {
      const status = await api.status();
      if (status.bootstrap && !status.bootstrap.ready) {
        set({ waking: true, wakeSince: Date.now(), wakeStage: status.bootstrap.stage });
        await get().waitForBackend();
        return;
      }
    } catch (error) {
      if (isWakingError(error)) {
        set({ waking: true, wakeSince: Date.now(), wakeStage: "starting the server" });
        await get().waitForBackend();
        return;
      }
    }
    await get().refreshAll();
  },

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
      set({ waking: false, wakeStage: null, wakeSince: null });
    } catch (error) {
      if (isWakingError(error)) {
        // A sleeping free-tier instance or a cold first scan. Say so and keep
        // asking rather than flashing an error at the visitor.
        if (!get().waking) {
          set({ waking: true, wakeSince: Date.now(), wakeStage: null });
          void get().waitForBackend();
        }
      } else {
        set({ error: error instanceof Error ? error.message : "request failed" });
      }
    } finally {
      set({ loading: false });
    }
  },

  waitForBackend: async () => {
    // Bounded: after ten minutes of silence this is an outage, not a wake.
    const deadline = Date.now() + 10 * 60_000;
    while (get().waking && Date.now() < deadline) {
      try {
        const status = await api.status();
        const boot = status.bootstrap;
        if (!boot || boot.ready) {
          set({ waking: false, wakeStage: null, wakeSince: null });
          await get().refreshAll();
          return;
        }
        set({ wakeStage: boot.error ? `failed: ${boot.error}` : boot.stage });
        if (boot.error) break;
      } catch {
        set({ wakeStage: "starting the server" });
      }
      await new Promise((resolve) => setTimeout(resolve, 3_000));
    }
    if (get().waking) {
      set({ waking: false, error: get().wakeStage ?? "backend did not come up" });
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
