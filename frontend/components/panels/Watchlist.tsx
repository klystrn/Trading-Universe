"use client";

/** Watchlist (spec 37, 69).
 *
 *  Watched names get scan priority and prominent placement. They never get a
 *  score bonus - the note from the backend says so and is shown verbatim.
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useTradingStore } from "@/stores/useTradingStore";
import { titleize, usd } from "@/lib/format";
import { EmptyState, PanelHeader, Pill } from "../Glass";

export function WatchlistPanel() {
  const watchlist = useTradingStore((s) => s.watchlist);
  const refresh = useTradingStore((s) => s.refreshWatchlist);
  const openChartFor = useTradingStore((s) => s.openChartFor);

  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const add = async () => {
    if (!ticker.trim()) return;
    setError(null);
    try {
      await api.addWatchlist(ticker.trim().toUpperCase(), note.trim() || undefined);
      setTicker("");
      setNote("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not add");
    }
  };

  const remove = async (symbol: string) => {
    await api.removeWatchlist(symbol);
    await refresh();
  };

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Watchlist" subtitle={`${watchlist.length} names · priority scan`} />

      <div className="border-b border-glass-edge px-5 py-3">
        <div className="flex gap-1.5">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && void add()}
            placeholder="Ticker"
            className="w-24 rounded-lg border border-glass-edge bg-void-200/70 px-2.5 py-1.5 font-mono text-sm text-ink outline-none focus:border-accent/50"
          />
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void add()}
            placeholder="Note (optional)"
            className="min-w-0 flex-1 rounded-lg border border-glass-edge bg-void-200/70 px-2.5 py-1.5 text-sm text-ink outline-none focus:border-accent/50"
          />
          <button
            onClick={() => void add()}
            className="rounded-lg border border-accent/40 bg-accent/10 px-3 font-mono text-[10px] uppercase tracking-[0.14em] text-accent hover:bg-accent/20"
          >
            Pin
          </button>
        </div>
        {error && <p className="mt-2 text-[11px] text-down">{error}</p>}
        <p className="mt-2 text-[10px] leading-relaxed text-ink-faint">
          Watchlist entries receive scan priority and real-time quotes. They
          never receive a score bonus.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {watchlist.length === 0 ? (
          <EmptyState message="Nothing pinned" hint="Add a ticker above to prioritise it." />
        ) : (
          <div className="divide-y divide-glass-edge/60">
            {watchlist.map((entry) => (
              <div key={entry.ticker} className="px-5 py-3">
                <div className="flex items-baseline justify-between gap-2">
                  <button
                    onClick={() => openChartFor(entry.ticker)}
                    className="font-mono text-sm text-ink hover:text-accent"
                  >
                    {entry.ticker}
                  </button>
                  <span className="font-mono text-sm text-ink-dim">{usd(entry.price)}</span>
                </div>
                <p className="mt-0.5 truncate text-[11px] text-ink-faint">
                  {entry.name} · {titleize(entry.sector ?? "")}
                </p>
                {entry.note && <p className="mt-1 text-xs text-ink-dim">{entry.note}</p>}
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  {entry.tier && <Pill>{entry.tier}</Pill>}
                  {entry.signal && (
                    <Pill tone={entry.signal.executable ? "up" : "warn"}>
                      {entry.signal.score} · {entry.signal.strategy.replace(/_/g, " ")}
                    </Pill>
                  )}
                  {(entry.political_activity ?? 0) > 0 && (
                    <Pill tone="warn">{entry.political_activity} political</Pill>
                  )}
                  <span className="flex-1" />
                  <button
                    onClick={() => openChartFor(entry.ticker)}
                    className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-faint hover:text-accent"
                  >
                    Chart
                  </button>
                  <button
                    onClick={() => void remove(entry.ticker)}
                    className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-faint hover:text-down"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
