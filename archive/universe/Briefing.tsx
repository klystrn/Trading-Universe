"use client";

/** The daily briefing (spec 63) - a compact strip along the top edge that
 *  answers the spec-79 questions at a glance. */

import { useTradingStore } from "@/stores/useTradingStore";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { cn, titleize } from "@/lib/format";
import { StatusDot } from "./Glass";

export function BriefingStrip() {
  const briefing = useTradingStore((s) => s.briefing);
  const health = useTradingStore((s) => s.health);
  const activeStrategy = useTradingStore((s) => s.activeStrategy);
  const strategies = useTradingStore((s) => s.strategies);
  const connected = useUniverseStore((s) => s.connected);
  const focusOn = useUniverseStore((s) => s.focusOn);

  if (!briefing) return null;

  const activeLabel = strategies.find((s) => s.id === activeStrategy)?.label ?? "NO TRADE";
  const portfolio = briefing.portfolio ?? {};
  const overall = health?.overall ?? "UNAVAILABLE";
  const canExecute =
    health && !health.kill_switch_engaged && health.operating_mode !== "ADVISORY"
      && (overall === "LIVE" || overall === "HEALTHY" || overall === "DEGRADED");

  return (
    <div className="pointer-events-auto flex flex-wrap items-center gap-x-5 gap-y-1 rounded-2xl border border-glass-edge bg-void-100/65 px-4 py-2 backdrop-blur-glass shadow-glass">
      <Item label="Regime" value={titleize(briefing.market_regime)} />
      <Item label="Active" value={activeLabel} accent />
      <Item
        label="Open"
        value={`${portfolio.open_positions ?? 0} / ${portfolio.max_open_positions ?? "-"}`}
      />
      <Item label="Slots today" value={String(portfolio.remaining_daily_entries ?? "-")} />
      {briefing.high_confidence_signals.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint">Top</span>
          {briefing.high_confidence_signals.slice(0, 3).map((s) => (
            <button
              key={s.ticker}
              onClick={() => focusOn(s.ticker)}
              className="font-mono text-[11px] text-ink hover:text-accent"
              title={s.strategy_label}
            >
              {s.ticker} <span className="text-accent">{s.score}</span>
            </button>
          ))}
        </div>
      )}
      <div className="ml-auto flex items-center gap-3">
        {health?.read_only && (
          <span
            className="rounded-md border border-warn/40 bg-warn/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-warn"
            title="Shared demo: settings, modes and orders cannot be changed here"
          >
            Read-only demo
          </span>
        )}
        <span className={cn("font-mono text-[9px] uppercase tracking-[0.16em]",
          canExecute ? "text-live" : "text-ink-faint")}>
          {health?.kill_switch_engaged ? "STOPPED"
            : health?.operating_mode === "ADVISORY" ? "ADVISORY"
            : canExecute ? "CAN EXECUTE" : "CANNOT EXECUTE"}
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint">
          <StatusDot status={connected ? overall : "UNAVAILABLE"} />
          {connected ? overall : "OFFLINE"}
        </span>
      </div>
    </div>
  );
}

function Item({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint">{label}</span>
      <span className={cn("font-mono text-[11px]", accent ? "text-accent" : "text-ink")}>{value}</span>
    </div>
  );
}
