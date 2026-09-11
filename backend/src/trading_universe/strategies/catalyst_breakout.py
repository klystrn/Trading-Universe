"""S2 - Fundamental Catalyst Breakout (spec section 10).

Major business developments can trigger institutional repricing. Enter only when
price, sentiment AND volume confirm the catalyst matters. The spec is explicit
about what to reject: a fantastic headline on a terrible balance sheet with no
volume, already extended.
"""

from __future__ import annotations

from trading_universe.domain.enums import CatalystType, StrategyKind
from trading_universe.strategies.base import (
    Strategy,
    StrategyContext,
    StrategyEvaluation,
    StrategyProposal,
)


class FundamentalCatalystBreakout(Strategy):
    id = "fundamental_catalyst_breakout"
    label = "Fundamental Catalyst Breakout"
    kind = StrategyKind.STANDARD

    def evaluate(self, ctx: StrategyContext) -> StrategyEvaluation:
        tech = ctx.technical
        sent = ctx.sentiment
        passed: list[str] = []
        failed: list[str] = []

        if tech.bars_available < 60:
            return self._fail(ctx, ["insufficient history"], passed)

        # --- the catalyst ----------------------------------------------------
        lookback = int(self.cfg("catalyst.lookback_sessions", 5))
        min_strength = float(self.cfg("catalyst.min_catalyst_strength", 0.5))
        accepted = {
            CatalystType(c) for c in self.cfg("catalyst.accepted_types", []) or []
        } or set(CatalystType)

        if sent.catalyst_type is None:
            failed.append("no identified catalyst")
        elif sent.catalyst_type not in accepted:
            failed.append(f"catalyst type {sent.catalyst_type.value} not accepted")
        elif sent.catalyst_sessions_ago is None or sent.catalyst_sessions_ago > lookback:
            failed.append(
                f"catalyst {sent.catalyst_sessions_ago} sessions ago, outside the "
                f"{lookback}-session window"
            )
        elif sent.catalyst_strength < min_strength:
            failed.append(
                f"catalyst strength {sent.catalyst_strength:.2f} < {min_strength:.2f}"
            )
        else:
            passed.append(
                f"{sent.catalyst_type.value} catalyst {sent.catalyst_sessions_ago} "
                f"session(s) ago (strength {sent.catalyst_strength:.2f})"
            )

        # --- technical breakout ----------------------------------------------
        if tech.broke_20d_high:
            passed.append(f"cleared the {self.cfg('technical.breakout_lookback', 20)}-day high")
        else:
            # A successful retest of a recent breakout is an acceptable entry.
            retest_ok = bool(
                self.cfg("technical.allow_retest_entry", True)
                and tech.high_20
                and tech.close >= tech.high_20 * 0.985
                and tech.rsi_turning_up
            )
            if retest_ok:
                passed.append("holding a successful retest of the breakout level")
            else:
                failed.append("no breakout above the 20-day high, and no valid retest")

        min_vol = float(self.cfg("technical.min_volume_ratio", 1.5))
        if tech.volume_ratio >= min_vol:
            passed.append(f"breakout volume {tech.volume_ratio:.2f}x the 20-day average")
        else:
            failed.append(
                f"breakout volume {tech.volume_ratio:.2f}x below the required {min_vol:.2f}x "
                "- the market is not confirming the catalyst"
            )

        # Reject setups that have already run: the move is gone.
        max_ext = float(self.cfg("technical.max_extension_atr", 3.0))
        if tech.atr14 and tech.high_20:
            extension = (tech.close - tech.high_20) / tech.atr14
            if extension <= max_ext:
                passed.append(f"{extension:.1f} ATR above the breakout level")
            else:
                failed.append(
                    f"already {extension:.1f} ATR above the breakout - excessively extended"
                )

        # --- sentiment and fundamentals ---------------------------------------
        s_ok, s_pass, s_fail, s_fit = self.check_sentiment(ctx)
        f_ok, f_pass, f_fail, f_fit = self.check_fundamentals(ctx)
        passed += s_pass + f_pass
        failed += s_fail + f_fail

        if failed:
            return self._fail(ctx, failed, passed)

        entry = ctx.price
        stop = self.place_stop(ctx, method=str(self.cfg("stop.method", "structure")))
        if stop is None or stop >= entry:
            return self._fail(ctx, ["no valid technical invalidation level"], passed)
        target, target_notes = self.build_target(entry, stop, self.resistance_for(ctx))

        return StrategyEvaluation(
            strategy_id=self.id,
            ticker=ctx.ticker,
            setup_present=True,
            passed_checks=passed,
            proposal=StrategyProposal(
                strategy_id=self.id,
                kind=self.kind,
                ticker=ctx.ticker,
                entry=round(entry, 4),
                stop=stop,
                target=target,
                invalidation=f"loss of the breakout level, below {stop:.2f}",
                technical_fit=self._technical_fit(ctx),
                sentiment_fit=s_fit,
                fundamental_fit=f_fit,
                holding_period_days=self.holding_period,
                evidence={
                    "catalyst_type": sent.catalyst_type.value if sent.catalyst_type else None,
                    "catalyst_strength": sent.catalyst_strength,
                    "catalyst_sessions_ago": sent.catalyst_sessions_ago,
                    "broke_20d_high": tech.broke_20d_high,
                    "high_20": tech.high_20,
                    "volume_ratio": tech.volume_ratio,
                    "rsi14": tech.rsi14,
                    "atr14": tech.atr14,
                    **target_notes,
                },
            ),
        )

    def _technical_fit(self, ctx: StrategyContext) -> float:
        tech = ctx.technical
        score = 0.0
        score += 0.30 if tech.broke_20d_high else 0.18
        # Volume is the confirmation that matters most here.
        score += 0.32 * min(1.0, max(0.0, (tech.volume_ratio - 1.0) / 1.5))
        score += 0.12 if tech.price_above_50dma else 0.0
        score += 0.08 if tech.price_above_200dma else 0.0
        # Less extension is better - we want the start of the move.
        if tech.atr14 and tech.high_20:
            extension = (tech.close - tech.high_20) / tech.atr14
            score += 0.18 * max(0.0, 1.0 - extension / 3.0)
        return round(min(1.0, score), 4)
