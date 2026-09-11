"""FreshnessService guarantees and political disclosure handling."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from trading_universe.domain.enums import (
    Chamber,
    FreshnessStatus,
    PoliticalOwner,
    TransactionType,
)
from trading_universe.domain.political import PoliticalTransaction
from trading_universe.features.political import (
    amount_band_score,
    build_political_snapshot,
    fresh_purchase_score,
)


class TestFreshness:
    def test_a_recent_observation_is_live(self, freshness):
        assert freshness.state("quote_active_candidate").status is FreshnessStatus.LIVE

    def test_an_old_observation_is_stale(self, freshness):
        freshness.record(
            "quote_active_candidate", event_time=datetime.now(UTC) - timedelta(minutes=5)
        )
        assert freshness.state("quote_active_candidate").status is FreshnessStatus.STALE

    def test_an_unrecorded_source_is_unavailable_not_fresh(self, freshness):
        freshness.clear()
        state = freshness.state("quote_active_candidate")
        assert state.status is FreshnessStatus.UNAVAILABLE
        assert "no observation" in (state.detail or "")

    def test_degraded_sits_between_healthy_and_stale(self, freshness):
        # warn 3s, max 5s for an active candidate quote.
        freshness.record(
            "quote_active_candidate", event_time=datetime.now(UTC) - timedelta(seconds=4)
        )
        assert freshness.state("quote_active_candidate").status is FreshnessStatus.DEGRADED

    def test_strategy_gating_blocks_on_a_required_source(self, freshness):
        freshness.mark_unavailable("news_sentiment_aggregate", "feed down")
        ok, blockers, _ = freshness.evaluate_strategy("fundamental_catalyst_breakout")
        assert not ok
        assert "news_sentiment_aggregate" in blockers

    def test_strategy_gating_ignores_sources_it_does_not_need(self, freshness):
        """Momentum Pullback does not require the news aggregate, so its loss
        must not disable it (spec section 30)."""
        freshness.mark_unavailable("news_sentiment_aggregate", "feed down")
        freshness.mark_unavailable("news_discovery", "feed down")
        ok, blockers, _ = freshness.evaluate_strategy("quality_momentum_pullback")
        assert ok, blockers

    def test_latency_metrics_are_computable(self, freshness):
        now = datetime.now(UTC)
        freshness.record(
            "sec_filing", event_time=now - timedelta(seconds=30), received_time=now
        )
        latency = freshness.latency("sec_filing")
        assert latency["source_latency"] == 30.0
        assert latency["data_age"] is not None

    def test_unused_sources_do_not_declare_a_system_outage(self, freshness):
        """A configured-but-unused feed going quiet is worth showing, not worth
        reporting as an outage."""
        freshness.clear()
        now = datetime.now(UTC)
        for source in freshness.required_sources():
            freshness.record(source, event_time=now)
        assert freshness.overall_status() in (
            FreshnessStatus.LIVE, FreshnessStatus.HEALTHY, FreshnessStatus.DEGRADED
        )

    def test_a_required_source_going_stale_does_degrade_the_system(self, freshness):
        freshness.record(
            "quote_active_candidate", event_time=datetime.now(UTC) - timedelta(hours=1)
        )
        assert freshness.overall_status() is FreshnessStatus.STALE


def _txn(
    politician: str, ticker: str, disclosure_days_ago: int, lag: int = 20,
    amount: tuple[float, float] = (15001, 50000),
    ttype: TransactionType = TransactionType.PURCHASE,
    chamber: Chamber = Chamber.HOUSE,
    owner: PoliticalOwner = PoliticalOwner.SELF,
    txn_id: str | None = None,
) -> PoliticalTransaction:
    disclosure = date.today() - timedelta(days=disclosure_days_ago)
    return PoliticalTransaction(
        transaction_id=txn_id or f"{politician}-{ticker}-{disclosure_days_ago}-{ttype.value}",
        politician=politician, chamber=chamber, party="D", state="CA", owner=owner,
        ticker=ticker, transaction_type=ttype,
        amount_low=amount[0], amount_high=amount[1],
        transaction_date=disclosure - timedelta(days=lag),
        disclosure_date=disclosure,
        detected_at=datetime.now(UTC),
    )


class TestPoliticalFeatures:
    def test_windows_use_the_disclosure_date_not_the_transaction_date(self):
        """Spec 31: using the transaction date would leak look-ahead information."""
        # Transacted 200 days ago, disclosed yesterday. It IS in the 30-day window.
        txn = _txn("Rep. A", "NVDA", disclosure_days_ago=1, lag=199)
        snapshot = build_political_snapshot("NVDA", [txn])
        assert snapshot.purchases_30d == 1
        assert snapshot.newest_disclosure_age_days == 1.0
        assert snapshot.newest_transaction_lag_days == 199.0

    def test_a_transaction_disclosed_long_ago_falls_out_of_the_window(self):
        txn = _txn("Rep. A", "NVDA", disclosure_days_ago=60, lag=5)
        snapshot = build_political_snapshot("NVDA", [txn])
        assert snapshot.purchases_30d == 0

    def test_member_and_spouse_count_separately(self):
        """Spec 14: track member / spouse separately where possible."""
        txns = [
            _txn("Rep. A", "NVDA", 5, owner=PoliticalOwner.SELF, txn_id="self"),
            _txn("Rep. A", "NVDA", 5, owner=PoliticalOwner.SPOUSE, txn_id="spouse"),
        ]
        snapshot = build_political_snapshot("NVDA", txns)
        assert snapshot.distinct_politicians_30d == 2

    def test_one_politician_buying_repeatedly_is_not_a_consensus(self):
        """Spec 15 is about INDEPENDENT politicians."""
        repeated = [
            _txn("Rep. A", "NVDA", d, txn_id=f"r{d}") for d in (2, 8, 14, 20)
        ]
        independent = [
            _txn(f"Rep. {n}", "NVDA", 5, txn_id=f"i{n}") for n in "ABCD"
        ]
        assert (
            build_political_snapshot("NVDA", repeated).consensus_score
            < build_political_snapshot("NVDA", independent).consensus_score
        )

    def test_chamber_overlap_raises_the_consensus_score(self):
        same = [
            _txn("Rep. A", "NVDA", 5, chamber=Chamber.HOUSE, txn_id="a"),
            _txn("Rep. B", "NVDA", 5, chamber=Chamber.HOUSE, txn_id="b"),
        ]
        mixed = [
            _txn("Rep. A", "NVDA", 5, chamber=Chamber.HOUSE, txn_id="a"),
            _txn("Sen. B", "NVDA", 5, chamber=Chamber.SENATE, txn_id="b"),
        ]
        assert (
            build_political_snapshot("NVDA", mixed).consensus_score
            > build_political_snapshot("NVDA", same).consensus_score
        )

    def test_sales_reduce_the_consensus_score(self):
        buys = [_txn(f"Rep. {n}", "NVDA", 5, txn_id=f"b{n}") for n in "ABC"]
        with_sale = buys + [
            _txn("Rep. D", "NVDA", 3, ttype=TransactionType.SALE, txn_id="sale")
        ]
        assert (
            build_political_snapshot("NVDA", with_sale).consensus_score
            < build_political_snapshot("NVDA", buys).consensus_score
        )

    def test_recency_decays_the_score(self):
        recent = build_political_snapshot("NVDA", [_txn("Rep. A", "NVDA", 1)])
        old = build_political_snapshot("NVDA", [_txn("Rep. A", "NVDA", 28)])
        assert recent.freshness_score > old.freshness_score

    def test_larger_disclosed_bands_score_higher(self):
        assert amount_band_score(500_000) > amount_band_score(50_000)
        assert amount_band_score(50_000) > amount_band_score(1_500)

    def test_repeat_buyer_requires_no_sales(self):
        purchases = [_txn("Rep. A", "NVDA", d, txn_id=f"p{d}") for d in (10, 40, 70)]
        with_sale = purchases + [
            _txn("Rep. A", "NVDA", 5, ttype=TransactionType.SALE, txn_id="s")
        ]
        assert (
            build_political_snapshot("NVDA", with_sale).repeat_score
            < build_political_snapshot("NVDA", purchases).repeat_score
        )

    def test_fresh_purchase_score_respects_the_age_limit(self):
        inside = build_political_snapshot("NVDA", [_txn("Rep. A", "NVDA", 5)])
        outside = build_political_snapshot("NVDA", [_txn("Rep. A", "NVDA", 25)])
        assert fresh_purchase_score(inside, max_age_days=21) > 0
        assert fresh_purchase_score(outside, max_age_days=21) == 0.0

    def test_disclosure_lag_is_reported(self):
        txn = _txn("Rep. A", "NVDA", disclosure_days_ago=3, lag=25)
        assert txn.disclosure_lag_days == 25

    def test_empty_history_is_a_neutral_snapshot_not_a_crash(self):
        snapshot = build_political_snapshot("NVDA", [])
        assert snapshot.purchases_30d == 0
        assert snapshot.consensus_score == 0.0
        assert snapshot.repeat_score == 0.0


class TestDisclosureParsing:
    def test_a_row_without_a_disclosure_date_is_skipped_not_guessed(self):
        from trading_universe.data.disclosures import HouseDisclosureClient

        rows = [
            {
                "representative": "Rep. A", "ticker": "NVDA", "type": "P",
                "amount": "$15,001 - $50,000", "transaction_date": "01/15/2026",
            }
        ]
        assert HouseDisclosureClient().parse_rows(rows) == []

    def test_ticker_is_extracted_from_the_asset_description(self):
        from trading_universe.data.disclosures import extract_ticker

        assert extract_ticker("NVIDIA Corporation (NVDA) Common Stock") == "NVDA"
        assert extract_ticker("Some Municipal Bond Fund") is None

    def test_amount_bands_parse_to_ranges(self):
        from trading_universe.data.disclosures import parse_amount_band

        assert parse_amount_band("$15,001 - $50,000") == (15001, 50000)
        assert parse_amount_band(None) == (0.0, 0.0)
