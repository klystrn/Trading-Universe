"use client";

/** Contextual liquid-glass popup for the hovered entity (spec 48).
 *
 *  Hovering also stabilises the entity in the scene; this is the readable half
 *  of that interaction.
 */

import { useTradingStore } from "@/stores/useTradingStore";
import { useUniverseStore } from "@/stores/useUniverseStore";
import { changeColor, num, signedPct, usd } from "@/lib/format";
import { Pill } from "./Glass";

export function HoverCard() {
  const hovered = useUniverseStore((s) => s.hovered);
  const entityById = useUniverseStore((s) => s.entityById);
  const sectorById = useUniverseStore((s) => s.sectorById);
  const focusOn = useUniverseStore((s) => s.focusOn);
  const signals = useTradingStore((s) => s.signals);
  const openChartFor = useTradingStore((s) => s.openChartFor);
  const strategies = useTradingStore((s) => s.strategies);

  if (!hovered) return null;

  const sector = sectorById.get(hovered);
  if (sector) {
    return (
      <div className="pointer-events-auto absolute bottom-24 left-1/2 w-[320px] -translate-x-1/2 rounded-2xl border border-glass-edge bg-void-100/88 p-4 backdrop-blur-glass shadow-glass animate-fade-up">
        <h3 className="font-mono text-xs uppercase tracking-[0.2em] text-ink">
          {sector.label}
        </h3>
        <dl className="mt-3 space-y-1.5 text-xs">
          <Row label="Session performance" value={signedPct(sector.performance)}
               tone={changeColor(sector.performance)} />
          <Row label="Relative strength" value={sector.rs_label} />
          <Row label="Breadth" value={`${Math.round(sector.breadth * 100)}%`} />
          <Row label="News sentiment" value={num(sector.news_sentiment, 2)} />
          <Row label="Regime" value={sector.regime.replace(/_/g, " ")} />
          <Row label="Signals" value={String(sector.signal_count)} />
          {sector.recommended_strategy && (
            <Row
              label="Preferred strategy"
              value={
                strategies.find((s) => s.id === sector.recommended_strategy)?.label ??
                sector.recommended_strategy
              }
            />
          )}
        </dl>
        <button
          onClick={() => focusOn(sector.id)}
          className="mt-3 w-full rounded-lg border border-accent/40 bg-accent/10 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-accent transition-colors hover:bg-accent/20"
        >
          Enter sector
        </button>
      </div>
    );
  }

  const entity = entityById.get(hovered);
  if (!entity) return null;

  const signal = signals.find((s) => s.ticker === entity.id);
  const entitySector = sectorById.get(entity.sector);

  return (
    <div className="pointer-events-auto absolute bottom-24 left-1/2 w-[320px] -translate-x-1/2 rounded-2xl border border-glass-edge bg-void-100/88 p-4 backdrop-blur-glass shadow-glass animate-fade-up">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-mono text-base text-ink">{entity.id}</h3>
        <span className={`font-mono text-sm ${changeColor(entity.price_change)}`}>
          {signedPct(entity.price_change)}
        </span>
      </div>
      <p className="mt-0.5 truncate text-xs text-ink-faint">{entity.name}</p>

      <dl className="mt-3 space-y-1.5 text-xs">
        <Row label="Price" value={usd(entity.price)} />
        {!entity.live && (
          <Row label="Quote" value="last close" tone="text-ink-faint" />
        )}
        {signal && (
          <>
            <Row label="Signal" value={String(signal.confidence)} tone="text-accent" />
            <Row label="Strategy" value={signal.strategy_label ?? signal.strategy_id} />
            <Row
              label="Technical"
              value={`${num(signal.score.technical, 1)}/${
                signal.strategy_kind === "political" ? 30 : 40
              }`}
            />
            <Row
              label="Fundamental"
              value={`${num(signal.score.fundamental, 1)}/${
                signal.strategy_kind === "political" ? 25 : 30
              }`}
            />
            {signal.score.political != null && (
              <Row label="Political" value={`${num(signal.score.political, 1)}/25`} />
            )}
            <Row label="Entry / stop" value={`${num(signal.trade.entry)} / ${num(signal.trade.stop)}`} />
            <Row label="Reward:risk" value={`${num(signal.trade.reward_risk)}R`} />
          </>
        )}
        <Row label="Sector" value={entitySector?.label ?? entity.sector} />
        <Row label="Subsector" value={entity.subsector} />
      </dl>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {signal && (
          <Pill tone={signal.execution.allowed ? "up" : "warn"}>
            {signal.execution.allowed ? "Executable" : "Blocked"}
          </Pill>
        )}
        {entity.portfolio?.held && <Pill tone="accent">Held</Pill>}
        {entity.watchlist && <Pill>Watchlist</Pill>}
        {entity.political?.active && (
          <Pill tone="warn">{entity.political.count} disclosure(s)</Pill>
        )}
      </div>

      <button
        onClick={() => openChartFor(entity.id)}
        className="mt-3 w-full rounded-lg border border-accent/40 bg-accent/10 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-accent transition-colors hover:bg-accent/20"
      >
        Open
      </button>
    </div>
  );
}

function Row({
  label,
  value,
  tone = "text-ink",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-faint">{label}</dt>
      <dd className={`truncate font-mono ${tone}`}>{value}</dd>
    </div>
  );
}
