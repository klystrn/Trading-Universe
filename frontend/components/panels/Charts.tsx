"use client";

/** Stock Charts (spec 38). Opening a ticker also travels the camera to it. */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CandleChart } from "@/charts/CandleChart";
import { useTradingStore } from "@/stores/useTradingStore";
import { num, signedPct, changeColor } from "@/lib/format";
import { EmptyState, PanelHeader, Pill } from "../Glass";
import type { CandleResponse } from "@/lib/types";

export function ChartsPanel() {
  const chartTicker = useTradingStore((s) => s.chartTicker);
  const openChartFor = useTradingStore((s) => s.openChartFor);
  const signals = useTradingStore((s) => s.signals);
  const [input, setInput] = useState("");
  const [data, setData] = useState<CandleResponse | null>(null);
  const [detail, setDetail] = useState<{ name: string; price: number | null; change: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!chartTicker) return;
    setError(null);
    setData(null);
    setDetail(null);
    api.candles(chartTicker).then(setData).catch((e) => setError(e.message));
    api.stock(chartTicker).then((d) => {
      const stock = d.stock as { name: string };
      const quote = d.quote as { last: number; change_pct: number } | null;
      const tech = d.technical as { close: number; change_pct: number } | null;
      setDetail({
        name: stock.name,
        price: quote?.last ?? tech?.close ?? null,
        change: quote?.change_pct ?? tech?.change_pct ?? 0,
      });
    }).catch(() => {});
  }, [chartTicker]);

  const entity = detail ? { name: detail.name, price: detail.price, price_change: detail.change } : undefined;
  const signal = signals.find((s) => s.ticker === chartTicker);
  const o = data?.overlays ?? {};

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Stock Charts"
        subtitle={entity ? entity.name : "Choose a ticker"}
        action={
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (input.trim()) openChartFor(input.trim().toUpperCase());
              setInput("");
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value.toUpperCase())}
              placeholder="Ticker"
              className="w-20 rounded-lg border border-glass-edge bg-void-200/70 px-2 py-1 font-mono text-xs text-ink outline-none focus:border-accent/50"
            />
          </form>
        }
      />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!chartTicker ? (
          <EmptyState message="No ticker selected" hint="Search, or click a name in the scanner or the universe." />
        ) : error ? (
          <EmptyState message={error} />
        ) : !data ? (
          <EmptyState message={`Loading ${chartTicker}…`} />
        ) : (
          <>
            <div className="flex items-baseline gap-3 px-5 pt-4">
              <span className="font-mono text-xl text-ink">{chartTicker}</span>
              {entity?.price != null && (
                <span className="font-mono text-sm text-ink-dim">{num(entity.price)}</span>
              )}
              {entity && (
                <span className={`font-mono text-sm ${changeColor(entity.price_change)}`}>
                  {signedPct(entity.price_change)}
                </span>
              )}
              {signal && (
                <Pill tone={signal.execution.allowed ? "up" : "warn"} className="ml-auto">
                  {signal.confidence} · {signal.strategy_label ?? signal.strategy_id}
                </Pill>
              )}
            </div>

            <div className="px-2 pt-2">
              <CandleChart data={data} />
            </div>

            <div className="grid grid-cols-3 gap-x-4 gap-y-2 px-5 pb-5 pt-2 font-mono text-[10px]">
              <Overlay label="EMA 20" value={o.ema20} tone="text-accent" />
              <Overlay label="DMA 50" value={o.dma50} tone="text-warn" />
              <Overlay label="DMA 200" value={o.dma200} tone="text-[#b79bd6]" />
              <Overlay label="VWAP 20" value={o.vwap} />
              <Overlay label="RSI 14" value={o.rsi14} />
              <Overlay label="ATR 14" value={o.atr14} />
              <Overlay label="BB upper" value={o.bb_upper} />
              <Overlay label="BB lower" value={o.bb_lower} />
              <Overlay label="20d high" value={o.high_20} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Overlay({ label, value, tone = "text-ink" }: { label: string; value: number | null | undefined; tone?: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-ink-faint">{label}</span>
      <span className={tone}>{value == null ? "--" : num(value)}</span>
    </div>
  );
}
