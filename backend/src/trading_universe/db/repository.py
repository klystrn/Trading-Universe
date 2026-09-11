"""Persistence helpers: domain objects in, rows out."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from trading_universe.db.models import (
    DailyRecommendationRow,
    OrderRow,
    PoliticalTransactionRow,
    ScanRunRow,
    SignalRow,
    ThesisRow,
    TradeRow,
    WatchlistRow,
)
from trading_universe.db.session import session_scope
from trading_universe.domain.political import PoliticalTransaction
from trading_universe.domain.portfolio import Order, Trade
from trading_universe.domain.regime import StrategyRecommendation
from trading_universe.domain.signals import Signal
from trading_universe.domain.thesis import TradeThesis


class Repository:
    """All database access goes through here so the rest of the app stays
    ignorant of SQLAlchemy."""

    # -- signals ------------------------------------------------------------
    def save_signal(self, signal: Signal) -> None:
        row = SignalRow(
            signal_id=signal.signal_id,
            ticker=signal.ticker,
            strategy_id=signal.strategy_id,
            strategy_kind=signal.strategy_kind.value,
            sector=signal.sector,
            subsector=signal.subsector,
            direction=signal.direction.value,
            generated_at=signal.generated_at,
            trading_day=signal.generated_at.date(),
            score_total=signal.score.total,
            score_technical=signal.score.technical,
            score_sentiment=signal.score.sentiment,
            score_fundamental=signal.score.fundamental,
            score_political=signal.score.political,
            entry=signal.trade.entry,
            stop=signal.trade.stop,
            target=signal.trade.target,
            reward_risk=signal.trade.reward_risk,
            market_regime=signal.market.regime.value,
            sector_regime=signal.market.sector_regime.value,
            strategy_match=signal.market.strategy_match,
            allowed=signal.execution.allowed,
            rejection_reasons=[r.value for r in signal.execution.reasons],
            quantity=signal.execution.quantity,
            position_value=signal.execution.position_value,
            freshness=signal.freshness.model_dump(mode="json"),
            evidence=_jsonable(signal.evidence),
            invalidation=signal.invalidation,
        )
        with session_scope() as session:
            session.merge(row)

    def save_signals(self, signals: list[Signal]) -> int:
        for signal in signals:
            self.save_signal(signal)
        return len(signals)

    def recent_signals(
        self,
        limit: int = 100,
        strategy_id: str | None = None,
        allowed_only: bool = False,
        min_score: float | None = None,
        trading_day: date | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(SignalRow).order_by(SignalRow.generated_at.desc())
        if strategy_id:
            stmt = stmt.where(SignalRow.strategy_id == strategy_id)
        if allowed_only:
            stmt = stmt.where(SignalRow.allowed.is_(True))
        if min_score is not None:
            stmt = stmt.where(SignalRow.score_total >= min_score)
        if trading_day:
            stmt = stmt.where(SignalRow.trading_day == trading_day)
        with session_scope() as session:
            return [_row_to_dict(r) for r in session.scalars(stmt.limit(limit)).all()]

    def rejected_signals(self, limit: int = 200) -> list[dict[str, Any]]:
        stmt = (
            select(SignalRow)
            .where(SignalRow.allowed.is_(False))
            .order_by(SignalRow.generated_at.desc())
            .limit(limit)
        )
        with session_scope() as session:
            return [_row_to_dict(r) for r in session.scalars(stmt).all()]

    # -- theses --------------------------------------------------------------
    def save_thesis(self, thesis: TradeThesis) -> None:
        row = ThesisRow(
            trade_id=thesis.trade_id,
            signal_id=thesis.signal_id,
            ticker=thesis.ticker,
            strategy=thesis.strategy,
            accepted=thesis.accepted,
            generated_at=thesis.generated_at,
            payload=thesis.model_dump(mode="json"),
        )
        with session_scope() as session:
            session.merge(row)

    def get_thesis(self, trade_id: str) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.get(ThesisRow, trade_id)
            return row.payload if row else None

    def thesis_for_signal(self, signal_id: str) -> dict[str, Any] | None:
        stmt = select(ThesisRow).where(ThesisRow.signal_id == signal_id).limit(1)
        with session_scope() as session:
            row = session.scalars(stmt).first()
            return row.payload if row else None

    # -- orders and trades -----------------------------------------------------
    def save_order(self, order: Order) -> None:
        row = OrderRow(
            order_id=order.order_id,
            broker_order_id=order.broker_order_id,
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            side=order.side.value,
            order_type=order.order_type.value,
            quantity=order.quantity,
            limit_price=order.limit_price,
            stop_price=order.stop_price,
            status=order.status.value,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
            signal_id=order.signal_id,
            strategy_id=order.strategy_id,
            operating_mode=order.operating_mode.value,
            execution_source=order.execution_source.value,
            paper=order.paper,
            created_at=order.created_at,
            submitted_at=order.submitted_at,
            filled_at=order.filled_at,
            rejection_reason=order.rejection_reason,
        )
        with session_scope() as session:
            session.merge(row)

    def save_trade(self, trade: Trade, sector: str = "", regime: str | None = None) -> None:
        row = TradeRow(
            trade_id=trade.trade_id,
            ticker=trade.ticker,
            strategy_id=trade.strategy_id,
            sector=sector or trade.sector,
            entry=trade.entry,
            stop=trade.stop,
            target=trade.target,
            quantity=trade.quantity,
            exit_price=trade.exit_price,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            exit_reason=trade.exit_reason,
            operating_mode=trade.operating_mode.value,
            execution_source=trade.execution_source.value,
            paper=trade.paper,
            was_recommended_strategy=trade.was_recommended_strategy,
            signal_id=trade.signal_id,
            thesis_id=trade.thesis_id,
            result=trade.result.value,
            realized_pnl=trade.realized_pnl,
            r_multiple=trade.r_multiple,
            market_regime=regime,
        )
        with session_scope() as session:
            session.merge(row)

    def list_trades(
        self,
        limit: int = 200,
        strategy_id: str | None = None,
        ticker: str | None = None,
        sector: str | None = None,
        result: str | None = None,
        paper: bool | None = None,
        execution_source: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(TradeRow).order_by(TradeRow.opened_at.desc())
        if strategy_id:
            stmt = stmt.where(TradeRow.strategy_id == strategy_id)
        if ticker:
            stmt = stmt.where(TradeRow.ticker == ticker.upper())
        if sector:
            stmt = stmt.where(TradeRow.sector == sector)
        if result:
            stmt = stmt.where(TradeRow.result == result)
        if paper is not None:
            stmt = stmt.where(TradeRow.paper.is_(paper))
        if execution_source:
            stmt = stmt.where(TradeRow.execution_source == execution_source)
        if since:
            stmt = stmt.where(TradeRow.opened_at >= since)
        with session_scope() as session:
            return [_row_to_dict(r) for r in session.scalars(stmt.limit(limit)).all()]

    def list_orders(self, limit: int = 200) -> list[dict[str, Any]]:
        stmt = select(OrderRow).order_by(OrderRow.created_at.desc()).limit(limit)
        with session_scope() as session:
            return [_row_to_dict(r) for r in session.scalars(stmt).all()]

    # -- recommendations --------------------------------------------------------
    def save_recommendation(self, rec: StrategyRecommendation) -> None:
        row = DailyRecommendationRow(
            trading_day=rec.trading_day,
            generated_at=rec.generated_at,
            primary_strategy=rec.primary_strategy,
            confidence=rec.confidence,
            market_regime=rec.market_regime.value,
            rationale=rec.rationale,
            sector_recommendations=[s.model_dump(mode="json") for s in rec.sector_recommendations],
            alternatives=[list(a) for a in rec.alternatives],
            accepted=rec.accepted,
            active_strategy=rec.active_strategy,
            overridden=rec.overridden,
        )
        with session_scope() as session:
            session.merge(row)

    def get_recommendation(self, trading_day: date) -> dict[str, Any] | None:
        with session_scope() as session:
            row = session.get(DailyRecommendationRow, trading_day)
            return _row_to_dict(row) if row else None

    def recommendation_history(self, days: int = 60) -> list[dict[str, Any]]:
        cutoff = date.today() - timedelta(days=days)
        stmt = (
            select(DailyRecommendationRow)
            .where(DailyRecommendationRow.trading_day >= cutoff)
            .order_by(DailyRecommendationRow.trading_day.desc())
        )
        with session_scope() as session:
            return [_row_to_dict(r) for r in session.scalars(stmt).all()]

    # -- political ----------------------------------------------------------------
    def save_political(self, transactions: list[PoliticalTransaction]) -> int:
        with session_scope() as session:
            for txn in transactions:
                session.merge(
                    PoliticalTransactionRow(
                        transaction_id=txn.transaction_id,
                        politician=txn.politician,
                        chamber=txn.chamber.value,
                        party=txn.party,
                        state=txn.state,
                        owner=txn.owner.value,
                        ticker=txn.ticker,
                        asset_description=txn.asset_description,
                        transaction_type=txn.transaction_type.value,
                        amount_low=txn.amount_low,
                        amount_high=txn.amount_high,
                        transaction_date=txn.transaction_date,
                        disclosure_date=txn.disclosure_date,
                        detected_at=txn.detected_at,
                        source_url=txn.source_url,
                    )
                )
        return len(transactions)

    def list_political(
        self,
        limit: int = 300,
        ticker: str | None = None,
        politician: str | None = None,
        chamber: str | None = None,
        party: str | None = None,
        state: str | None = None,
        transaction_type: str | None = None,
        min_amount: float | None = None,
        disclosed_since: date | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(PoliticalTransactionRow).order_by(
            PoliticalTransactionRow.disclosure_date.desc()
        )
        if ticker:
            stmt = stmt.where(PoliticalTransactionRow.ticker == ticker.upper())
        if politician:
            stmt = stmt.where(PoliticalTransactionRow.politician.ilike(f"%{politician}%"))
        if chamber:
            stmt = stmt.where(PoliticalTransactionRow.chamber == chamber.upper())
        if party:
            stmt = stmt.where(PoliticalTransactionRow.party == party)
        if state:
            stmt = stmt.where(PoliticalTransactionRow.state == state)
        if transaction_type:
            stmt = stmt.where(
                PoliticalTransactionRow.transaction_type == transaction_type.upper()
            )
        if min_amount is not None:
            stmt = stmt.where(PoliticalTransactionRow.amount_high >= min_amount)
        if disclosed_since:
            stmt = stmt.where(PoliticalTransactionRow.disclosure_date >= disclosed_since)
        with session_scope() as session:
            return [_row_to_dict(r) for r in session.scalars(stmt.limit(limit)).all()]

    def load_political_domain(self, days: int = 365) -> list[PoliticalTransaction]:
        cutoff = date.today() - timedelta(days=days)
        stmt = select(PoliticalTransactionRow).where(
            PoliticalTransactionRow.disclosure_date >= cutoff
        )
        with session_scope() as session:
            rows = session.scalars(stmt).all()
        return [
            PoliticalTransaction(
                transaction_id=r.transaction_id,
                politician=r.politician,
                chamber=r.chamber,  # type: ignore[arg-type]
                party=r.party,
                state=r.state,
                owner=r.owner,  # type: ignore[arg-type]
                ticker=r.ticker,
                asset_description=r.asset_description,
                transaction_type=r.transaction_type,  # type: ignore[arg-type]
                amount_low=r.amount_low,
                amount_high=r.amount_high,
                transaction_date=r.transaction_date,
                disclosure_date=r.disclosure_date,
                detected_at=r.detected_at,
                source_url=r.source_url,
            )
            for r in rows
        ]

    def political_summary(self) -> dict[str, Any]:
        with session_scope() as session:
            total = session.scalar(select(func.count()).select_from(PoliticalTransactionRow)) or 0
            newest = session.scalar(
                select(func.max(PoliticalTransactionRow.disclosure_date))
            )
            politicians = session.scalar(
                select(func.count(func.distinct(PoliticalTransactionRow.politician)))
            ) or 0
        return {
            "transactions": total,
            "politicians": politicians,
            "newest_disclosure": newest.isoformat() if newest else None,
        }

    # -- watchlist ------------------------------------------------------------------
    def watchlist(self) -> list[dict[str, Any]]:
        with session_scope() as session:
            rows = session.scalars(select(WatchlistRow).order_by(WatchlistRow.added_at)).all()
            return [_row_to_dict(r) for r in rows]

    def watchlist_tickers(self) -> list[str]:
        with session_scope() as session:
            return list(session.scalars(select(WatchlistRow.ticker)).all())

    def add_watchlist(
        self, ticker: str, note: str | None = None, pinned: bool = False,
        alert_above: float | None = None, alert_below: float | None = None,
    ) -> None:
        with session_scope() as session:
            session.merge(
                WatchlistRow(
                    ticker=ticker.upper(), note=note, pinned=pinned,
                    alert_above=alert_above, alert_below=alert_below,
                    added_at=datetime.now(UTC),
                )
            )

    def remove_watchlist(self, ticker: str) -> None:
        with session_scope() as session:
            session.execute(delete(WatchlistRow).where(WatchlistRow.ticker == ticker.upper()))

    # -- scan runs ---------------------------------------------------------------------
    def start_scan(self, started_at: datetime) -> int:
        with session_scope() as session:
            row = ScanRunRow(started_at=started_at)
            session.add(row)
            session.flush()
            return row.id

    def finish_scan(
        self, scan_id: int, finished_at: datetime, tickers: int, signals: int,
        executable: int, rejected: int, regime: str | None, error: str | None = None,
    ) -> None:
        with session_scope() as session:
            row = session.get(ScanRunRow, scan_id)
            if row is None:
                return
            row.finished_at = finished_at
            row.tickers_scanned = tickers
            row.signals_found = signals
            row.executable = executable
            row.rejected = rejected
            row.market_regime = regime
            row.error = error

    def last_scan(self) -> dict[str, Any] | None:
        stmt = (
            select(ScanRunRow)
            .where(ScanRunRow.finished_at.is_not(None))
            .order_by(ScanRunRow.finished_at.desc())
            .limit(1)
        )
        with session_scope() as session:
            row = session.scalars(stmt).first()
            return _row_to_dict(row) if row else None


def _row_to_dict(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, datetime | date):
            value = value.isoformat()
        out[column.name] = value
    return out


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce evidence values into JSON-safe primitives."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, datetime | date):
            out[key] = value.isoformat()
        elif isinstance(value, dict | list | str | int | float | bool) or value is None:
            out[key] = value
        else:
            out[key] = str(value)
    return out
