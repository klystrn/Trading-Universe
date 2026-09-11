"use client";

/** Portfolio (spec 41). Separate from the trade log. */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useTradingStore } from "@/stores/useTradingStore";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { changeColor, num, signedPct, titleize, usd } from "@/lib/format";
import { EmptyState, Meter, PanelHeader, Stat } from "../Glass";

export function PortfolioPanel() {
  const portfolio = useTradingStore((s) => s.portfolio);
  const refresh = useTradingStore((s) => s.refreshPortfolio);
  const focusOn = useUniverseStore((s) => s.focusOn);
  const [strategyTable, setStrategyTable] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void refresh();
    api
      .performance()
      .then((data) => setStrategyTable((data.by_strategy as Record<string, unknown>[]) ?? []))
      .catch(() => {});
  }, [refresh]);

  if (!portfolio) {
    return (
      <div className="flex h-full flex-col">
        <PanelHeader title="Portfolio" />
        <EmptyState message="Loading portfolio…" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Portfolio"
        subtitle={`${portfolio.broker} · ${portfolio.paper ? "paper" : "LIVE"}`}
      />

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
        <section className="grid grid-cols-2 gap-4">
          <Stat label="Portfolio value" value={usd(portfolio.portfolio_value)} />
          <Stat label="Cash" value={usd(portfolio.cash)} />
          <Stat label="Exposure" value={usd(portfolio.total_exposure)} />
          <Stat label="Buying power" value={usd(portfolio.buying_power)} />
          <Stat
            label="Unrealized P&L"
            value={usd(portfolio.unrealized_pnl)}
            tone={portfolio.unrealized_pnl >= 0 ? "up" : "down"}
          />
          <Stat
            label="Realized today"
            value={usd(portfolio.realized_pnl_today)}
            tone={portfolio.realized_pnl_today >= 0 ? "up" : "down"}
          />
        </section>

        {/* Capacity: the "how many more trades can I open" question (spec 79). */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Capacity
          </p>
          <div className="mt-2 space-y-3">
            <div>
              <div className="flex justify-between text-xs">
                <span className="text-ink-dim">Open positions</span>
                <span className="font-mono text-ink">
                  {portfolio.open_position_count} / {portfolio.max_open_positions}
                </span>
              </div>
              <Meter
                className="mt-1.5"
                value={portfolio.open_position_count}
                max={Math.max(1, portfolio.max_open_positions)}
                tone={portfolio.remaining_position_slots === 0 ? "warn" : "accent"}
              />
            </div>
            <div>
              <div className="flex justify-between text-xs">
                <span className="text-ink-dim">New trades today</span>
                <span className="font-mono text-ink">
                  {portfolio.max_new_trades_per_day - portfolio.remaining_daily_entries} /{" "}
                  {portfolio.max_new_trades_per_day}
                </span>
              </div>
              <Meter
                className="mt-1.5"
                value={portfolio.max_new_trades_per_day - portfolio.remaining_daily_entries}
                max={Math.max(1, portfolio.max_new_trades_per_day)}
                tone={portfolio.remaining_daily_entries === 0 ? "warn" : "accent"}
              />
            </div>
          </div>
        </section>

        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Open positions
          </p>
          {portfolio.positions.length === 0 ? (
            <p className="mt-3 text-xs text-ink-faint">No open positions.</p>
          ) : (
            <div className="mt-2 space-y-1.5">
              {portfolio.positions.map((position) => (
                <button
                  key={position.ticker}
                  onClick={() => focusOn(position.ticker)}
                  className="w-full rounded-lg border border-glass-edge px-3 py-2.5 text-left transition-colors hover:border-accent/35 hover:bg-glass"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-sm text-ink">{position.ticker}</span>
                    <span className={`font-mono text-sm ${changeColor(position.unrealized_pnl_pct)}`}>
                      {signedPct(position.unrealized_pnl_pct)}
                    </span>
                  </div>
                  <div className="mt-1 grid grid-cols-3 gap-2 text-[10px] text-ink-faint">
                    <span>{num(position.quantity, 4)} sh</span>
                    <span>@ {num(position.avg_entry)}</span>
                    <span className="text-right">{usd(position.market_value)}</span>
                  </div>
                  <div className="mt-1 grid grid-cols-3 gap-2 text-[10px]">
                    <span className="text-ink-faint">
                      stop {position.stop ? num(position.stop) : "--"}
                    </span>
                    <span className="text-ink-faint">
                      target {position.target ? num(position.target) : "--"}
                    </span>
                    <span className="text-right font-mono text-ink-dim">
                      {position.r_multiple != null ? `${num(position.r_multiple)}R` : "--"}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        {Object.keys(portfolio.sector_exposure).length > 0 && (
          <section>
            <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
              Sector exposure
            </p>
            <div className="mt-2 space-y-1.5">
              {Object.entries(portfolio.sector_exposure).map(([sector, value]) => (
                <div key={sector} className="flex justify-between text-xs">
                  <span className="text-ink-dim">{titleize(sector)}</span>
                  <span className="font-mono text-ink">{usd(value)}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Strategy performance
          </p>
          {strategyTable.length === 0 ? (
            <p className="mt-2 text-[11px] leading-relaxed text-ink-faint">
              No closed trades yet. This table fills in as paper history
              accumulates — it is the dataset that has to exist before any
              statistical strategy selection is reasonable.
            </p>
          ) : (
            <table className="mt-2 w-full text-[11px]">
              <thead>
                <tr className="border-b border-glass-edge text-ink-faint">
                  <th className="py-1 text-left font-mono text-[9px] uppercase">Strategy</th>
                  <th className="py-1 text-right font-mono text-[9px] uppercase">N</th>
                  <th className="py-1 text-right font-mono text-[9px] uppercase">Win</th>
                  <th className="py-1 text-right font-mono text-[9px] uppercase">Avg R</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-glass-edge/50">
                {strategyTable.map((row) => (
                  <tr key={String(row.strategy)}>
                    <td className="py-1.5 pr-2 text-ink-dim">{String(row.label)}</td>
                    <td className="py-1.5 text-right font-mono text-ink">
                      {String(row.trades)}
                    </td>
                    <td className="py-1.5 text-right font-mono text-ink">
                      {row.win_rate != null
                        ? `${Math.round(Number(row.win_rate) * 100)}%`
                        : "--"}
                    </td>
                    <td className="py-1.5 text-right font-mono text-ink">
                      {row.avg_r != null ? num(Number(row.avg_r)) : "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
