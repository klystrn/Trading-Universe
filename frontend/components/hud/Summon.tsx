"use client";

/** Hosts whichever panel has been summoned. One at a time; Escape dismisses. */

import { useEffect } from "react";
import { GlassPanel } from "../Glass";
import { ChartsPanel } from "../panels/Charts";
import { ParametersPanel } from "../panels/Parameters";
import { PoliticiansPanel } from "../panels/Politicians";
import { PortfolioPanel } from "../panels/Portfolio";
import { SignalsPanel } from "../panels/Signals";
import { SystemPanel } from "../panels/System";
import { TradeLogPanel } from "../panels/TradeLog";
import { WatchlistPanel } from "../panels/Watchlist";
import { useTradingStore } from "@/stores/useTradingStore";

const PANELS = {
  parameters: ParametersPanel, trades: TradeLogPanel, watchlist: WatchlistPanel, charts: ChartsPanel,
  politicians: PoliticiansPanel, signals: SignalsPanel, portfolio: PortfolioPanel, system: SystemPanel,
} as const;

export function Summon() {
  const openPanel = useTradingStore((s) => s.openPanel);
  const closePanel = useTradingStore((s) => s.closePanel);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closePanel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closePanel]);

  if (!openPanel) return null;
  const Panel = PANELS[openPanel];
  return (
    <div className="pointer-events-auto absolute bottom-4 right-4 top-4 z-30 w-[min(460px,calc(100vw-2rem))] animate-fade-up">
      <GlassPanel className="h-full overflow-hidden">
        <button onClick={closePanel} aria-label="Dismiss panel"
                className="absolute right-4 top-4 z-10 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-faint hover:text-ink">
          esc
        </button>
        <Panel />
      </GlassPanel>
    </div>
  );
}
