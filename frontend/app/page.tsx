"use client";

/** Trading Universe.
 *
 *  Layout (spec 33-34): the 3D universe owns the whole viewport. A narrow
 *  liquid-glass rail sits on the left; one card at a time expands from it. A
 *  floating search bar sits centre-top, a briefing strip beside it, filters
 *  along the bottom, navigation hints bottom-right.
 */

import dynamic from "next/dynamic";
import { useEffect, useRef } from "react";
import { BriefingStrip } from "@/components/Briefing";
import { GlassPanel } from "@/components/Glass";
import { HoverCard } from "@/components/HoverCard";
import { Rail } from "@/components/Rail";
import { SearchBar } from "@/components/SearchBar";
import { ChartsPanel } from "@/components/panels/Charts";
import { ParametersPanel } from "@/components/panels/Parameters";
import { PoliticiansPanel } from "@/components/panels/Politicians";
import { PortfolioPanel } from "@/components/panels/Portfolio";
import { SignalsPanel } from "@/components/panels/Signals";
import { SystemPanel } from "@/components/panels/System";
import { TradeLogPanel } from "@/components/panels/TradeLog";
import { WatchlistPanel } from "@/components/panels/Watchlist";
import { api } from "@/lib/api";
import { UniverseSocket, type Envelope } from "@/lib/ws";
import { useTradingStore } from "@/stores/useTradingStore";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { FilterBar, NavigationHud } from "@/universe/camera/NavigationHud";
import type {
  Briefing, Signal, SystemHealth, UniversePayload,
} from "@/lib/types";

// WebGL has no server-side rendering; load the scene on the client only.
const UniverseScene = dynamic(
  () => import("@/universe/scene/UniverseScene").then((m) => m.UniverseScene),
  { ssr: false },
);

const PANELS = {
  parameters: ParametersPanel,
  trades: TradeLogPanel,
  watchlist: WatchlistPanel,
  charts: ChartsPanel,
  politicians: PoliticiansPanel,
  signals: SignalsPanel,
  portfolio: PortfolioPanel,
  system: SystemPanel,
} as const;

export default function Page() {
  const openPanel = useTradingStore((s) => s.openPanel);
  const closePanel = useTradingStore((s) => s.closePanel);
  const refreshAll = useTradingStore((s) => s.refreshAll);
  const error = useTradingStore((s) => s.error);
  const setPayload = useUniverseStore((s) => s.setPayload);
  const setConnected = useUniverseStore((s) => s.setConnected);
  const socketRef = useRef<UniverseSocket | null>(null);

  useEffect(() => {
    // Initial state over HTTP, then live updates over the socket.
    void refreshAll();
    api.universe().then(setPayload).catch(() => {});

    const socket = new UniverseSocket();
    socketRef.current = socket;
    const offMessage = socket.onMessage((envelope: Envelope) => {
      switch (envelope.channel) {
        case "universe":
          setPayload(envelope.data as UniversePayload);
          break;
        case "signals": {
          const data = envelope.data as { generated_at: string; signals: Signal[] };
          // The socket carries a compact signal list; refetch the full one so
          // the scanner has complete evidence and execution notes.
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

    // Belt and braces: the socket can miss a push, so poll slowly as well.
    const poll = setInterval(() => void refreshAll(), 60_000);

    return () => {
      offMessage();
      offStatus();
      socket.close();
      clearInterval(poll);
    };
  }, [refreshAll, setPayload, setConnected]);

  // Escape closes the open panel (after releasing the pointer, handled by the
  // scene).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.pointerLockElement) closePanel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closePanel]);

  const Panel = openPanel ? PANELS[openPanel] : null;

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-void">
      <UniverseScene />

      {/* Top: search centre, briefing strip */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex flex-col items-center gap-2 px-4 pt-4">
        <SearchBar />
        <BriefingStrip />
      </div>

      {/* Left: rail + expanding card */}
      <div className="pointer-events-none absolute bottom-4 left-4 top-32 z-30 flex items-stretch gap-3">
        <div className="self-start">
          <Rail />
        </div>
        {Panel && (
          <GlassPanel className="pointer-events-auto w-[min(440px,calc(100vw-6rem))] overflow-hidden animate-fade-up">
            <Panel />
          </GlassPanel>
        )}
      </div>

      {/* Bottom centre: filters */}
      <div className="pointer-events-none absolute bottom-5 left-1/2 z-20 -translate-x-1/2">
        <FilterBar />
      </div>

      <NavigationHud />
      <HoverCard />

      {error && (
        <div className="pointer-events-auto absolute bottom-20 right-5 z-40 rounded-xl border border-down/40 bg-down/10 px-4 py-2 text-xs text-down backdrop-blur-glass">
          Backend unreachable: {error}. Start it with <code>trading-universe serve</code>.
        </div>
      )}

      <h1 className="pointer-events-none absolute bottom-5 left-1/2 hidden -translate-x-1/2 translate-y-8 font-mono text-[9px] uppercase tracking-[0.4em] text-ink-faint/40 lg:block">
        Trading Universe
      </h1>
    </main>
  );
}
