"use client";

/** Politician trade monitoring (spec 39). V1 is signal-focused. */

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useTradingStore } from "@/stores/useTradingStore";
import { cn, compact, titleize } from "@/lib/format";
import { EmptyState, PanelHeader, Pill } from "../Glass";
import type { PoliticalTransaction } from "@/lib/types";

export function PoliticiansPanel() {
  const openChartFor = useTradingStore((s) => s.openChartFor);
  const [rows, setRows] = useState<PoliticalTransaction[]>([]);
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [query, setQuery] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.politicalSummary().then(setSummary).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.political({ ...query, limit: 150 });
      setRows(data.transactions);
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    void load();
  }, [load]);

  const set = (key: string, value: string) =>
    setQuery((prev) => {
      const next = { ...prev };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });

  const lag = summary?.disclosure_lag as Record<string, number> | undefined;

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Politician Trades"
        subtitle={
          summary
            ? `${summary.transactions} disclosures · ${summary.politicians} accounts`
            : "Disclosures"
        }
      />

      <div className="space-y-2 border-b border-glass-edge px-5 py-3">
        <div className="flex flex-wrap gap-1.5">
          <input
            value={query.politician ?? ""}
            onChange={(e) => set("politician", e.target.value)}
            placeholder="Politician"
            className="w-28 rounded-lg border border-glass-edge bg-void-200/70 px-2 py-1 text-[11px] text-ink outline-none"
          />
          <input
            value={query.ticker ?? ""}
            onChange={(e) => set("ticker", e.target.value.toUpperCase())}
            placeholder="Ticker"
            className="w-20 rounded-lg border border-glass-edge bg-void-200/70 px-2 py-1 font-mono text-[11px] text-ink outline-none"
          />
          <Select value={query.chamber ?? ""} onChange={(v) => set("chamber", v)}
                  options={[["", "Both chambers"], ["HOUSE", "House"], ["SENATE", "Senate"]]} />
          <Select value={query.party ?? ""} onChange={(v) => set("party", v)}
                  options={[["", "Any party"], ["D", "D"], ["R", "R"], ["I", "I"]]} />
          <Select value={query.transaction_type ?? ""} onChange={(v) => set("transaction_type", v)}
                  options={[["", "Buys & sales"], ["PURCHASE", "Purchases"], ["SALE", "Sales"]]} />
          <Select value={query.disclosed_within_days ?? ""} onChange={(v) => set("disclosed_within_days", v)}
                  options={[["", "Any recency"], ["7", "7 days"], ["30", "30 days"], ["90", "90 days"]]} />
          <Select value={query.min_amount ?? ""} onChange={(v) => set("min_amount", v)}
                  options={[["", "Any size"], ["15001", "$15k+"], ["50001", "$50k+"], ["100001", "$100k+"]]} />
        </div>
        {lag && lag.count > 0 && (
          <p className="text-[10px] leading-relaxed text-ink-faint">
            Median disclosure lag {lag.median_lag_days} days. All windows run from
            the disclosure date, never the transaction date.
          </p>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <EmptyState message="Loading disclosures…" />
        ) : rows.length === 0 ? (
          <EmptyState
            message="No disclosures match"
            hint="In LIVE mode, import a periodic transaction report export with the CLI."
          />
        ) : (
          <div className="divide-y divide-glass-edge/60">
            {rows.map((row) => (
              <div key={row.transaction_id} className="px-5 py-3">
                <div className="flex items-baseline justify-between gap-2">
                  <button
                    onClick={() => row.in_universe && openChartFor(row.ticker)}
                    className={cn(
                      "font-mono text-sm",
                      row.in_universe ? "text-ink hover:text-accent" : "text-ink-faint",
                    )}
                  >
                    {row.ticker}
                  </button>
                  <Pill tone={row.transaction_type === "PURCHASE" ? "up" : "down"}>
                    {titleize(row.transaction_type)}
                  </Pill>
                </div>
                <p className="mt-0.5 text-xs text-ink-dim">
                  {row.politician}
                  <span className="text-ink-faint">
                    {" "}· {row.chamber === "HOUSE" ? "House" : "Senate"}
                    {row.party ? ` · ${row.party}` : ""}
                    {row.state ? `-${row.state}` : ""}
                    {row.owner !== "SELF" && row.owner !== "UNKNOWN" ? ` · ${titleize(row.owner)}` : ""}
                  </span>
                </p>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-ink-faint">
                  <span>${compact(row.amount_low)}–${compact(row.amount_high)}</span>
                  <span>traded {row.transaction_date}</span>
                  <span>disclosed {row.disclosure_date}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Select({
  value, onChange, options,
}: { value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-glass-edge bg-void-200/70 px-2 py-1 font-mono text-[10px] text-ink-dim outline-none"
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>{label}</option>
      ))}
    </select>
  );
}
