"use client";

/** Parameters & Strategy (spec 35).
 *
 *  The recommendation, its reasoning, the manual override, and the risk sliders
 *  that map directly onto config/risk.yaml.
 */

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useTradingStore } from "@/stores/useTradingStore";
import { cn, titleize } from "@/lib/format";
import { EmptyState, Meter, PanelHeader, Pill, Slider } from "../Glass";

interface RiskConfig {
  minimum_reward_risk: number;
  max_position_value: number;
  max_new_trades_per_day: number;
  max_open_positions: number;
  min_score_standard: number;
  min_score_political: number;
}

export function ParametersPanel() {
  const recommendation = useTradingStore((s) => s.recommendation);
  const strategies = useTradingStore((s) => s.strategies);
  const activeStrategy = useTradingStore((s) => s.activeStrategy);
  const accept = useTradingStore((s) => s.acceptRecommendation);
  const override = useTradingStore((s) => s.overrideStrategy);
  const health = useTradingStore((s) => s.health);

  const [risk, setRisk] = useState<RiskConfig | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.riskConfig().then((data) => setRisk(data as unknown as RiskConfig)).catch(() => {});
  }, []);

  const patch = async (key: keyof RiskConfig, value: number) => {
    setRisk((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSaving(true);
    try {
      await api.patchRisk({ [key]: value });
    } finally {
      setSaving(false);
    }
  };

  const setMode = async (mode: string) => {
    await api.setMode(mode);
    useTradingStore.setState({ health: await api.health() });
  };

  const readOnly = health?.read_only ?? false;

  const isOverridden =
    activeStrategy !== null &&
    recommendation !== null &&
    activeStrategy !== recommendation.primary_strategy;

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Parameters & Strategy"
        subtitle="Today's recommendation, overrides and risk limits"
        action={saving ? <span className="font-mono text-[9px] text-accent">saving…</span> : null}
      />

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
        {/* --- the recommendation ------------------------------------------- */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Today
          </p>
          {recommendation ? (
            <>
              <h3 className="mt-1.5 text-lg leading-tight text-ink">
                {recommendation.primary_strategy_label}
              </h3>
              <div className="mt-3 flex items-center gap-3">
                <Meter value={recommendation.confidence} />
                <span className="shrink-0 font-mono text-sm text-accent">
                  {Math.round(recommendation.confidence * 100)}%
                </span>
              </div>

              <div className="mt-3 flex items-center gap-2">
                <Pill tone="accent">
                  {recommendation.market_regime.replace(/_/g, " ")}
                </Pill>
                {isOverridden && <Pill tone="warn">Overridden</Pill>}
              </div>

              <ul className="mt-3 space-y-1">
                {recommendation.rationale.map((reason) => (
                  <li key={reason} className="flex gap-2 text-xs text-ink-dim">
                    <span className="mt-0.5 shrink-0 text-accent">✓</span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>

              <button
                onClick={() => void accept()}
                disabled={readOnly || activeStrategy === recommendation.primary_strategy}
                className={cn(
                  "mt-4 w-full rounded-lg border py-2 font-mono text-[10px] uppercase tracking-[0.18em] transition-colors",
                  activeStrategy === recommendation.primary_strategy
                    ? "border-glass-edge text-ink-faint"
                    : "border-accent/40 bg-accent/10 text-accent hover:bg-accent/20",
                )}
              >
                {activeStrategy === recommendation.primary_strategy
                  ? "Recommendation active"
                  : "Use recommendation"}
              </button>
            </>
          ) : (
            <EmptyState
              message="No recommendation yet"
              hint="It appears once the first scan completes."
            />
          )}
        </section>

        {/* --- manual override ----------------------------------------------- */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Active execution strategy
          </p>
          <select
            value={activeStrategy ?? "NO_TRADE"}
            onChange={(e) => void override(e.target.value)}
            disabled={readOnly}
            className="mt-2 w-full disabled:opacity-50 rounded-lg border border-glass-edge bg-void-200/70 px-3 py-2 text-sm text-ink outline-none focus:border-accent/50"
          >
            <option value="NO_TRADE">NO TRADE — nothing executes</option>
            {strategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id} disabled={!strategy.enabled}>
                {strategy.label}
                {strategy.signals_today ? ` (${strategy.signals_today})` : ""}
              </option>
            ))}
          </select>
          <p className="mt-2 text-[10px] leading-relaxed text-ink-faint">
            Only the active strategy may execute automatically. Every other
            strategy keeps scanning and keeps appearing in the scanner and the
            universe.
          </p>
        </section>

        {/* --- execution mode -------------------------------------------------- */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Operating mode
          </p>
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            {(["ADVISORY", "PAPER_AUTO", "LIVE_AUTO"] as const).map((mode) => {
              const active = health?.operating_mode === mode;
              const live = mode === "LIVE_AUTO";
              return (
                <button
                  key={mode}
                  onClick={() => void setMode(mode)}
                  disabled={readOnly}
                  className={cn(
                    "disabled:opacity-50",
                    "rounded-lg border px-2 py-2 font-mono text-[9px] uppercase tracking-[0.1em] transition-colors",
                    active
                      ? live
                        ? "border-down/50 bg-down/15 text-down"
                        : "border-accent/40 bg-accent/10 text-accent"
                      : "border-glass-edge text-ink-faint hover:text-ink-dim",
                  )}
                >
                  {mode.replace("_", " ")}
                </button>
              );
            })}
          </div>
          {health?.operating_mode === "LIVE_AUTO" && !health.allow_real_orders && (
            <p className="mt-2 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-[10px] leading-relaxed text-warn">
              Live mode is selected but real orders remain blocked: the
              environment still has TRADING_ENV=PAPER and ALLOW_REAL_ORDERS=false.
              Both must change on the server, and execution must be armed in the
              System tab.
            </p>
          )}
        </section>

        {/* --- risk sliders ----------------------------------------------------- */}
        {risk && (
          <section className={cn("space-y-4", readOnly && "pointer-events-none opacity-60")}>
            <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
              Risk limits
            </p>
            <Slider
              label="Reward : Risk"
              value={risk.minimum_reward_risk}
              min={1}
              max={5}
              step={0.05}
              suffix=" : 1"
              onChange={(v) => void patch("minimum_reward_risk", v)}
              hint="Minimum acceptable ratio, not a fixed target."
            />
            <Slider
              label="Max capital / trade"
              value={risk.max_position_value}
              min={25}
              max={2000}
              step={25}
              suffix="$"
              onChange={(v) => void patch("max_position_value", v)}
              hint="Capital deployed, not maximum loss."
            />
            <Slider
              label="Max new trades / day"
              value={risk.max_new_trades_per_day}
              min={0}
              max={15}
              onChange={(v) => void patch("max_new_trades_per_day", v)}
            />
            <Slider
              label="Max open positions"
              value={risk.max_open_positions}
              min={0}
              max={20}
              onChange={(v) => void patch("max_open_positions", v)}
            />
            <Slider
              label="Min signal score"
              value={risk.min_score_standard}
              min={0}
              max={100}
              onChange={(v) => void patch("min_score_standard", v)}
              hint="Standard strategies. Political strategies use their own threshold."
            />
            <Slider
              label="Min political score"
              value={risk.min_score_political}
              min={0}
              max={100}
              onChange={(v) => void patch("min_score_political", v)}
            />
          </section>
        )}

        {/* --- per-strategy state -------------------------------------------------- */}
        <section>
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-faint">
            Strategies
          </p>
          <div className="mt-2 space-y-1.5">
            {strategies.map((strategy) => (
              <div
                key={strategy.id}
                className={cn(
                  "rounded-lg border px-3 py-2",
                  strategy.is_active
                    ? "border-accent/35 bg-accent/[0.07]"
                    : "border-glass-edge",
                )}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-xs text-ink">{strategy.label}</span>
                  <span className="shrink-0 font-mono text-[10px] text-ink-dim">
                    {strategy.signals_today}
                  </span>
                </div>
                <p
                  className={cn(
                    "mt-1 font-mono text-[9px] uppercase tracking-[0.1em]",
                    strategy.gate === "MAY TRADE" ? "text-live" : "text-degraded",
                  )}
                >
                  {titleize(strategy.gate)}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
