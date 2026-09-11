"""Market question answering for the floating search bar (spec section 43).

Deliberately a deterministic intent matcher over the platform's own state rather
than a language model. Every answer is therefore traceable to data the system
actually holds, and a question it cannot answer says so instead of improvising
a plausible-sounding number.

Supported intents mirror the spec's examples:
    Which sector is strongest today?
    Why is <sector> outperforming?
    What are the best momentum setups?
    Show me political purchases in Financials.
    What is my highest-confidence trade?
    Why did the bot reject NVDA?
"""

from __future__ import annotations

import re
from typing import Any

_SECTOR_WORDS = {
    "tech": "information_technology",
    "technology": "information_technology",
    "semis": "information_technology",
    "semiconductors": "information_technology",
    "health": "health_care",
    "healthcare": "health_care",
    "financial": "financials",
    "financials": "financials",
    "banks": "financials",
    "energy": "energy",
    "industrial": "industrials",
    "industrials": "industrials",
    "utilities": "utilities",
    "staples": "consumer_staples",
    "discretionary": "consumer_discretionary",
    "materials": "materials",
    "real estate": "real_estate",
    "communication": "communication_services",
    "comms": "communication_services",
}

_STRATEGY_WORDS = {
    "momentum": "quality_momentum_pullback",
    "pullback": "quality_momentum_pullback",
    "catalyst": "fundamental_catalyst_breakout",
    "breakout": "fundamental_catalyst_breakout",
    "oversold": "quality_oversold_reversal",
    "reversal": "quality_oversold_reversal",
    "squeeze": "quality_volatility_squeeze",
    "volatility": "quality_volatility_squeeze",
    "value": "value_rerating_50dma_reclaim",
    "reclaim": "value_rerating_50dma_reclaim",
    "congress": "congress_consensus",
    "political": "congress_consensus",
    "politician": "congress_consensus",
}


