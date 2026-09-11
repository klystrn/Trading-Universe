/** Deterministic command router.
 *
 *  UI and control commands are resolved here, in the browser, with no model:
 *  summon a panel, chart a ticker, stop trading, scan, accept or override the
 *  strategy, change mode, edit the watchlist. Anything that is a question about
 *  the market goes to the backend's own intent matcher (/api/search/ask), which
 *  answers from live platform state. An unrecognised request says so rather
 *  than guessing.
 */

import { api } from "./api";
import type { PanelId, StrategyInfo } from "./types";

export interface Outcome {
  text: string;          // shown in the transcript
  speech?: string;       // spoken form (defaults to text)
  panel?: PanelId | null;
  chart?: string;        // ticker to chart
  refresh?: boolean;     // trading state changed; refetch
}

const PANELS: [RegExp, PanelId][] = [
  [/\b(signals?|scanner|setups?|candidates?)\b/, "signals"],
  [/\b(portfolio|positions?|holdings)\b/, "portfolio"],
  [/\b(trade ?log|trades|history)\b/, "trades"],
  [/\bwatch ?list\b/, "watchlist"],
  [/\b(politicians?|political|congress)\b/, "politicians"],
  [/\b(system|health|status|diagnostics?)\b/, "system"],
  [/\b(parameters?|settings|strategy|strategies|risk)\b/, "parameters"],
  [/\b(charts?)\b/, "charts"],
];

const SUMMON = /^(open|show|bring up|display|pull up|summon|go to|switch to)\b/;
const DISMISS = /^(close|dismiss|hide|clear|go back|back|minimi[sz]e)\b/;

function panelFor(text: string): PanelId | null {
  for (const [re, id] of PANELS) if (re.test(text)) return id;
  return null;
}

const STRATEGY_WORDS: [RegExp, string][] = [
  [/momentum|pullback/, "quality_momentum_pullback"],
  [/catalyst|breakout/, "fundamental_catalyst_breakout"],
  [/oversold|reversal/, "quality_oversold_reversal"],
  [/squeeze|volatility/, "quality_volatility_squeeze"],
  [/value|re-?rating|reclaim/, "value_rerating_50dma_reclaim"],
  [/fresh|purchase/, "congress_fresh_purchase"],
  [/consensus/, "congress_consensus"],
  [/repeat/, "congress_repeat_buyer"],
];

async function resolveTicker(word: string): Promise<{ id: string; name: string } | null> {
  const results = (await api.search(word)).results.filter((r) => r.type === "stock");
  const exact = results.find((r) => r.id.toLowerCase() === word.toLowerCase());
  const pick = exact ?? results[0];
  return pick ? { id: pick.id, name: pick.sublabel } : null;
}

