"use client";

/** The floating liquid-glass search bar (spec 43).
 *
 *  Two jobs in one minimal control: entity search (which triggers camera
 *  travel) and natural-language market questions (answered from the platform's
 *  own state).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/format";
import { useTradingStore } from "@/stores/useTradingStore";
import { useUniverseStore } from "@/stores/useUniverseStore";
import type { QuestionAnswer, SearchResult } from "@/lib/types";

// A question, not a lookup: these words mean "answer me" rather than "find me".
const QUESTION_HINTS = /\?|^(why|what|which|how|show|when|is|are|can|should|who)\b/i;

export function SearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [answer, setAnswer] = useState<QuestionAnswer | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const focusOn = useUniverseStore((s) => s.focusOn);
  const openChartFor = useTradingStore((s) => s.openChartFor);

  const isQuestion = QUESTION_HINTS.test(query.trim()) && query.trim().length > 8;

  // Debounced entity search. Questions are not searched as you type - they are
  // only answered on Enter, since each one is a real backend evaluation.
  useEffect(() => {
    if (!query.trim() || isQuestion) {
      setResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const data = await api.search(query);
        setResults(data.results);
        setHighlight(0);
      } catch {
        setResults([]);
      }
    }, 130);
    return () => clearTimeout(timer);
  }, [query, isQuestion]);

  // Cmd/Ctrl-K focuses the bar from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (document.pointerLockElement) document.exitPointerLock();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const choose = useCallback(
    (result: SearchResult) => {
      // Selecting an entity triggers camera travel to it (spec 43).
      focusOn(result.id);
      if (result.type === "stock") openChartFor(result.id);
      setQuery("");
      setResults([]);
      setOpen(false);
      inputRef.current?.blur();
    },
    [focusOn, openChartFor],
  );

  const ask = useCallback(async () => {
    if (!query.trim()) return;
    setBusy(true);
    setAnswer(null);
    try {
      const data = await api.ask(query);
      setAnswer(data);
      if (data.ticker) focusOn(data.ticker);
      else if (data.sector) focusOn(data.sector);
    } catch {
      setAnswer({
        intent: "error",
        answer: "The platform could not answer that right now.",
      });
    } finally {
      setBusy(false);
    }
  }, [query, focusOn]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setOpen(false);
      setAnswer(null);
      inputRef.current?.blur();
      return;
    }
    if (isQuestion || results.length === 0) {
      if (e.key === "Enter") void ask();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(results.length - 1, h + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(0, h - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const result = results[highlight];
      if (result) choose(result);
    }
  };

  return (
    <div className="pointer-events-auto relative w-[min(560px,calc(100vw-8rem))]">
      <div
        className={cn(
          "flex items-center gap-2.5 rounded-2xl border bg-void-100/70 px-4 py-2.5 backdrop-blur-glass transition-all duration-200 ease-calm",
          open ? "border-accent/40 shadow-glow" : "border-glass-edge shadow-glass",
        )}
      >
        <span className="font-mono text-xs text-ink-faint" aria-hidden>
          {isQuestion ? "?" : "⌕"}
        </span>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setAnswer(null);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 180)}
          onKeyDown={onKeyDown}
          placeholder="Search a ticker or sector, or ask about the market"
          className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
          spellCheck={false}
          autoComplete="off"
        />
        {busy ? (
          <span className="h-3 w-3 animate-spin rounded-full border border-glass-edge border-t-accent" />
        ) : (
          <kbd className="hidden rounded border border-glass-edge px-1.5 py-0.5 font-mono text-[9px] text-ink-faint sm:block">
            ⌘K
          </kbd>
        )}
      </div>

      {open && results.length > 0 && (
        <div className="absolute left-0 right-0 top-full mt-2 overflow-hidden rounded-2xl border border-glass-edge bg-void-100/90 backdrop-blur-glass shadow-glass animate-fade-up">
          {results.map((result, index) => (
            <button
              key={`${result.type}-${result.id}`}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(result);
              }}
              onMouseEnter={() => setHighlight(index)}
              className={cn(
                "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors",
                index === highlight ? "bg-accent/10" : "hover:bg-glass",
              )}
            >
              <div className="min-w-0">
                <span className="font-mono text-sm text-ink">{result.label}</span>
                <span className="ml-2 truncate text-xs text-ink-faint">
                  {result.sublabel}
                </span>
              </div>
              <span className="shrink-0 font-mono text-[9px] uppercase tracking-[0.14em] text-ink-faint">
                {result.type}
              </span>
            </button>
          ))}
        </div>
      )}

      {answer && (
        <div className="absolute left-0 right-0 top-full mt-2 rounded-2xl border border-glass-edge bg-void-100/92 p-4 backdrop-blur-glass shadow-glass animate-fade-up">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm leading-relaxed text-ink">{answer.answer}</p>
            <button
              onClick={() => setAnswer(null)}
              className="shrink-0 font-mono text-xs text-ink-faint hover:text-ink"
              aria-label="Dismiss answer"
            >
              ✕
            </button>
          </div>

          {answer.supported && (
            <ul className="mt-3 space-y-1 border-t border-glass-edge pt-3">
              {answer.supported.map((example) => (
                <li key={example}>
                  <button
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setQuery(example);
                      setAnswer(null);
                      inputRef.current?.focus();
                    }}
                    className="text-left text-xs text-ink-faint transition-colors hover:text-accent"
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {answer.failed_checks && answer.failed_checks.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-glass-edge pt-3">
              {answer.failed_checks.map((check) => (
                <li key={check} className="flex gap-2 text-xs text-ink-dim">
                  <span className="text-down">✕</span>
                  {check}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
