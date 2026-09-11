"use client";

/** The left-side liquid-glass tab rail (spec 34).
 *
 *  Only one card is expanded at a time. When minimised, more of the universe
 *  becomes visible - which is the point: the visualization is the interface.
 */

import { useTradingStore } from "@/stores/useTradingStore";
import { cn } from "@/lib/format";
import type { PanelId } from "@/lib/types";

const TABS: { id: PanelId; glyph: string; label: string }[] = [
  { id: "parameters", glyph: "⚙", label: "Parameters & Strategy" },
  { id: "trades", glyph: "↕", label: "Trade Log" },
  { id: "watchlist", glyph: "★", label: "Watchlist" },
  { id: "charts", glyph: "◒", label: "Stock Charts" },
  { id: "politicians", glyph: "♙", label: "Politician Trades" },
  { id: "signals", glyph: "◎", label: "Signals / Scanner" },
  { id: "portfolio", glyph: "◫", label: "Portfolio" },
  { id: "system", glyph: "⚡", label: "System / Data Health" },
];

export function Rail() {
  const openPanel = useTradingStore((s) => s.openPanel);
  const togglePanel = useTradingStore((s) => s.togglePanel);
  const health = useTradingStore((s) => s.health);
  const signals = useTradingStore((s) => s.signals);

  const badgeFor = (id: PanelId): number | null => {
    if (id === "signals") return signals.filter((s) => s.execution.allowed).length || null;
    if (id === "system" && health && health.overall !== "LIVE" && health.overall !== "HEALTHY") {
      return 1;
    }
    return null;
  };

  return (
    <nav className="pointer-events-auto flex flex-col gap-1 rounded-2xl border border-glass-edge bg-void-100/65 p-1.5 backdrop-blur-glass shadow-glass">
      {TABS.map((tab) => {
        const active = openPanel === tab.id;
        const badge = badgeFor(tab.id);
        return (
          <button
            key={tab.id}
            onClick={() => togglePanel(tab.id)}
            title={tab.label}
            aria-label={tab.label}
            aria-pressed={active}
            className={cn(
              "group relative flex h-11 w-11 items-center justify-center rounded-xl text-lg transition-all duration-200 ease-calm",
              active
                ? "bg-accent/18 text-accent shadow-glow"
                : "text-ink-faint hover:bg-glass hover:text-ink-dim",
            )}
          >
            <span aria-hidden>{tab.glyph}</span>

            {badge !== null && (
              <span
                className={cn(
                  "absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 font-mono text-[9px]",
                  tab.id === "system"
                    ? "bg-degraded text-void"
                    : "bg-accent text-void",
                )}
              >
                {tab.id === "system" ? "!" : badge}
              </span>
            )}

            {/* Label on hover only - the rail stays narrow so the universe
                keeps the screen. */}
            <span className="pointer-events-none absolute left-full ml-3 hidden whitespace-nowrap rounded-lg border border-glass-edge bg-void-100/90 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-dim backdrop-blur-glass group-hover:block">
              {tab.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
