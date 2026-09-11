"use client";

/** The readouts around the core: the spec-79 questions, always answerable at a
 *  glance without opening anything. */

import { useTradingStore } from "@/stores/useTradingStore";
import { useHudStore } from "@/stores/useHudStore";
import { cn, relativeTime, titleize } from "@/lib/format";
import { StatusDot } from "../Glass";

function Readout({ label, value, tone, hint, align = "left" }: {
  label: string; value: string; tone?: "accent" | "up" | "down" | "warn" | "dim"; hint?: string; align?: "left" | "right";
}) {
  const color = { accent: "text-accent", up: "text-up", down: "text-down", warn: "text-warn", dim: "text-ink-dim" }[tone ?? "dim"];
  return (
    <div className={cn("min-w-[150px]", align === "right" && "text-right")}>
      <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-ink-faint">{label}</p>
      <p className={cn("mt-1 font-mono text-sm tracking-wide", color)}>{value}</p>
      {hint && <p className="mt-0.5 font-mono text-[10px] text-ink-faint">{hint}</p>}
    </div>
  );
}

export function StatusReadouts() {
  const briefing = useTradingStore((s) => s.briefing);
  const health = useTradingStore((s) => s.health);
  const strategies = useTradingStore((s) => s.strategies);
  const activeStrategy = useTradingStore((s) => s.activeStrategy);
  const signals = useTradingStore((s) => s.signals);
  const connected = useHudStore((s) => s.connected);
  const waking = useTradingStore((s) => s.waking);

  const pf = briefing?.portfolio ?? {};
  const overall = waking ? "WAKING" : connected ? (health?.overall ?? "UNAVAILABLE") : "OFFLINE";
  const healthy = overall === "LIVE" || overall === "HEALTHY";
  const canExecute = !!health && !health.kill_switch_engaged && health.operating_mode !== "ADVISORY"
    && (healthy || overall === "DEGRADED");
  const executable = signals.filter((s) => s.execution.allowed).length;
  const active = strategies.find((s) => s.id === activeStrategy)?.label ?? "NO TRADE";

  return (
    <>
      <div className="absolute left-[10%] top-[22%] space-y-6">
        <Readout label="Market regime" value={titleize(briefing?.market_regime ?? "unknown")} tone="accent"
                 hint={briefing?.regime_confidence != null ? `${Math.round(briefing.regime_confidence * 100)}% confidence` : undefined} />
        <Readout label="Active strategy" value={active} tone={activeStrategy ? "accent" : "warn"}
                 hint={briefing?.primary_strategy_label && briefing.primary_strategy !== activeStrategy
                   ? `recommended: ${briefing.primary_strategy_label}` : undefined} />
      </div>
      <div className="absolute right-[10%] top-[22%] space-y-6">
        <Readout align="right" label="Open positions" value={`${pf.open_positions ?? 0} / ${pf.max_open_positions ?? "-"}`}
                 hint={`${pf.remaining_daily_entries ?? "-"} entries left today`} />
        <Readout align="right" label="Setups" value={`${signals.length} · ${executable} executable`} tone="accent"
                 hint={briefing?.high_confidence_signals?.slice(0, 3).map((s) => `${s.ticker} ${s.score}`).join("  ")} />
      </div>
      <div className="absolute left-[10%] bottom-[34%]">
        <Readout label="Execution" value={health?.kill_switch_engaged ? "STOPPED" : (health?.operating_mode ?? "").replace("_", " ")}
                 tone={health?.kill_switch_engaged ? "down" : canExecute ? "up" : "dim"}
                 hint={health?.kill_switch_engaged ? "kill switch engaged" : canExecute ? "can execute" : "advisory - will not execute"} />
      </div>
      <div className="absolute right-[10%] bottom-[34%] text-right">
        <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-ink-faint">Data</p>
        <p className="mt-1 flex items-center justify-end gap-2 font-mono text-sm">
          <StatusDot status={overall} />
          <span className={healthy ? "text-live" : overall === "DEGRADED" ? "text-degraded" : "text-stale"}>{overall}</span>
        </p>
        <p className="mt-0.5 font-mono text-[10px] text-ink-faint">
          {health?.session?.replace("_", " ").toLowerCase()} · scanned {relativeTime(health?.last_scan_at)}
        </p>
      </div>
    </>
  );
}
