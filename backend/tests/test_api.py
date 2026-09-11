"""End-to-end API tests against a fully bootstrapped demo platform."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_db():
    """Override conftest's per-test database isolation.

    These tests share one bootstrapped app for the whole module (the first scan
    costs seconds), so repointing the engine between tests would leave the
    running platform talking to a database that no longer has its tables.
    """
    yield


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """One bootstrapped app for the module - the first scan costs seconds."""
    import os

    db = tmp_path_factory.mktemp("api") / "api.sqlite"
    os.environ["TU_DATABASE_URL"] = f"sqlite:///{db}"
    os.environ["TU_DATA_MODE"] = "DEMO"

    from fastapi.testclient import TestClient

    from trading_universe.db.session import reset_engine
    from trading_universe.services.platform import reset_platform
    from trading_universe.settings import reload_settings

    reload_settings()
    reset_engine()
    reset_platform()

    from trading_universe.api.app import create_app

    with TestClient(create_app()) as c:
        yield c
    reset_platform()


class TestSystem:
    def test_health_reports_every_source(self, client):
        body = client.get("/api/system/health").json()
        assert body["overall"]
        names = {s["name"] for s in body["sources"]}
        assert {"SEC", "GDELT", "MARKETAUX", "CONGRESS"} <= names
        assert body["strategy_gates"]

    def test_status_shows_the_safety_state(self, client):
        body = client.get("/api/system/status").json()
        assert body["trading_env"] == "PAPER"
        assert body["allow_real_orders"] is False
        assert body["execution"] in ("ADVISORY", "PAPER_AUTO", "LIVE_AUTO")

    def test_freshness_exposes_per_strategy_gates(self, client):
        body = client.get("/api/system/freshness").json()
        assert len(body["sources"]) > 5
        assert len(body["strategy_gates"]) == 8

    def test_kill_switch_round_trip(self, client):
        assert client.post("/api/system/kill-switch", params={"engage": True}).json()[
            "kill_switch_engaged"
        ]
        scan = client.post("/api/system/scan", params={"execute": True}).json()
        assert scan["executable"] == 0
        assert scan["orders_placed"] == 0
        client.post("/api/system/kill-switch", params={"engage": False})

    def test_live_mode_reports_its_blocking_gates(self, client):
        body = client.post("/api/system/mode", params={"mode": "LIVE_AUTO"}).json()
        assert body["live_gates"]["permitted"] is False
        assert len(body["live_gates"]["blocking"]) >= 2
        client.post("/api/system/mode", params={"mode": "ADVISORY"})

    def test_an_unknown_mode_is_rejected(self, client):
        assert client.post("/api/system/mode", params={"mode": "YOLO"}).status_code == 400


class TestUniverse:
    def test_payload_is_compact_and_complete(self, client):
        body = client.get("/api/universe").json()
        assert len(body["entities"]) > 400
        assert len(body["sectors"]) == 11
        assert body["subsectors"]

        entity = body["entities"][0]
        # Spec 77: a lean visualization payload, not every financial metric.
        assert set(entity) <= {
            "id", "type", "name", "sector", "subsector", "position", "size",
            "orbit_speed", "intensity", "price_change", "volume_ratio", "price",
            "live", "watchlist", "signal", "portfolio", "political",
        }
        assert len(entity["position"]) == 3
        assert 0.0 <= entity["intensity"] <= 1.0
        assert entity["orbit_speed"] > 0

    def test_flows_are_labelled_as_inferred(self, client):
        """Spec 51: never imply real capital-flow data we do not have."""
        for flow in client.get("/api/universe").json()["flows"]:
            assert flow["inferred"] is True
            assert "not observed capital flow" in flow["basis"]

    def test_sizes_are_log_scaled(self, client):
        entities = client.get("/api/universe").json()["entities"]
        sizes = [e["size"] for e in entities]
        # A mega-cap must not dwarf the universe (spec 49).
        assert max(sizes) / min(sizes) < 12

    def test_stock_detail(self, client):
        body = client.get("/api/universe/stock/NVDA").json()
        assert body["stock"]["ticker"] == "NVDA"
        assert body["technical"] is not None
        assert body["fundamental"] is not None
        assert "signals" in body

    def test_unknown_ticker_is_404(self, client):
        assert client.get("/api/universe/stock/ZZZZ").status_code == 404

    def test_candles_include_overlays_for_the_chart(self, client):
        body = client.get("/api/universe/candles/NVDA").json()
        assert len(body["candles"]) > 200
        assert {"time", "open", "high", "low", "close", "volume"} <= set(body["candles"][0])
        assert "ema20" in body["overlays"]
        assert "dma200" in body["overlays"]

    def test_briefing(self, client):
        body = client.get("/api/universe/briefing").json()
        assert body["market_regime"]
        assert "strongest_sectors" in body
        assert "portfolio" in body


class TestSignalsAndStrategy:
    def test_signals_are_returned_with_scores(self, client):
        body = client.get("/api/signals").json()
        assert body["count"] >= 0
        if body["signals"]:
            signal = body["signals"][0]
            assert signal["score"]["total"] <= 100
            assert signal["trade"]["reward_risk"] >= 1.75
            assert "execution" in signal

    def test_signals_can_be_filtered(self, client):
        body = client.get(
            "/api/signals", params={"strategy": "quality_momentum_pullback"}
        ).json()
        assert all(
            s["strategy_id"] == "quality_momentum_pullback" for s in body["signals"]
        )

    def test_rejected_signals_are_retained_with_reasons(self, client):
        body = client.get("/api/signals/rejected").json()
        for signal in body["signals"]:
            assert signal["allowed"] is False
            assert signal["rejection_reasons"]

    def test_all_eight_strategies_are_listed(self, client):
        body = client.get("/api/strategy").json()
        assert len(body["strategies"]) == 8
        assert all("gate" in s for s in body["strategies"])

    def test_recommendation_is_explainable(self, client):
        body = client.get("/api/strategy/recommendation").json()
        assert body["primary_strategy"]
        assert body["rationale"], "a recommendation with no reasons is not explainable"
        assert 0.0 <= body["confidence"] <= 1.0
        assert body["sector_recommendations"]

    def test_manual_override_is_honoured(self, client):
        """Spec 6: the user must retain the ability to override."""
        body = client.post(
            "/api/strategy/override", json={"strategy_id": "quality_oversold_reversal"}
        ).json()
        assert body["active_strategy"] == "quality_oversold_reversal"
        assert client.get("/api/strategy").json()["active_strategy"] == (
            "quality_oversold_reversal"
        )

    def test_other_strategies_keep_scanning_while_one_is_active(self, client):
        """Spec 67: only the active strategy executes; the rest keep scanning."""
        client.post("/api/strategy/override", json={"strategy_id": "congress_consensus"})
        client.post("/api/system/scan", params={"execute": False})
        signals = client.get("/api/signals").json()["signals"]
        strategies = {s["strategy_id"] for s in signals}
        assert len(strategies) > 1, "other strategies stopped producing signals"

    def test_no_trade_is_a_valid_choice(self, client):
        """Spec 2: the bot should never feel required to trade."""
        body = client.post("/api/strategy/override", json={"strategy_id": "NO_TRADE"}).json()
        assert body["active_strategy"] is None

    def test_unknown_strategy_is_rejected(self, client):
        assert client.post(
            "/api/strategy/override", json={"strategy_id": "made_up"}
        ).status_code == 400


class TestConfig:
    def test_risk_config_is_readable(self, client):
        body = client.get("/api/config/risk").json()
        assert body["minimum_reward_risk"] == 1.75
        assert body["max_position_value"] == 150.0
        assert body["max_new_trades_per_day"] == 3
        assert body["max_open_positions"] == 5

    def test_sliders_can_change_risk_settings(self, client):
        body = client.patch(
            "/api/config/risk", json={"max_position_value": 250.0}
        ).json()
        assert body["risk"]["max_position_value"] == 250.0
        client.patch("/api/config/risk", json={"max_position_value": 150.0})

    def test_out_of_range_values_are_refused(self, client):
        """A slider must not be able to set an absurd limit."""
        assert client.patch(
            "/api/config/risk", json={"max_position_value": 1e12}
        ).status_code == 400
        assert client.patch(
            "/api/config/risk", json={"minimum_reward_risk": 0.1}
        ).status_code == 400

    def test_strategy_parameters_can_be_tuned(self, client):
        body = client.patch(
            "/api/config/strategies/quality_momentum_pullback",
            json={"rsi.min": 35.0},
        ).json()
        assert body["config"]["rsi"]["min"] == 35.0
        client.patch(
            "/api/config/strategies/quality_momentum_pullback", json={"rsi.min": 40.0}
        )


class TestWatchlistAndSearch:
    def test_watchlist_round_trip(self, client):
        client.post("/api/watchlist", json={"ticker": "NVDA", "note": "semis"})
        body = client.get("/api/watchlist").json()
        assert any(w["ticker"] == "NVDA" for w in body["watchlist"])
        # Spec 69: priority, never a score bonus.
        assert "never a score bonus" in body["note"]
        client.delete("/api/watchlist/NVDA")
        assert not client.get("/api/watchlist").json()["watchlist"]

    def test_watchlist_rejects_tickers_outside_the_universe(self, client):
        assert client.post("/api/watchlist", json={"ticker": "ZZZZ"}).status_code == 404

    def test_entity_search_prefers_exact_tickers(self, client):
        results = client.get("/api/search", params={"q": "nvda"}).json()["results"]
        assert results[0]["id"] == "NVDA"
        assert results[0]["type"] == "stock"

    def test_search_matches_sectors_and_names(self, client):
        assert any(
            r["type"] == "sector"
            for r in client.get("/api/search", params={"q": "financ"}).json()["results"]
        )
        assert any(
            r["id"] == "AAPL"
            for r in client.get("/api/search", params={"q": "apple"}).json()["results"]
        )

    @pytest.mark.parametrize(
        "question,intent",
        [
            ("Which sector is strongest today?", "sector_strength"),
            ("What is my highest-confidence trade?", "best_trade"),
            ("Show me political purchases in Financials", "political"),
            ("Why did the bot reject NVDA?", "rejection"),
            ("What are the best momentum setups?", "setups"),
            ("How is the market doing?", "regime"),
        ],
    )
    def test_market_questions_are_answered(self, client, question, intent):
        body = client.get("/api/search/ask", params={"q": question}).json()
        assert body["intent"] == intent, body
        assert body["answer"]

    def test_an_unrecognised_question_says_so(self, client):
        """Better to admit the limit than to improvise a plausible number."""
        body = client.get(
            "/api/search/ask", params={"q": "what will happen to gold next quarter"}
        ).json()
        assert body["intent"] == "unknown"
        assert body["supported"]


class TestPortfolioAndAnalytics:
    def test_portfolio_reports_capacity(self, client):
        body = client.get("/api/portfolio").json()
        assert "remaining_position_slots" in body
        assert "sector_exposure" in body
        assert body["paper"] is True

    def test_capacity_endpoint(self, client):
        body = client.get("/api/portfolio/capacity").json()
        assert body["max_position_value"] == 150.0
        assert body["max_open_positions"] == 5

    def test_analytics_handle_an_empty_history(self, client):
        body = client.get("/api/analytics/performance").json()
        assert body["overall"]["trades"] >= 0
        assert "by_strategy" in body

    def test_rejection_analytics_explain_the_thresholds(self, client):
        body = client.get("/api/analytics/rejected").json()
        assert "breakdown" in body
        assert "threshold_analysis" in body
        assert "measured=0" in body["note"]

    def test_political_summary_states_the_disclosure_caveat(self, client):
        body = client.get("/api/political/summary").json()
        assert "DISCLOSURE date" in body["note"]


class TestAssistantIntents:
    @pytest.mark.parametrize(
        "question,intent,panel",
        [
            ("Give me the briefing", "briefing", "signals"),
            ("How is my portfolio?", "portfolio", "portfolio"),
            ("How many trades can I open?", "capacity", "portfolio"),
            ("What strategy is active?", "strategy", "parameters"),
            ("Can you execute right now?", "health", "system"),
        ],
    )
    def test_assistant_intents_answer_and_summon_a_panel(self, client, question, intent, panel):
        body = client.get("/api/search/ask", params={"q": question}).json()
        assert body["intent"] == intent, body
        assert body["panel"] == panel
        assert body["answer"]

    def test_every_answer_carries_a_short_spoken_form(self, client):
        for q in ("Which sector is strongest today?", "Give me the briefing", "what is gold doing"):
            body = client.get("/api/search/ask", params={"q": q}).json()
            assert body["speech"]
            assert len(body["speech"]) <= 260