export async function route(
  raw: string,
  context: { strategies: StrategyInfo[]; muted: boolean; toggleMuted: () => void },
): Promise<Outcome> {
  const text = raw.trim().replace(/[.!?]+$/, "");
  const q = text.toLowerCase();
  if (!q) return { text: "" };

  // --- voice ----------------------------------------------------------------
  if (/^(mute|be quiet|silence|stop talking)$/.test(q)) {
    if (!context.muted) context.toggleMuted();
    return { text: "Muted.", speech: "" };
  }
  if (/^(unmute|speak|talk to me)$/.test(q)) {
    if (context.muted) context.toggleMuted();
    return { text: "Voice on." };
  }

  // --- help ---------------------------------------------------------------------
  if (/^(help|what can you do|commands?)$/.test(q)) {
    return {
      text:
        "Try: briefing · show signals · portfolio · chart NVDA · why did the bot reject NVDA · " +
        "which sector is strongest · use recommendation · override to oversold reversal · " +
        "scan now · stop all trading · resume trading · switch to paper auto · watch AMD · close",
      speech: "Ask for the briefing, a panel, a chart, or a market question. Say help to see the list.",
    };
  }

  // --- dismiss --------------------------------------------------------------------
  if (DISMISS.test(q)) return { text: "Dismissed.", speech: "", panel: null };

  // --- kill switch -------------------------------------------------------------------
  if (/(stop all trading|kill switch|halt trading|emergency stop|stop trading)/.test(q) && !/release|resume|clear/.test(q)) {
    await api.killSwitch(true);
    return { text: "Kill switch engaged. All new entries stopped.", panel: "system", refresh: true };
  }
  if (/(resume trading|release (the )?kill switch|clear (the )?kill switch|re-?enable trading)/.test(q)) {
    await api.killSwitch(false);
    return { text: "Kill switch released. Trading may resume under normal gates.", panel: "system", refresh: true };
  }

  // --- scan ----------------------------------------------------------------------------
  if (/\b(re)?scan\b/.test(q)) {
    const r = await api.scan(false);
    return {
      text: `Scan complete: ${r.signals} setups, ${r.executable} executable, in ${r.duration_seconds}s.`,
      panel: "signals",
      refresh: true,
    };
  }

  // --- strategy ----------------------------------------------------------------------------
  if (/(use|accept|take|apply) (the )?recommend/.test(q)) {
    const r = await api.acceptRecommendation();
    const label = context.strategies.find((s) => s.id === r.active_strategy)?.label ?? r.active_strategy;
    return { text: `Recommendation accepted. ${label} is the active strategy.`, panel: "parameters", refresh: true };
  }
  if (/(override|switch|change|set) (the )?(strategy|to)\b|^strategy\b/.test(q) || /\bno trade\b/.test(q)) {
    if (/\bno trade\b/.test(q)) {
      await api.overrideStrategy("NO_TRADE");
      return { text: "Active strategy set to NO TRADE. Nothing will execute; scanning continues.", panel: "parameters", refresh: true };
    }
    const hit = STRATEGY_WORDS.find(([re]) => re.test(q));
    if (hit) {
      const info = context.strategies.find((s) => s.id === hit[1]);
      await api.overrideStrategy(hit[1]);
      return { text: `Override: ${info?.label ?? hit[1]} is now the active execution strategy.`, panel: "parameters", refresh: true };
    }
  }

  // --- mode -------------------------------------------------------------------------------------
  if (/\b(live|real)( auto| trading| mode)?\b/.test(q) && /(switch|go|enter|enable|set|turn)/.test(q)) {
    return {
      text:
        "I won't switch to LIVE from a command. Live trading needs TRADING_ENV=REAL and " +
        "ALLOW_REAL_ORDERS=true on the server, LIVE AUTO selected in Parameters, and execution " +
        "armed in the System panel - deliberately four separate steps.",
      panel: "system",
    };
  }
  if (/\b(advisory|paper( auto)?)\b/.test(q) && /(switch|go|enter|enable|set|turn|mode)/.test(q)) {
    const mode = /paper/.test(q) ? "PAPER_AUTO" : "ADVISORY";
    await api.setMode(mode);
    return { text: `Operating mode set to ${mode.replace("_", " ")}.`, panel: "parameters", refresh: true };
  }

  // --- watchlist ------------------------------------------------------------------------------------
  const watch = q.match(/^(?:watch|add)\s+([a-z.\-]{1,6})(?:\s+to (?:the )?watch ?list)?$/);
  if (watch) {
    const t = await resolveTicker(watch[1]);
    if (!t) return { text: `I don't have ${watch[1].toUpperCase()} in the universe.` };
    await api.addWatchlist(t.id);
    return { text: `${t.id} pinned to the watchlist - it gets scan priority, never a score bonus.`, panel: "watchlist", refresh: true };
  }
  const unwatch = q.match(/^(?:unwatch|remove)\s+([a-z.\-]{1,6})(?:\s+from (?:the )?watch ?list)?$/);
  if (unwatch) {
    await api.removeWatchlist(unwatch[1].toUpperCase());
    return { text: `${unwatch[1].toUpperCase()} removed from the watchlist.`, panel: "watchlist", refresh: true };
  }

  // --- charts ---------------------------------------------------------------------------------------------
  const chart = q.match(/^(?:chart|graph|plot|show me|show|open|look at|inspect)\s+([a-z.\-]{1,6})$/);
  if (chart && !panelFor(chart[1])) {
    const t = await resolveTicker(chart[1]);
    if (t) return { text: `${t.id} - ${t.name}.`, speech: `${t.id}.`, chart: t.id };
  }
  // A bare ticker.
  if (/^[a-z.\-]{1,6}$/.test(q)) {
    const t = await resolveTicker(q);
    if (t) return { text: `${t.id} - ${t.name}.`, speech: `${t.id}.`, chart: t.id };
  }

  // --- summon a panel ----------------------------------------------------------------------------------------
  if (SUMMON.test(q) || /^(the )?(signals?|portfolio|watch ?list|trade ?log|politicians?|system)$/.test(q)) {
    const panel = panelFor(q);
    if (panel) return { text: `${panel[0].toUpperCase()}${panel.slice(1)}.`, speech: "", panel };
  }

  // --- everything else is a market question for the backend -----------------------------------------------------
  const a = await api.ask(text);
  const panel = (a as { panel?: PanelId }).panel ?? null;
  return {
    text: a.answer,
    speech: (a as { speech?: string }).speech ?? a.answer,
    panel: panel ?? undefined,
    chart: a.ticker,
  };
}
