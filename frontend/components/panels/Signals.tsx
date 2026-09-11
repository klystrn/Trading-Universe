"use client";

/** Signals / Scanner (spec 40). The essential tab.
 *
 *  Clicking a candidate focuses the universe on it and opens its detail, which
 *  is what makes the 3D scene the navigation layer rather than a picture.
 */

import { useMemo, useState } from "react";
import { useTradingStore } from "@/stores/useTradingStore";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { api } from "@/lib/api";
import { cn, humanizeReason, num, relativeTime } from "@/lib/format";
import { EmptyState, PanelHeader, Pill } from "../Glass";
import type { Signal } from "@/lib/types";

export function SignalsPanel() {
  const signals = useTradingStore((s) => s.signals);
  const generatedAt = useTradingStore((s) => s.signalsGeneratedAt);
  const strategies = useTradingStore((s) => s.strategies);
  const openChartFor = useTradingStore((s) => s.openChartFor);
  const focusOn = useUniverseStore((s) => s.focusOn);

  const [strategyFilter, setStrategyFilter] = useState("");
  const [executableOnly, setExecutableOnly] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [nearMisses, setNearMisses] = useState<
    { ticker: string; strategy: string; failed: string[] }[] | null
  >(null);

  const filtered = useMemo(
    () =>
      signals.filter(
        (s) =>
          (!strategyFilter || s.strategy_id === strategyFilter) &&
          (!executableOnly || s.execution.allowed),
      ),
    [signals, strategyFilter, executableOnly],
  );

  const loadNearMisses = async () => {
    if (nearMisses) {
      setNearMisses(null);
      return;
    }
    const data = await api.nearMisses(40);
    setNearMisses(data.near_misses);
  };

  const select = (signal: Signal) => {
    // Clicking a candidate focuses the universe on that entity (spec 40).
    focusOn(signal.ticker);
    setExpanded(expanded === signal.signal_id ? null : signal.signal_id);
  };

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Signals / Scanner"
        subtitle={
          generatedAt
            ? `${filtered.length} of ${signals.length} · scanned ${relativeTime(generatedAt)}`
            : "Waiting for the first scan"
        }
      />

      <div className="flex flex-wrap items-center gap-1.5 border-b border-glass-edge px-5 py-3">
        <select
          value={strategyFilter}
          onChange={(e) => setStrategyFilter(e.target.value)}
          className="rounded-lg border border-glass-edge bg-void-200/70 px-2 py-1 font-mono text-[10px] text-ink-dim outline-none"
        >
          <option value="">All strategies</option>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <button
          onClick={() => setExecutableOnly((v) => !v)}
          className={cn(
            "rounded-lg border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors",
            executableOnly
              ? "border-accent/40 bg-accent/10 text-accent"
              : "border-glass-edge text-ink-faint",
          )}
        >
          Executable only
        </button>
        <button
          onClick={() => void loadNearMisses()}
          className={cn(
            "rounded-lg border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors",
            nearMisses ? "border-warn/40 bg-warn/10 text-warn" : "border-glass-edge text-ink-faint",
          )}
        >
          Near misses
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {nearMisses ? (
          <div className="divide-y divide-glass-edge">
            <p className="px-5 py-3 text-[10px] leading-relaxed text-ink-faint">
              Setups that failed only one or two checks. Shown so a threshold can
              be questioned rather than silently trusted.
            </p>
            {nearMisses.map((miss, i) => (
              <div key={`${miss.ticker}-${miss.strategy}-${i}`} className="px-5 py-3">
                <div className="flex items-baseline justify-between">
                  <span className="font-mono text-sm text-ink">{miss.ticker}</span>
                  <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-faint">
                    {miss.strategy.replace(/_/g, " ")}
                  </span>
                </div>
                <ul className="mt-1.5 space-y-0.5">
                  {miss.failed.map((check) => (
                    <li key={check} className="flex gap-2 text-[11px] text-ink-dim">
                      <span className="text-down">✕</span>
                      {check}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            message="No qualifying setups"
            hint="NO TRADE is a valid recommendation for a day or a sector."
          />
        ) : (
          <table className="w-full">
            <thead className="sticky top-0 bg-void-100/92 backdrop-blur-glass">
              <tr className="border-b border-glass-edge">
                {["Ticker", "Score", "Tech", "Sent", "Fund", ""].map((head) => (
                  <th
                    key={head}
                    className="px-3 py-2 text-left font-mono text-[9px] uppercase tracking-[0.14em] text-ink-faint first:pl-5 last:pr-5"
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-glass-edge/60">
              {filtered.map((signal) => {
                const isOpen = expanded === signal.signal_id;
                const maxTech = signal.strategy_kind === "political" ? 30 : 40;
                return (
                  <>
                    <tr
                      key={signal.signal_id}
                      onClick={() => select(signal)}
                      className={cn(
                        "cursor-pointer transition-colors hover:bg-glass",
                        isOpen && "bg-accent/[0.06]",
                      )}
                    >
                      <td className="py-2.5 pl-5 pr-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-sm text-ink">
                            {signal.ticker}
                          </span>
                          {!signal.execution.allowed && (
                            <span className="text-[10px] text-warn" title="Blocked by risk">
                              ⚠
                            </span>
                          )}
                        </div>
                        <span className="truncate text-[10px] text-ink-faint">
                          {signal.strategy_label ?? signal.strategy_id}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-sm text-accent">
                        {signal.confidence}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[11px] text-ink-dim">
                        {num(signal.score.technical, 0)}/{maxTech}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[11px] text-ink-dim">
                        {num(signal.score.sentiment, 0)}/
                        {signal.strategy_kind === "political" ? 20 : 30}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[11px] text-ink-dim">
                        {num(signal.score.fundamental, 0)}/
                        {signal.strategy_kind === "political" ? 25 : 30}
                      </td>
                      <td className="py-2.5 pr-5 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            openChartFor(signal.ticker);
                          }}
                          className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-faint hover:text-accent"
                        >
                          Chart
                        </button>
                      </td>
                    </tr>

                    {isOpen && (
                      <tr key={`${signal.signal_id}-detail`} className="bg-void-200/40">
                        <td colSpan={6} className="px-5 py-3">
                          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[11px]">
                            <Detail label="Entry" value={num(signal.trade.entry)} />
                            <Detail label="Stop" value={num(signal.trade.stop)} />
                            <Detail label="Target" value={num(signal.trade.target)} />
                            <Detail
                              label="Reward:risk"
                              value={`${num(signal.trade.reward_risk)}R`}
                            />
                            <Detail label="Sector" value={signal.sector.replace(/_/g, " ")} />
                            <Detail
                              label="Regime match"
                              value={`${Math.round((signal.market.strategy_match ?? 0) * 100)}%`}
                            />
                            <Detail
                              label="Market data"
                              value={signal.freshness.market_data}
                            />
                            <Detail label="News" value={signal.freshness.news} />
                          </div>

                          <p className="mt-2.5 text-[11px] text-ink-dim">
                            <span className="text-ink-faint">Invalidation: </span>
                            {signal.invalidation}
                          </p>

                          <div className="mt-2.5 flex flex-wrap gap-1.5">
                            {signal.execution.allowed ? (
                              <Pill tone="up">Executable</Pill>
                            ) : (
                              signal.execution.reasons.map((reason) => (
                                <Pill key={reason} tone="warn">
                                  {humanizeReason(reason)}
                                </Pill>
                              ))
                            )}
                          </div>

                          {signal.execution.notes.length > 0 && (
                            <ul className="mt-2 space-y-0.5">
                              {signal.execution.notes.map((note) => (
                                <li key={note} className="text-[10px] text-ink-faint">
                                  {note}
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-ink-faint">{label}</span>
      <span className="font-mono text-ink">{value}</span>
    </div>
  );
}
