"""
Tests de los schemas de validación de datos internos.

Qué verificamos:
1. Los schemas aceptan datos válidos.
2. Los schemas rechazan datos inválidos con errores claros.
3. Las propiedades calculadas (pnl, return_pct) son correctas.
4. Los enums tienen los valores esperados.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from config.schemas import (
    OHLCV,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Signal,
    SignalStrength,
    Trade,
)


class TestOHLCV:
    def test_valid_ohlcv(self):
        bar = OHLCV(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=150.0,
            high=155.0,
            low=149.0,
            close=153.0,
            volume=5_000_000.0,
        )
        assert bar.symbol == "AAPL"
        assert bar.close == 153.0

    def test_negative_price_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            OHLCV(
                symbol="AAPL",
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                open=-1.0,
                high=155.0,
                low=149.0,
                close=153.0,
                volume=5_000_000.0,
            )
        assert "positivo" in str(exc_info.value).lower()

    def test_zero_price_raises(self):
        with pytest.raises(ValidationError):
            OHLCV(
                symbol="AAPL",
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                open=0.0,
                high=155.0,
                low=149.0,
                close=153.0,
                volume=5_000_000.0,
            )

    def test_negative_volume_raises(self):
        with pytest.raises(ValidationError):
            OHLCV(
                symbol="AAPL",
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                open=150.0,
                high=155.0,
                low=149.0,
                close=153.0,
                volume=-1.0,
            )

    def test_zero_volume_is_allowed(self):
        bar = OHLCV(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=150.0,
            high=155.0,
            low=149.0,
            close=153.0,
            volume=0.0,
        )
        assert bar.volume == 0.0


class TestSignal:
    def test_valid_signal(self):
        sig = Signal(
            strategy_id="sma_crossover_v1",
            symbol="AAPL",
            side=OrderSide.BUY,
            confidence=0.75,
            generated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert sig.confidence == 0.75
        assert sig.strength == SignalStrength.MODERATE  # default

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            Signal(
                strategy_id="test",
                symbol="AAPL",
                side=OrderSide.BUY,
                confidence=1.5,  # > 1.0
                generated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )


class TestTrade:
    def _make_trade(self, entry=100.0, exit=110.0, quantity=10.0, commission=1.0):
        return Trade(
            trade_id="t001",
            strategy_id="sma_v1",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=quantity,
            entry_price=entry,
            exit_price=exit,
            entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            exit_time=datetime(2024, 1, 5, tzinfo=timezone.utc),
            commission=commission,
        )

    def test_gross_pnl_long(self):
        trade = self._make_trade(entry=100.0, exit=110.0, quantity=10.0)
        assert trade.gross_pnl == pytest.approx(100.0)  # (110-100)*10

    def test_net_pnl_deducts_commission(self):
        trade = self._make_trade(entry=100.0, exit=110.0, quantity=10.0, commission=5.0)
        assert trade.net_pnl == pytest.approx(95.0)  # 100 - 5

    def test_return_pct(self):
        trade = self._make_trade(entry=100.0, exit=110.0)
        assert trade.return_pct == pytest.approx(0.10)  # 10%

    def test_negative_pnl_on_losing_trade(self):
        trade = self._make_trade(entry=100.0, exit=90.0, quantity=10.0, commission=0.0)
        assert trade.gross_pnl == pytest.approx(-100.0)

    def test_net_pnl_worse_than_gross(self):
        trade = self._make_trade(entry=100.0, exit=110.0, quantity=10.0, commission=5.0)
        assert trade.net_pnl < trade.gross_pnl


class TestPosition:
    def test_unrealized_pnl_positive(self):
        pos = Position(
            symbol="AAPL",
            quantity=10.0,
            entry_price=100.0,
            current_price=115.0,
            strategy_id="test",
            opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert pos.unrealized_pnl == pytest.approx(150.0)
        assert pos.unrealized_pnl_pct == pytest.approx(0.15)

    def test_unrealized_pnl_negative(self):
        pos = Position(
            symbol="AAPL",
            quantity=10.0,
            entry_price=100.0,
            current_price=90.0,
            strategy_id="test",
            opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        assert pos.unrealized_pnl == pytest.approx(-100.0)
