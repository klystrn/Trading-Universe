"use client";

/** System / Data Health (spec 32, 42), with the STOP ALL TRADING kill switch. */

import { useState } from "react";
import { api } from "@/lib/api";
import { useTradingStore } from "@/stores/useTradingStore";
import { cn, dataAge, relativeTime, statusColor, titleize } from "@/lib/format";
import { EmptyState, PanelHeader, StatusDot } from "../Glass";

export function SystemPanel() {
  const health = useTradingStore((s) => s.health);
  const setKillSwitch = useTradingStore((s) => s.setKillSwitch);
  const [busy, setBusy] = useState(false);
  const [scanResult, setScanResult] = useState<string | null>(null);

  if (!health) {
    return (
      <div className="flex h-full flex-col">
        <PanelHeader title="System" />
        <EmptyState message="Waiting for the first health report…" />
      </div>
    );
  }

  const toggleKill = async () => {
    setBusy(true);
    try {
      await setKillSwitch(!health.kill_switch_engaged);
    } finally {
      setBusy(false);
    }
  };

  const arm = async (armed: boolean) => {
    await api.armAutoTrade(armed);
    useTradingStore.setState({ health: await api.health() });
  };

  const scan = async () => {
    setBusy(true);
    setScanResult(null);
    try {
      const r = await api.scan(false);
      setScanResult(`${r.signals} signals, ${r.executable} executable, ${r.duration_seconds}s`);
      await useTradingStore.getState().refreshAll();
    } finally {
      setBusy(false);
    }
  };

  const overallHealthy = health.overall === "LIVE" || health.overall === "HEALTHY";
  const readOnly = health.read_only;

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="System / Data Health"
        subtitle={overallHealthy ? "All systems healthy" : `${health.overall} — see below`}
        action={<StatusDot status={health.overall} className="mt-1 h-2.5 w-2.5" />}
      />

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
        {/* --- the kill switch: always visible, always obvious --------------- */}
        {readOnly && (
          <p className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-[11px] leading-relaxed text-warn">
            Shared read-only demo: controls are disabled here. Run the platform
            locally to change modes, limits or execution.
          </p>
        )}
        <button
          onClick={() => void toggleKill()}
          disabled={busy || readOnly}
          className={cn(
            "w-full rounded-xl border-2 py-4 font-mono text-sm uppercase tracking-[0.24em] transition-all duration-200 ease-calm",
            health.kill_switch_engaged
              ? "border-down bg-down/20 text-down shadow-[0_0_28px_rgba(232,136,107,0.35)]"
              : "border-down/60 bg-down/[0.07] text-down hover:bg-down/15",
          )}
        >
          {health.kill_switch_engaged ? "Trading stopped — release" : "Stop all trading"}
        </button>

        {/* --- status grid (spec 42) ------------------------------------------ */}
        <section className="grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-[11px]">
          <Line label="Feed" value={health.sources[0]?.connected ? "CONNECTED" : "DISCONNECTED"} ok={health.sources[0]?.connected} />
          <Line label="Quotes" value={health.overall} ok={overallHealthy} />
          <Line label="Database" value={health.database_healthy ? "HEALTHY" : "ERROR"} ok={health.database_healthy} />
          <Line label="Scanner" value={health.scanner_running ? "RUNNING" : "STOPPED"} ok={health.scanner_running} />
          <Line label="Execution" value={health.operating_mode.replace("_", " ")} />
          <Line label="Auto trade" value={health.auto_trade_enabled ? "ARMED" : "DISABLED"} ok={!health.auto_trade_enabled} />
          <Line label="Env" value={health.trading_env} ok={health.trading_env === "PAPER"} />
          <Line label="Real orders" value={health.allow_real_orders ? "PERMITTED" : "BLOCKED"} ok={!health.allow_real_orders} />
          <Line label="Session" value={health.session.replace("_", " ")} />
          <Line label="Open orders" value={String(health.open_orders)} />
          <Line label="Rejected today" value={String(health.rejected_orders_today)} />
          <Line label="Last scan" value={relativeTime(health.last_scan_at)} />
          <Line label="Last sync" value={relativeTime(health.last_sync_at)} />
        </section>

        <div className="flex gap-1.5">
          <button
            onClick={() => void scan()}
            disabled={busy || readOnly}
            className="flex-1 rounded-lg border border-glass-edge py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-dim hover:text-accent disabled:opacity-50"
          >
            {busy ? "Working…" : "Scan now"}
          </button>
          {health.operating_mode === "LIVE_AUTO" && (
            <button
              onClick={() => void arm(!health.auto_trade_enabled)}
              className={cn(
                "flex-1 rounded-lg border py-1.5 font-mono text-[10px] uppercase tracking-[0.14em]",
                health.auto_trade_enabled
                  ? "border-down/50 text-down"
                  : "border-warn/50 text-warn",
              )}
            >
              {health.auto_trade_enabled ? "Disarm" : "Arm execution"}
            </button>
          )}
        </div>
        {scanResult && <p className="-mt-3 font-mono text-[10px] text-ink-faint">{scanResult}</p>}

        {/* --- data sources (spec 32) ----------------------------------------- */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Data health
          </p>
          <div className="mt-2 space-y-1.5">
            {health.sources.map((source) => (
              <div key={source.name} className="rounded-lg border border-glass-edge px-3 py-2">
                <div className="flex items-center gap-2">
                  <StatusDot status={source.status} />
                  <span className="font-mono text-[11px] text-ink">{source.name}</span>
                  <span className={cn("ml-auto font-mono text-[10px]", statusColor(source.status))}>
                    {source.status}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 font-mono text-[10px] text-ink-faint">
                  {source.latency_ms != null && source.latency_ms > 0 && (
                    <span>latency {Math.round(source.latency_ms)} ms</span>
                  )}
                  {source.last_success_at && <span>updated {relativeTime(source.last_success_at)}</span>}
                  {source.quota_limit != null && (
                    <span>quota {source.quota_used ?? 0} / {source.quota_limit}</span>
                  )}
                  {source.queue_depth != null && <span>queue {source.queue_depth}</span>}
                </div>
                {source.detail && (
                  <p className="mt-0.5 text-[10px] text-ink-faint">{source.detail}</p>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* --- freshness per source ---------------------------------------------- */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Freshness
          </p>
          <div className="mt-2 space-y-1">
            {health.freshness.map((state) => (
              <div key={state.source} className="flex items-center gap-2 text-[11px]">
                <StatusDot status={state.status} />
                <span className="truncate text-ink-dim">{titleize(state.source)}</span>
                {state.blocking && <span className="text-[9px] text-ink-faint">blocking</span>}
                <span className={cn("ml-auto font-mono text-[10px]", statusColor(state.status))}>
                  {state.age_seconds != null ? dataAge(state.age_seconds) : state.status}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* --- strategy gates (spec 30) ---------------------------------------------- */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Strategy gates
          </p>
          <div className="mt-2 space-y-1">
            {Object.entries(health.strategy_gates).map(([strategy, gate]) => {
              const may = gate === "MAY TRADE";
              return (
                <div key={strategy} className="flex items-start gap-2 text-[11px]">
                  <span className={may ? "text-live" : "text-down"}>{may ? "✓" : "✕"}</span>
                  <span className="text-ink-dim">{titleize(strategy)}</span>
                  <span className={cn("ml-auto text-right font-mono text-[9px]", may ? "text-live" : "text-degraded")}>
                    {gate}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function Line({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-ink-faint">{label}</span>
      <span className={ok === undefined ? "text-ink" : ok ? "text-live" : "text-degraded"}>
        {value}
      </span>
    </div>
  );
}
