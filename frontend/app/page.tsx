"use client";

/** Trading Universe - the HUD.
 *
 *  A dark instrument: a reactive core in the centre, the questions that matter
 *  (regime, strategy, positions, execution, data) as readouts around it, and a
 *  command line at the bottom that takes text or voice. Panels exist only when
 *  summoned. No WebGL.
 */

import { useCallback, useEffect, useState } from "react";
import { CommandLine } from "@/components/hud/CommandLine";
import { Galaxy, type HoveredStar } from "@/components/hud/Galaxy";
import { StatusReadouts } from "@/components/hud/StatusReadouts";
import { Summon } from "@/components/hud/Summon";
import { api } from "@/lib/api";
import { UniverseSocket, type Envelope } from "@/lib/ws";
import { useHudStore } from "@/stores/useHudStore";
import { useTradingStore } from "@/stores/useTradingStore";
import type { Briefing, Signal, SystemHealth, UniversePayload } from "@/lib/types";

export default function Page() {
  const refreshAll = useTradingStore((s) => s.refreshAll);
  const boot = useTradingStore((s) => s.boot);
  const error = useTradingStore((s) => s.error);
  const waking = useTradingStore((s) => s.waking);
  const wakeStage = useTradingStore((s) => s.wakeStage);
  const openPanel = useTradingStore((s) => s.openPanel);
  const setConnected = useHudStore((s) => s.setConnected);
  const openChartFor = useTradingStore((s) => s.openChartFor);
  const signalsGeneratedAt = useTradingStore((s) => s.signalsGeneratedAt);
  const [universe, setUniverse] = useState<UniversePayload | null>(null);
  const [hovered, setHovered] = useState<HoveredStar | null>(null);

  // The galaxy's stars: reloaded whenever a scan lands, and every 30 s for
  // the day's moves. Failures keep the last good sky.
  const loadUniverse = useCallback(() => {
    api.universe().then(setUniverse).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (waking) return;
    loadUniverse();
    const timer = setInterval(loadUniverse, 30_000);
    return () => clearInterval(timer);
  }, [waking, signalsGeneratedAt, loadUniverse]);

  useEffect(() => {
    void boot();
    const socket = new UniverseSocket(["signals", "system", "briefing"]);
    const offMessage = socket.onMessage((envelope: Envelope) => {
      switch (envelope.channel) {
        case "signals": {
          const data = envelope.data as { generated_at: string; signals: Signal[] };
          void refreshAll();
          useTradingStore.setState({ signalsGeneratedAt: data.generated_at });
          break;
        }
        case "system":
          useTradingStore.getState().setHealth(envelope.data as SystemHealth);
          break;
        case "briefing":
          useTradingStore.getState().setBriefing(envelope.data as Briefing);
          break;
      }
    });
    const offStatus = socket.onStatus(setConnected);
    socket.connect();
    const poll = setInterval(() => void refreshAll(), 60_000);
    return () => { offMessage(); offStatus(); socket.close(); clearInterval(poll); };
  }, [boot, refreshAll, setConnected]);

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-void">

      <header className="pointer-events-none absolute left-6 top-5 z-20">
        <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-ink">Trading Universe</p>
        <p className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.28em] text-ink-faint">advisory intelligence</p>
      </header>

      {/* When a panel is summoned the HUD keeps its layout but yields the
          panel's width, so readouts reflow rather than slide off-screen. */}
      <div className="absolute inset-y-0 left-0 transition-[right] duration-500 ease-calm"
           style={{ right: openPanel ? "min(460px, calc(100vw - 2rem))" : 0 }}>
        <Galaxy universe={universe} onHover={setHovered} onPick={openChartFor} />
        {hovered && <StarCard star={hovered} />}
        {/* Overlays let the pointer through to the galaxy except where they
            need it (the command line opts back in). */}
        <div className="pointer-events-none absolute inset-0">
        {waking && (
          <div className="pointer-events-none absolute left-1/2 top-[63%] z-20 -translate-x-1/2 text-center"
               data-testid="waking">
            <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-accent">
              Waking up
            </p>
            <p className="mt-1 font-mono text-[10px] tracking-[0.12em] text-ink-faint">
              {wakeStage ?? "starting the server"} · the free instance sleeps when idle, this takes about a minute
            </p>
          </div>
        )}
        <StatusReadouts />
        <div className="pointer-events-none absolute inset-x-0 bottom-6 z-20 flex justify-center px-4">
          <CommandLine />
        </div>
        </div>
      </div>

      <Summon />

      {error && (
        <div className="pointer-events-auto absolute right-5 top-5 z-40 rounded-xl border border-down/40 bg-down/10 px-4 py-2 font-mono text-[11px] text-down backdrop-blur-glass">
          Backend unreachable: {error}
        </div>
      )}
    </main>
  );
}

function StarCard({ star }: { star: HoveredStar }) {
  const e = star.entity;
  const change = (e.price_change ?? 0) * 100; // payload carries a fraction
  return (
    <div className="pointer-events-none absolute z-30 -translate-x-1/2 rounded-lg border border-white/10 bg-black/60 px-3 py-2 font-mono text-[10px] backdrop-blur-glass"
         style={{ left: star.x, top: star.y + 14 }}>
      <p className="text-[12px] tracking-[0.12em] text-ink">
        {e.id}{" "}
        <span className={change >= 0 ? "text-up" : "text-down"}>
          {change >= 0 ? "+" : ""}{change.toFixed(2)}%
        </span>
      </p>
      <p className="text-ink-faint">{e.name}</p>
      <p className="mt-0.5 uppercase tracking-[0.18em] text-ink-faint">{star.sectorLabel}</p>
      {e.signal?.active && (
        <p className="mt-0.5 text-accent">
          setup {Math.round(e.signal.score)} · {e.signal.executable ? "executable" : "watch"}
        </p>
      )}
      {e.portfolio?.held && <p className="mt-0.5 text-ink">held · {e.portfolio.pnl_pct.toFixed(1)}%</p>}
      <p className="mt-1 text-ink-faint">click for chart</p>
    </div>
  );
}
