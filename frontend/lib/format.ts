import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export const usd = (value: number | null | undefined, digits = 2) =>
  value == null
    ? "--"
    : value.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

export const pct = (value: number | null | undefined, digits = 2) =>
  value == null ? "--" : `${(value * 100).toFixed(digits)}%`;

export const signedPct = (value: number | null | undefined, digits = 2) =>
  value == null ? "--" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;

export const num = (value: number | null | undefined, digits = 2) =>
  value == null ? "--" : value.toFixed(digits);

export const compact = (value: number | null | undefined) => {
  if (value == null) return "--";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
};

export const relativeTime = (iso: string | null | undefined) => {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 2) return "just now";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
};

export const dataAge = (seconds: number | null | undefined) => {
  if (seconds == null) return "--";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${rest}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
};

/** Human-readable label for a machine-readable rejection reason. */
export const humanizeReason = (reason: string) =>
  reason
    .toLowerCase()
    .split("_")
    .join(" ")
    .replace(/^\w/, (c) => c.toUpperCase());

export const titleize = (value: string) =>
  value
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");

/** Status colour classes. Never colour alone: every use is paired with text. */
export const statusColor = (status: string) => {
  switch (status) {
    case "LIVE":
    case "HEALTHY":
      return "text-live";
    case "DEGRADED":
      return "text-degraded";
    case "STALE":
    case "UNAVAILABLE":
      return "text-stale";
    default:
      return "text-ink-dim";
  }
};

export const changeColor = (value: number) =>
  value > 0.0005 ? "text-up" : value < -0.0005 ? "text-down" : "text-ink-dim";