def _speech(text: str, limit: int = 220) -> str:
    """A short spoken form: the first sentence or two, trimmed for TTS."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    out = ""
    for part in parts:
        if len(out) + len(part) > limit and out:
            break
        out = f"{out} {part}".strip()
    return out or text[:limit]


def _answer(kind: str, text: str, **extra: Any) -> dict[str, Any]:
    speech = extra.pop("speech", None) or _speech(text)
    return {"intent": kind, "answer": text, "speech": speech, **extra}


def _find_sector(query: str, platform) -> str | None:
    for word, sector_id in _SECTOR_WORDS.items():
        if word in query:
            return sector_id
    for sector_id, sector in platform.universe.sectors.items():
        if sector.label.lower() in query or sector_id.replace("_", " ") in query:
            return sector_id
    return None


def _find_ticker(query: str, platform) -> str | None:
    for token in re.findall(r"\b[A-Za-z.\-]{1,6}\b", query):
        candidate = token.upper()
        if platform.universe.get(candidate) is not None and candidate not in (
            "A", "THE", "IS", "MY", "IT", "IN", "WHY", "DID", "BOT", "ON", "OF", "ME",
        ):
            return candidate
    return None


def _find_strategy(query: str) -> str | None:
    for word, sid in _STRATEGY_WORDS.items():
        if word in query:
            return sid
    return None


def answer_question(question: str, platform, labels: dict[str, str]) -> dict[str, Any]:
    query = question.strip().lower()
    result = platform.scanner.last_result

    if result is None:
        return _answer(
            "not_ready",
            "No scan has completed yet, so there is nothing to report. "
            "Trigger a scan from the System tab.",
        )

    sector_id = _find_sector(query, platform)
    ticker = _find_ticker(query, platform)
    strategy_id = _find_strategy(query)
    sectors = sorted(result.sector_regimes, key=lambda s: s.relative_strength, reverse=True)

    # --- briefing / status report -------------------------------------------
    briefing_words = ("briefing", "status report", "morning report", "good morning",
                      "daily report", "summary of the day", "what's the plan")
    if any(w in query for w in briefing_words):
        b = platform.briefing()
        pf = b.get("portfolio", {})
        top = ", ".join(
            f"{x['ticker']} {x['score']}" for x in b.get("high_confidence_signals", [])[:3]
        )
        strongest = ", ".join(
            x["sector"].replace("_", " ") for x in b.get("strongest_sectors", [])[:2]
        )
        counts = b.get("signal_counts", {})
        text = (
            f"Regime {b['market_regime'].replace('_', ' ').title()}. "
            f"Strategy of the day: {b.get('primary_strategy_label') or 'none'} at "
            f"{round((b.get('confidence') or 0) * 100)} percent confidence. "
            f"{counts.get('total', 0)} setups found, {counts.get('executable', 0)} executable"
            + (f", led by {top}. " if top else ". ")
            + (f"Strongest sectors: {strongest}. " if strongest else "")
            + f"{pf.get('open_positions', 0)} of {pf.get('max_open_positions', 0)} positions open, "
            f"{pf.get('remaining_daily_entries', 0)} entries left today."
        )
        return _answer("briefing", text, briefing=b, panel="signals", speech=text)

    # --- portfolio ------------------------------------------------------------
    portfolio_words = ("portfolio", "positions", "how am i doing", "my holdings", "p&l", "pnl")
    if any(w in query for w in portfolio_words):
        pf = platform.broker.get_portfolio()
        risk = platform.config.risk
        held = ", ".join(
            f"{p.ticker} {p.unrealized_pnl_pct:+.1%}" for p in pf.positions[:5]
        ) or "no open positions"
        text = (
            f"Portfolio value {pf.portfolio_value:,.0f} dollars, cash {pf.cash:,.0f}. "
            f"{len(pf.positions)} of {risk.max_open_positions} positions open: {held}. "
            f"Unrealized {pf.unrealized_pnl:+,.2f}, realized today {pf.realized_pnl_today:+,.2f}."
        )
        return _answer("portfolio", text, panel="portfolio")

    # --- capacity ---------------------------------------------------------------
    if any(w in query for w in ("how many trades", "capacity", "slots", "can i open", "room for")):
        pf = platform.broker.get_portfolio()
        risk = platform.config.risk
        today = getattr(platform.broker, "trades_opened_today", lambda: 0)()
        slots = max(0, risk.max_open_positions - len(pf.positions))
        daily = max(0, risk.max_new_trades_per_day - today)
        text = (
            f"{slots} position slot{'s' if slots != 1 else ''} free of {risk.max_open_positions}, "
            f"and {daily} new entr{'ies' if daily != 1 else 'y'} left today of "
            f"{risk.max_new_trades_per_day}. Max {risk.max_position_value:,.0f} dollars per trade."
        )
        return _answer("capacity", text, panel="portfolio")

    # --- active strategy ----------------------------------------------------------
    strategy_words = ("active strategy", "what strategy", "which strategy",
                      "strategy of the day", "recommended strategy", "current strategy")
    if any(w in query for w in strategy_words):
        active = platform.execution.active_strategy
        rec = result.recommendation
        text = f"Active execution strategy: {labels.get(active or '', 'none - NO TRADE')}. "
        if rec:
            overridden = active is not None and active != rec.primary_strategy
            text += (
                f"Today's recommendation is "
                f"{labels.get(rec.primary_strategy, rec.primary_strategy)} at "
                f"{rec.confidence:.0%}"
                + (" - currently overridden." if overridden else ".")
            )
        return _answer("strategy", text, panel="parameters", active=active)

    # --- health / can you execute ----------------------------------------------------
    health_words = ("can you execute", "can you trade", "data live", "is data", "health",
                    "systems", "are we live", "system status", "diagnostic")
    if any(w in query for w in health_words):
        h = platform.health.snapshot()
        bad = ("DEGRADED", "STALE", "UNAVAILABLE")
        degraded = [s.name for s in h.sources if s.status.value in bad]
        blocked = [k for k, v in h.strategy_gates.items() if v != "MAY TRADE"]
        kill = "engaged" if h.kill_switch_engaged else "clear"
        text = (
            f"Data {h.overall.value.lower()}. Mode {h.operating_mode.replace('_', ' ')}, "
            f"environment {h.trading_env}, kill switch {kill}. "
        )
        if degraded:
            text += f"Degraded sources: {', '.join(degraded)}. "
        else:
            text += "All sources healthy. "
        if blocked:
            plural = "ies" if len(blocked) != 1 else "y"
            text += f"{len(blocked)} strateg{plural} gated by freshness."
        else:
            text += "Every strategy may trade."
        return _answer("health", text, panel="system", health=h.model_dump(mode="json"))

    # --- why was X rejected ------------------------------------------------
    if ticker and any(w in query for w in ("reject", "not trade", "why not", "blocked")):
        matches = [s for s in result.signals if s.ticker == ticker]
        if not matches:
            near = [e for e in result.near_misses if e.ticker == ticker]
            if near:
                evaluation = near[0]
                return _answer(
                    "rejection",
                    f"{ticker} produced no signal. The closest was "
                    f"{labels.get(evaluation.strategy_id, evaluation.strategy_id)}, which "
                    f"failed on: " + "; ".join(evaluation.failed_checks) + ".",
                    ticker=ticker,
                    failed_checks=evaluation.failed_checks,
                )
            return _answer(
                "rejection",
                f"{ticker} did not produce a signal on the last scan, and was not "
                "close to one on any strategy.",
                ticker=ticker,
            )
        signal = max(matches, key=lambda s: s.score.total)
        if signal.execution.allowed:
            return _answer(
                "rejection",
                f"{ticker} was not rejected. It scored {signal.confidence} on "
                f"{labels.get(signal.strategy_id, signal.strategy_id)} and is executable.",
                ticker=ticker,
                signal=signal.model_dump(mode="json"),
            )
        reasons = ", ".join(r.value.replace("_", " ").lower() for r in signal.execution.reasons)
        return _answer(
            "rejection",
            f"{ticker} scored {signal.confidence} on "
            f"{labels.get(signal.strategy_id, signal.strategy_id)} but the risk engine "
            f"blocked it: {reasons}. " + " ".join(signal.execution.notes),
            ticker=ticker,
            signal=signal.model_dump(mode="json"),
        )

    # --- highest-confidence trade --------------------------------------------
    if any(w in query for w in ("highest", "best trade", "top trade", "highest-confidence")) \
            and not strategy_id:
        executable = result.executable or result.signals
        if not executable:
            return _answer("best_trade", "There are no qualifying setups right now. NO TRADE.")
        best = executable[0]
        return _answer(
            "best_trade",
            f"{best.ticker} at {best.confidence}/100 on "
            f"{labels.get(best.strategy_id, best.strategy_id)}. "
            f"Entry {best.trade.entry:.2f}, stop {best.trade.stop:.2f}, "
            f"target {best.trade.target:.2f} ({best.trade.reward_risk:.2f}R). "
            + ("Executable." if best.execution.allowed
               else f"Not executable: {best.execution.reason or ''}"),
            ticker=best.ticker,
            signal=best.model_dump(mode="json"),
        )

    # --- strongest / weakest sector --------------------------------------------
    if any(w in query for w in ("strongest", "leading", "best sector")):
        if not sectors:
            return _answer("sector_strength", "No sector data yet.")
        top = sectors[0]
        return _answer(
            "sector_strength",
            f"{platform.universe.sectors[top.sector_id].label} is strongest, "
            f"{top.relative_strength:+.2%} relative to the market ({top.rs_label}), "
            f"with {top.breadth:.0%} of its names above their 50DMA and "
            f"{top.signal_count} signal(s) today. "
            f"Preferred strategy: {labels.get(top.recommended_strategy or '', 'none')}.",
            sector=top.sector_id,
            ranking=[{"sector": s.sector_id, "rs": s.relative_strength} for s in sectors],
        )

    if any(w in query for w in ("weakest", "worst sector", "lagging")):
        if not sectors:
            return _answer("sector_strength", "No sector data yet.")
        bottom = sectors[-1]
        return _answer(
            "sector_strength",
            f"{platform.universe.sectors[bottom.sector_id].label} is weakest, "
            f"{bottom.relative_strength:+.2%} relative to the market, with "
            f"{bottom.breadth:.0%} above their 50DMA.",
            sector=bottom.sector_id,
        )

    # --- why is <sector> outperforming ------------------------------------------
    if sector_id and any(
        w in query for w in ("why", "outperform", "underperform", "doing", "how is")
    ):
        match = next((s for s in sectors if s.sector_id == sector_id), None)
        if match is None:
            return _answer("sector_detail", f"No data for {sector_id}.")
        return _answer(
            "sector_detail",
            f"{platform.universe.sectors[sector_id].label}: "
            f"{match.regime.value.replace('_', ' ').title()}, "
            f"{match.relative_strength:+.2%} vs the market. "
            + " ".join(match.rationale),
            sector=sector_id,
            detail=match.model_dump(mode="json"),
        )

    # --- political activity ---------------------------------------------------------
    if any(w in query for w in ("political", "congress", "senator", "politician", "disclosure")):
        politicals = platform.features.politicals(platform.universe.tickers())
        rows = [
            (t, s) for t, s in politicals.items()
            if s.purchases_30d > 0
            and (sector_id is None or platform.universe.sector_of(t) == sector_id)
        ]
        rows.sort(key=lambda kv: kv[1].consensus_score, reverse=True)
        if not rows:
            where = (
                f" in {platform.universe.sectors[sector_id].label}" if sector_id else ""
            )
            return _answer(
                "political",
                f"No disclosed congressional purchases{where} in the last 30 days.",
                sector=sector_id,
            )
        top = ", ".join(
            f"{t} ({s.distinct_politicians_30d} buyer(s))" for t, s in rows[:6]
        )
        where = f" in {platform.universe.sectors[sector_id].label}" if sector_id else ""
        return _answer(
            "political",
            f"{len(rows)} name(s){where} with disclosed purchases in the last 30 "
            f"days: {top}. All windows run from the disclosure date, not the "
            "transaction date.",
            sector=sector_id,
            tickers=[t for t, _ in rows[:20]],
        )

    # --- best setups for a strategy ------------------------------------------------------
    if strategy_id or any(w in query for w in ("setups", "candidates", "opportunities")):
        matches = [
            s for s in result.signals
            if (strategy_id is None or s.strategy_id == strategy_id)
            and (sector_id is None or s.sector == sector_id)
        ]
        if not matches:
            name = labels.get(strategy_id or "", "any strategy")
            return _answer(
                "setups", f"No qualifying {name} setups right now. NO TRADE.",
                strategy=strategy_id,
            )
        listed = ", ".join(
            f"{s.ticker} ({s.confidence})" for s in matches[:8]
        )
        name = labels.get(strategy_id or "", "All strategies")
        return _answer(
            "setups",
            f"{name}: {len(matches)} setup(s). Top: {listed}.",
            strategy=strategy_id,
            tickers=[s.ticker for s in matches[:20]],
        )

    # --- regime -------------------------------------------------------------------------
    if any(w in query for w in ("regime", "market doing", "how is the market")):
        regime = result.regime
        if regime is None:
            return _answer("regime", "No regime computed yet.")
        return _answer(
            "regime",
            f"{regime.regime.value.replace('_', ' ').title()} "
            f"({regime.confidence:.0%} confidence). " + " ".join(regime.rationale),
            regime=regime.regime.value,
        )

    # --- a plain ticker lookup --------------------------------------------------------------
    if ticker:
        matches = [s for s in result.signals if s.ticker == ticker]
        stock = platform.universe.get(ticker)
        quote = platform.market_data.get_quote(ticker)
        price = f"${quote.last:,.2f} ({quote.change_pct:+.2%})" if quote else "price unavailable"
        if matches:
            best = max(matches, key=lambda s: s.score.total)
            return _answer(
                "ticker",
                f"{ticker} - {stock.name}, {price}. "
                f"{labels.get(best.strategy_id, best.strategy_id)} signal at "
                f"{best.confidence}/100, "
                + ("executable." if best.execution.allowed
                   else f"blocked: {best.execution.reason or ''}."),
                ticker=ticker,
                signal=best.model_dump(mode="json"),
            )
        return _answer(
            "ticker",
            f"{ticker} - {stock.name}, {price}. No active signal.",
            ticker=ticker,
        )

    return _answer(
        "unknown",
        "I can answer questions about sector strength, the market regime, current "
        "setups, political disclosures, your best trade, and why a specific ticker "
        "was rejected. Try: \"why did the bot reject NVDA?\"",
        supported=[
            "Which sector is strongest today?",
            "Why is technology outperforming?",
            "What are the best momentum setups?",
            "Show me political purchases in Financials.",
            "What is my highest-confidence trade?",
            "Why did the bot reject NVDA?",
        ],
    )
