"use client";

/** The command line: type or hold to talk; replies are shown and spoken. */

import { useCallback, useEffect, useRef, useState } from "react";
import { route } from "@/lib/intents";
import { cn } from "@/lib/format";
import { createRecognizer, recognitionSupported, speak, stopSpeaking } from "@/lib/voice";
import { useHudStore } from "@/stores/useHudStore";
import { useTradingStore } from "@/stores/useTradingStore";

const SUGGESTIONS = [
  "Briefing", "Show signals", "Portfolio", "Chart NVDA",
  "Which sector is strongest today?", "Why did the bot reject NVDA?", "Can you execute?",
];

export function CommandLine() {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const recognizerRef = useRef<ReturnType<typeof createRecognizer>>(null);
  const [voiceOk, setVoiceOk] = useState(false);

  const { say, listening, setListening, interim, setInterim, setSpeaking, muted, toggleMuted, busy, setBusy } = useHudStore();
  const transcript = useHudStore((s) => s.transcript);
  const strategies = useTradingStore((s) => s.strategies);
  const refreshAll = useTradingStore((s) => s.refreshAll);
  const openChartFor = useTradingStore((s) => s.openChartFor);

  useEffect(() => setVoiceOk(recognitionSupported()), []);

  const submit = useCallback(async (text: string) => {
    const cleaned = text.trim();
    if (!cleaned || busy) return;
    setValue("");
    setInterim("");
    say("you", cleaned);
    setBusy(true);
    stopSpeaking();
    try {
      const out = await route(cleaned, { strategies, muted, toggleMuted });
      if (out.text) say("tu", out.text);
      if (out.panel !== undefined) {
        useTradingStore.setState({ openPanel: out.panel });
      }
      if (out.chart) openChartFor(out.chart);
      if (out.refresh) void refreshAll();
      const speech = out.speech ?? out.text;
      if (speech && !useHudStore.getState().muted) {
        speak(speech, () => setSpeaking(true), () => setSpeaking(false));
      }
    } catch (error) {
      say("tu", error instanceof Error ? `That failed: ${error.message}` : "That failed.");
    } finally {
      setBusy(false);
    }
  }, [busy, say, setBusy, setInterim, setSpeaking, strategies, muted, toggleMuted, openChartFor, refreshAll]);

  // --- push to talk ------------------------------------------------------------
  const startListening = useCallback(() => {
    if (listening || !voiceOk) return;
    stopSpeaking();
    const rec = createRecognizer({
      onInterim: setInterim,
      onFinal: (text) => { setInterim(""); void submit(text); },
      onEnd: () => setListening(false),
      onError: (message) => { setListening(false); setInterim(""); if (message !== "aborted" && message !== "no-speech") say("tu", `Microphone: ${message}.`); },
    });
    if (!rec) return;
    recognizerRef.current = rec;
    setListening(true);
    try { rec.start(); } catch { setListening(false); }
  }, [listening, voiceOk, setInterim, setListening, submit, say]);

  const stopListening = useCallback(() => {
    recognizerRef.current?.stop();
  }, []);

  // Hold Ctrl+Space (or the mic button) to talk; Escape stops speech.
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code === "Space" && e.ctrlKey && !e.repeat) { e.preventDefault(); startListening(); }
      if (e.key === "Escape") stopSpeaking();
      if (e.key === "/" && document.activeElement !== inputRef.current) { e.preventDefault(); inputRef.current?.focus(); }
    };
    const up = (e: KeyboardEvent) => { if (e.code === "Space" && e.ctrlKey) stopListening(); };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [startListening, stopListening]);

  const recent = transcript.slice(-4);

  return (
    <div className="pointer-events-auto w-[min(720px,calc(100vw-2rem))]">
      {/* Transcript: the last few exchanges, newest at the bottom. */}
      <div className="mb-3 space-y-1.5 px-1">
        {recent.map((x) => (
          <p key={x.id} className={cn("font-mono text-[12px] leading-relaxed animate-fade-up",
              x.role === "you" ? "text-ink-faint" : "text-ink")}>
            <span className={cn("mr-2 text-[9px] uppercase tracking-[0.2em]", x.role === "you" ? "text-ink-faint/70" : "text-accent")}>
              {x.role === "you" ? "you" : "tu"}
            </span>
            {x.text}
          </p>
        ))}
        {interim && <p className="font-mono text-[12px] italic text-accent/70">{interim}…</p>}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); void submit(value); }}
        className={cn("flex items-center gap-3 rounded-2xl border bg-void-100/70 px-4 py-3 backdrop-blur-glass transition-all duration-200 ease-calm",
          listening ? "border-accent/60 shadow-glow" : "border-glass-edge shadow-glass")}
      >
        <button
          type="button"
          onMouseDown={startListening}
          onMouseUp={stopListening}
          onMouseLeave={stopListening}
          onTouchStart={startListening}
          onTouchEnd={stopListening}
          disabled={!voiceOk}
          title={voiceOk ? "Hold to talk (or hold Ctrl+Space)" : "Voice input needs Chrome or Edge"}
          aria-label="Hold to talk"
          className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition-all",
            listening ? "border-accent bg-accent/20 text-accent animate-pulse-soft" : "border-glass-edge text-ink-dim hover:text-accent",
            !voiceOk && "opacity-40")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
          </svg>
        </button>
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={listening ? "Listening…" : "Ask, or give a command   ·   /"}
          className="w-full bg-transparent font-mono text-sm text-ink outline-none placeholder:text-ink-faint"
          spellCheck={false}
          autoComplete="off"
          autoFocus
        />
        {busy ? (
          <span className="h-3 w-3 shrink-0 animate-spin rounded-full border border-glass-edge border-t-accent" />
        ) : (
          <button type="button" onClick={toggleMuted} title={muted ? "Unmute replies" : "Mute replies"}
                  className="shrink-0 font-mono text-[9px] uppercase tracking-[0.16em] text-ink-faint hover:text-accent">
            {muted ? "muted" : "voice"}
          </button>
        )}
      </form>

      <div className="mt-2 flex flex-wrap justify-center gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button key={s} onClick={() => void submit(s)}
                  className="rounded-full border border-glass-edge px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-faint transition-colors hover:border-accent/40 hover:text-accent">
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
