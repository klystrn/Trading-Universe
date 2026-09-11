"use client";

/** Trade Log (spec 36), with the filters the spec calls for. */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn, num, relativeTime, titleize, usd } from "@/lib/format";
import { EmptyState, PanelHeader, Pill } from "../Glass";
import type { Trade } from "@/lib/types";

export function TradeLogPanel() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [filters, setFilters] = useState<{
    strategies: { id: string; label: string }[];
    sectors: { id: string; label: string }[];
    results: string[];
    execution_sources: string[];
  } | null>(null);
  const [query, setQuery] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [thesis, setThesis] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.trades({ ...query, limit: 200 });
      setTrades(data.trades);
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api.tradeFilters().then(setFilters).catch(() => {});
  }, []);

  const openThesis = async (trade: Trade) => {
    if (expanded === trade.trade_id) {
      setExpanded(null);
      setThesis(null);
      return;
    }
    setExpanded(trade.trade_id);
    try {
      setThesis(await api.tradeThesis(trade.trade_id));
    } catch {
      setThesis(null);
    }
  };

  const setFilter = (key: string, value: string) =>
    setQuery((prev) => {
      const next = { ...prev };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Trade Log" subtitle={`${trades.length} trades`} />

      <div className="flex flex-wrap gap-1.5 border-b border-glass-edge px-5 py-3">
        {filters && (
          <>
            <FilterSelect
              value={query.strategy ?? ""}
              onChange={(v) => setFilter("strategy", v)}
              placeholder="All strategies"
              options={filters.strategies.map((s) => ({ value: s.id, label: s.label }))}
            />
            <FilterSelect
              value={query.sector ?? ""}
              onChange={(v) => setFilter("sector", v)}
              placeholder="All sectors"
              options={filters.sectors.map((s) => ({ value: s.id, label: s.label }))}
            />
            <FilterSelect
              value={query.result ?? ""}
              onChange={(v) => setFilter("result", v)}
              placeholder="Any result"
              options={filters.results.map((r) => ({ value: r, label: titleize(r) }))}
            />
            <FilterSelect
              value={query.execution_source ?? ""}
              onChange={(v) => setFilter("execution_source", v)}
              placeholder="Any source"
              options={filters.execution_sources.map((s) => ({
                value: s,
                label: titleize(s),
              }))}
            />
            <FilterSelect
              value={query.paper ?? ""}
              onChange={(v) => setFilter("paper", v)}
              placeholder="Paper & live"
              options={[
                { value: "true", label: "Paper only" },
                { value: "false", label: "Live only" },
              ]}
            />
          </>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <EmptyState message="Loading trades…" />
        ) : trades.length === 0 ? (
          <EmptyState
            message="No trades yet"
            hint="Advisory mode records recommendations without executing them. Switch to Paper Auto to begin filling."
          />
        ) : (
          <div className="divide-y divide-glass-edge/60">
            {trades.map((trade) => (
              <div key={trade.trade_id}>
                <button
                  onClick={() => void openThesis(trade)}
                  className="w-full px-5 py-3 text-left transition-colors hover:bg-glass"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-sm text-ink">{trade.ticker}</span>
                    <span
                      className={cn(
                        "font-mono text-sm",
                        trade.result === "WIN" ? "text-up"
                          : trade.result === "LOSS" ? "text-down"
                          : "text-ink-dim",
                      )}
                    >
                      {trade.realized_pnl != null ? usd(trade.realized_pnl) : "open"}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2">
                    <span className="truncate text-[11px] text-ink-faint">
                      {trade.strategy_label ?? trade.strategy_id}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-ink-dim">
                      {trade.r_multiple != null ? `${num(trade.r_multiple)}R` : "--"}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Pill>{trade.paper ? "Paper" : "Live"}</Pill>
                    <Pill>{titleize(trade.execution_source)}</Pill>
                    {trade.exit_reason && <Pill>{titleize(trade.exit_reason)}</Pill>}
                    <span className="text-[10px] text-ink-faint">
                      {relativeTime(trade.opened_at)}
                    </span>
                  </div>
                  <div className="mt-1 grid grid-cols-4 gap-2 font-mono text-[10px] text-ink-faint">
                    <span>in {num(trade.entry)}</span>
                    <span>stop {num(trade.stop)}</span>
                    <span>tgt {num(trade.target)}</span>
                    <span>out {trade.exit_price ? num(trade.exit_price) : "--"}</span>
                  </div>
                </button>

                {expanded === trade.trade_id && (
                  <div className="border-t border-glass-edge bg-void-200/40 px-5 py-3">
                    <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint">
                      Thesis
                    </p>
                    {thesis ? (
                      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[10px] leading-relaxed text-ink-dim">
                        {JSON.stringify(thesis, null, 2)}
                      </pre>
                    ) : (
                      <p className="mt-2 text-[11px] text-ink-faint">
                        No thesis recorded for this trade.
                      </p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FilterSelect({
  value,
  onChange,
  placeholder,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-glass-edge bg-void-200/70 px-2 py-1 font-mono text-[10px] text-ink-dim outline-none"
    >
      <option value="">{placeholder}</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
