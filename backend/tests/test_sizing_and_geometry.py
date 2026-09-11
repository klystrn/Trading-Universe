"""Position sizing and reward/risk geometry (spec sections 19, 20)."""

from __future__ import annotations

import pytest

from trading_universe.domain.signals import TradeParams
from trading_universe.execution.sizing import size_position


class TestSizing:
    def test_spec_example_whole_shares(self):
        """Spec 19: max $150, entry $50 -> 3 shares."""
        result = size_position(50.0, 48.0, 150.0, allow_fractional=True)
        assert result.quantity == 3.0
        assert result.position_value == 150.0
        assert result.risk_amount == 6.0

    def test_spec_example_fractional(self):
        """Spec 19: max $150, entry $212 -> about 0.7075 shares."""
        result = size_position(212.0, 205.0, 150.0, allow_fractional=True)
        assert result.quantity == pytest.approx(0.7075, abs=1e-4)
        assert result.fractional_used is True
        assert result.position_value <= 150.0

    def test_never_exceeds_the_capital_cap(self):
        for entry in (7.77, 33.33, 101.01, 249.99, 512.5):
            result = size_position(entry, entry * 0.95, 150.0, allow_fractional=True)
            assert result.position_value <= 150.0, entry

    def test_whole_share_flooring_stays_under_the_cap(self):
        result = size_position(60.0, 57.0, 150.0, allow_fractional=False)
        assert result.quantity == 2.0
        assert result.position_value == 120.0
        assert "floored" in (result.note or "")

    def test_unaffordable_without_fractional_shares(self):
        result = size_position(212.0, 205.0, 150.0, allow_fractional=False)
        assert not result.viable
        assert "fractional shares are disabled" in (result.note or "")

    def test_rejects_a_stop_above_entry(self):
        result = size_position(50.0, 51.0, 150.0, allow_fractional=True)
        assert not result.viable

    def test_max_position_value_is_capital_not_loss(self):
        """The $150 cap limits deployed capital; risk is far smaller."""
        result = size_position(50.0, 48.0, 150.0, allow_fractional=True)
        assert result.position_value == 150.0
        assert result.risk_amount == 6.0
        assert result.risk_amount < result.position_value


class TestTradeGeometry:
    def test_minimum_target_matches_the_spec_worked_example(self):
        """Spec 20: entry 50, stop 48 -> risk 2 -> minimum target 53.50."""
        params = TradeParams(entry=50.0, stop=48.0, target=53.50)
        assert params.risk_per_share == 2.0
        assert params.reward_risk == 1.75
        assert params.minimum_target(1.75) == 53.50

    def test_reward_risk_computation(self):
        params = TradeParams(entry=100.0, stop=96.0, target=110.0)
        assert params.risk_per_share == 4.0
        assert params.reward_risk == 2.5

    def test_rejects_inverted_long_geometry(self):
        with pytest.raises(ValueError, match="stop"):
            TradeParams(entry=100.0, stop=101.0, target=110.0)
        with pytest.raises(ValueError, match="target"):
            TradeParams(entry=100.0, stop=96.0, target=99.0)
