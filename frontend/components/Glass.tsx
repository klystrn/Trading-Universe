"use client";

/** Liquid-glass primitives - the visual language of the left rail and overlays.
 *
 *  Roughly 70% Apple-like polish, 30% dense trading-terminal utility (spec 33):
 *  generous spacing and soft edges, but real density where numbers live.
 */

import { cn } from "@/lib/format";
import type { ReactNode } from "react";

export function GlassPanel({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-glass-edge bg-void-100/65 backdrop-blur-glass shadow-glass",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function PanelHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-glass-edge px-5 py-4">
      <div className="min-w-0">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.2em] text-ink-dim">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 truncate text-xs text-ink-faint">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
  mono = true,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "default" | "up" | "down" | "warn" | "accent";
  mono?: boolean;
}) {
  const toneClass = {
    default: "text-ink",
    up: "text-up",
    down: "text-down",
    warn: "text-warn",
    accent: "text-accent",
  }[tone];

  return (
    <div className="min-w-0">
      <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint">
        {label}
      </p>
      <p className={cn("mt-1 truncate text-sm", mono && "font-mono", toneClass)}>
        {value}
      </p>
      {hint && <p className="mt-0.5 truncate text-[10px] text-ink-faint">{hint}</p>}
    </div>
  );
}

export function Meter({
  value,
  max = 1,
  tone = "accent",
  className,
}: {
  value: number;
  max?: number;
  tone?: "accent" | "up" | "down" | "warn";
  className?: string;
}) {
  const pctValue = Math.max(0, Math.min(1, value / max));
  const bar = {
    accent: "bg-accent",
    up: "bg-up",
    down: "bg-down",
    warn: "bg-warn",
  }[tone];

  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-void-300", className)}>
      <div
        className={cn("h-full rounded-full transition-[width] duration-500 ease-calm", bar)}
        style={{ width: `${pctValue * 100}%` }}
      />
    </div>
  );
}

export function StatusDot({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const color =
    status === "LIVE" || status === "HEALTHY" || status === "CURRENT"
      ? "bg-live"
      : status === "DEGRADED" || status === "WAKING"
        ? "bg-degraded"
        : status === "STALE" || status === "UNAVAILABLE"
          ? "bg-stale"
          : "bg-ink-faint";
  return (
    <span
      className={cn(
        "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
        color,
        status === "DEGRADED" && "animate-pulse-soft",
        className,
      )}
    />
  );
}

export function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  suffix = "",
  onChange,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  onChange: (value: number) => void;
  hint?: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-faint">
          {label}
        </label>
        <span className="font-mono text-sm text-ink">
          {suffix === "$" ? `$${value}` : `${value}${suffix}`}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 h-1 w-full cursor-pointer appearance-none rounded-full bg-void-300 accent-accent
                   [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5
                   [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full
                   [&::-webkit-slider-thumb]:bg-accent [&::-webkit-slider-thumb]:shadow-glow"
      />
      {hint && <p className="mt-1 text-[10px] text-ink-faint">{hint}</p>}
    </div>
  );
}

export function Pill({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  tone?: "default" | "accent" | "up" | "down" | "warn";
  className?: string;
}) {
  const tones = {
    default: "border-glass-edge text-ink-dim",
    accent: "border-accent/40 bg-accent/10 text-accent",
    up: "border-up/40 bg-up/10 text-up",
    down: "border-down/40 bg-down/10 text-down",
    warn: "border-warn/40 bg-warn/10 text-warn",
  }[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em]",
        tones,
        className,
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="px-5 py-10 text-center">
      <p className="text-sm text-ink-dim">{message}</p>
      {hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}
