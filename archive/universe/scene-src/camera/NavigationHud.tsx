"use client";

/** Navigation affordances that live outside the canvas: the controls legend,
 *  reset/home shortcuts, and the current filter (spec 46, 56).
 */

import { useUniverseStore } from "@/stores/useUniverseStore";
import { cn } from "@/lib/format";
import type { UniverseFilter } from "@/lib/types";

const FILTERS: { id: UniverseFilter; label: string; hint: string }[] = [
  { id: "MARKET", label: "Market", hint: "Everything, normal state" },
  { id: "SECTORS", label: "Sectors", hint: "Emphasise sector performance" },
  { id: "SIGNALS", label: "Signals", hint: "Fade names with no setup" },
  { id: "POLITICAL", label: "Political", hint: "Highlight disclosed activity" },
  { id: "PORTFOLIO", label: "Portfolio", hint: "Emphasise current holdings" },
  { id: "WATCHLIST", label: "Watchlist", hint: "Emphasise watched names" },
];

export function FilterBar() {
  const filter = useUniverseStore((s) => s.filter);
  const setFilter = useUniverseStore((s) => s.setFilter);
  const showLabels = useUniverseStore((s) => s.showLabels);
  const toggleLabels = useUniverseStore((s) => s.toggleLabels);
  const showFlows = useUniverseStore((s) => s.showFlows);
  const toggleFlows = useUniverseStore((s) => s.toggleFlows);

  return (
    <div className="pointer-events-auto flex items-center gap-1 rounded-full border border-glass-edge bg-void-100/70 p-1 backdrop-blur-glass shadow-glass">
      {FILTERS.map((item) => (
        <button
          key={item.id}
          onClick={() => setFilter(item.id)}
          title={item.hint}
          className={cn(
            "rounded-full px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] transition-colors duration-200 ease-calm",
            filter === item.id
              ? "bg-accent/20 text-accent"
              : "text-ink-faint hover:bg-glass hover:text-ink-dim",
          )}
        >
          {item.label}
        </button>
      ))}
      <div className="mx-1 h-4 w-px bg-glass-edge" />
      <button
        onClick={toggleLabels}
        title="Toggle entity labels"
        className={cn(
          "rounded-full px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] transition-colors",
          showLabels ? "text-ink-dim" : "text-ink-faint/50",
        )}
      >
        Labels
      </button>
      <button
        onClick={toggleFlows}
        title="Toggle inferred sector-rotation arcs"
        className={cn(
          "rounded-full px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] transition-colors",
          showFlows ? "text-ink-dim" : "text-ink-faint/50",
        )}
      >
        Flow
      </button>
    </div>
  );
}

/** The crosshair: visible only in fly mode, brightens and names its target. */
export function Crosshair() {
  const flying = useUniverseStore((s) => s.flying);
  const hovered = useUniverseStore((s) => s.hovered);
  const entityById = useUniverseStore((s) => s.entityById);
  const sectorById = useUniverseStore((s) => s.sectorById);
  if (!flying) return null;
  const target = hovered ? (sectorById.get(hovered)?.label ?? entityById.get(hovered)?.id ?? null) : null;
  const armed = target !== null;
  return (
    <div className="pointer-events-none absolute left-1/2 top-1/2 z-20 -translate-x-1/2 -translate-y-1/2">
      <div className={cn("relative h-8 w-8 transition-transform duration-150 ease-calm", armed && "scale-125")}>
        {[["top-0", "left-1/2 -translate-x-1/2 h-2 w-px"], ["bottom-0", "left-1/2 -translate-x-1/2 h-2 w-px"],
          ["left-0", "top-1/2 -translate-y-1/2 w-2 h-px"], ["right-0", "top-1/2 -translate-y-1/2 w-2 h-px"]].map(([a, b]) => (
          <span key={a} className={cn("absolute", a, b, armed ? "bg-accent shadow-glow" : "bg-ink/70")} />
        ))}
        <span className={cn("absolute left-1/2 top-1/2 h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full",
                            armed ? "bg-accent" : "bg-ink/50")} />
      </div>
      {armed && (
        <div className="absolute left-1/2 top-full mt-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-glass-edge bg-void-100/80 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.14em] text-accent backdrop-blur-glass">
          {target} · click
        </div>
      )}
    </div>
  );
}

export function NavigationHud() {
  const flying = useUniverseStore((s) => s.flying);
  const clearFocus = useUniverseStore((s) => s.clearFocus);
  const focusOn = useUniverseStore((s) => s.focusOn);
  const select = useUniverseStore((s) => s.select);
  const sectors = useUniverseStore((s) => s.sectors);

  const goHome = () => {
    clearFocus();
    select(null);
    // Re-focus the strongest sector: "home" should be somewhere meaningful,
    // not an arbitrary origin.
    const strongest = [...sectors].sort(
      (a, b) => b.relative_strength - a.relative_strength,
    )[0];
    if (strongest) focusOn(strongest.id);
  };

  return (
    <div className="pointer-events-none absolute bottom-5 right-5 z-20 flex flex-col items-end gap-2">
      <div className="pointer-events-auto flex gap-1.5">
        <button
          onClick={goHome}
          className="rounded-lg border border-glass-edge bg-void-100/70 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-dim backdrop-blur-glass transition-colors hover:text-accent"
        >
          Market overview
        </button>
        <button
          onClick={() => {
            clearFocus();
            select(null);
          }}
          className="rounded-lg border border-glass-edge bg-void-100/70 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-dim backdrop-blur-glass transition-colors hover:text-accent"
        >
          Reset view
        </button>
      </div>

      <div className="rounded-lg border border-glass-edge bg-void-100/55 px-3 py-2 backdrop-blur-glass">
        <p className="font-mono text-[9px] leading-relaxed tracking-wider text-ink-faint">
          {flying ? (
            <>
              <span className="text-accent">W A S D</span> move &nbsp;
              <span className="text-accent">MOUSE</span> look &nbsp;
              <span className="text-accent">SPACE</span> up &nbsp;
              <span className="text-accent">C</span> down &nbsp;
              <span className="text-accent">SHIFT</span> boost &nbsp;
              <span className="text-accent">ESC</span> release
            </>
          ) : (
            <>Click the universe to fly</>
          )}
        </p>
      </div>
    </div>
  );
}
