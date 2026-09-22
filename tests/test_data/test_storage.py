"""
Tests del sistema de almacenamiento.

Usamos SQLite en memoria (:memory:) para que los tests sean:
- Rápidos: sin I/O de disco
- Aislados: cada test tiene su propia DB limpia
- Sin efectos secundarios: no contaminan la DB de desarrollo
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest

# Forzar DB en memoria para tests de storage
os.environ["DATABASE__URL"] = "sqlite:///:memory:"


@pytest.fixture
def db():
    from storage.database import Database, reset_database
    reset_database()
    test_db = Database("sqlite:///:memory:")
    test_db.create_tables()
    yield test_db
    test_db.dispose()


@pytest.fixture
def ts_repo(db):
    from storage.timeseries import TimeSeriesRepository
    return TimeSeriesRepository(db)


@pytest.fixture
def trade_repo(db):
    from storage.repository import TradingRepository
    return TradingRepository(db)


def make_ohlcv_list(symbol: str = "TEST", n: int = 10):
    from config.schemas import OHLCV
    return [
        OHLCV(
            symbol=symbol,
            timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            open=100.0 + i,
            high=105.0 + i,
            low=98.0 + i,
            close=103.0 + i,
            volume=1_000_000.0,
        )
        for i in range(n)
    ]


class TestTimeSeriesRepository:
    def test_upsert_and_count(self, ts_repo):
        bars = make_ohlcv_list("AAPL", 10)
        stored = ts_repo.upsert_many(bars, interval="1d", source="test")
        assert stored == 10
        assert ts_repo.count_bars("AAPL") == 10

    def test_upsert_is_idempotent(self, ts_repo):
        bars = make_ohlcv_list("AAPL", 10)
        ts_repo.upsert_many(bars)
        ts_repo.upsert_many(bars)  # segunda vez no duplica
        assert ts_repo.count_bars("AAPL") == 10

    def test_upsert_updates_existing(self, ts_repo):
        from config.schemas import OHLCV
        bar = OHLCV(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=100.0, high=105.0, low=98.0, close=103.0, volume=1_000_000.0,
        )
        ts_repo.upsert_many([bar])

        updated_bar = OHLCV(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=100.0, high=105.0, low=98.0, close=150.0, volume=999.0,
        )
        ts_repo.upsert_many([updated_bar])

        df = ts_repo.fetch_range("AAPL", date(2024, 1, 1), date(2024, 1, 1))
        assert df.iloc[0]["close"] == pytest.approx(150.0)

    def test_fetch_range_returns_correct_data(self, ts_repo):
        bars = make_ohlcv_list("SPY", 15)
        ts_repo.upsert_many(bars)

        df = ts_repo.fetch_range("SPY", date(2024, 1, 3), date(2024, 1, 7))
        assert len(df) == 5
        assert df["symbol"].iloc[0] == "SPY"

    def test_fetch_range_returns_empty_for_unknown_symbol(self, ts_repo):
        df = ts_repo.fetch_range("NOTEXIST", date(2024, 1, 1), date(2024, 12, 31))
        assert df.empty

    def test_fetch_range_sorted_by_timestamp(self, ts_repo):
        bars = make_ohlcv_list("TEST", 10)
        ts_repo.upsert_many(bars[::-1])  # insertar en orden inverso
        df = ts_repo.fetch_range("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert df.index.is_monotonic_increasing

    def test_get_latest_timestamp(self, ts_repo):
        bars = make_ohlcv_list("AAPL", 10)
        ts_repo.upsert_many(bars)
        latest = ts_repo.get_latest_timestamp("AAPL")
        assert latest is not None
        expected = datetime(2024, 1, 10, tzinfo=timezone.utc)
        assert latest.date() == expected.date()

    def test_get_latest_timestamp_none_when_no_data(self, ts_repo):
        latest = ts_repo.get_latest_timestamp("NOTEXIST")
        assert latest is None

    def test_get_available_symbols(self, ts_repo):
        ts_repo.upsert_many(make_ohlcv_list("AAPL", 5))
        ts_repo.upsert_many(make_ohlcv_list("SPY", 5))
        ts_repo.upsert_many(make_ohlcv_list("QQQ", 5))
        symbols = ts_repo.get_available_symbols()
        assert set(symbols) == {"AAPL", "SPY", "QQQ"}

    def test_different_intervals_stored_separately(self, ts_repo):
        daily_bars = make_ohlcv_list("AAPL", 10)
        ts_repo.upsert_many(daily_bars, interval="1d")
        ts_repo.upsert_many(daily_bars, interval="1h")
        assert ts_repo.count_bars("AAPL", interval="1d") == 10
        assert ts_repo.count_bars("AAPL", interval="1h") == 10

    def test_upsert_empty_list_returns_zero(self, ts_repo):
        result = ts_repo.upsert_many([])
        assert result == 0

    def test_fetch_includes_boundary_dates(self, ts_repo):
        bars = make_ohlcv_list("TEST", 5)
        ts_repo.upsert_many(bars)
        df = ts_repo.fetch_range("TEST", date(2024, 1, 1), date(2024, 1, 5))
        assert len(df) == 5


class TestTradingRepository:
    def test_log_ingestion(self, trade_repo):
        trade_repo.log_ingestion(
            symbol="AAPL",
            interval="1d",
            source="yfinance",
            start_date="2024-01-01",
            end_date="2024-01-31",
            bars_downloaded=22,
            bars_stored=22,
            had_errors=False,
            had_warnings=False,
        )
        # Si no lanza excepción, el log se guardó correctamente

    def test_save_and_retrieve_trade(self, trade_repo):
        from config.schemas import Trade, OrderSide
        trade = Trade(
            trade_id="t001",
            strategy_id="sma_v1",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10.0,
            entry_price=150.0,
            exit_price=165.0,
            entry_time=datetime(2024, 1, 5, tzinfo=timezone.utc),
            exit_time=datetime(2024, 1, 10, tzinfo=timezone.utc),
            commission=2.0,
        )
        trade_repo.save_trade(trade, environment="backtest")
        trades = trade_repo.get_trades(strategy_id="sma_v1")
        assert len(trades) == 1
        assert trades[0].trade_id == "t001"

    def test_save_trade_idempotent(self, trade_repo):
        from config.schemas import Trade, OrderSide
        trade = Trade(
            trade_id="t_dup",
            strategy_id="test",
            symbol="SPY",
            side=OrderSide.BUY,
            quantity=5.0,
            entry_price=400.0,
            exit_price=410.0,
            entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            exit_time=datetime(2024, 1, 5, tzinfo=timezone.utc),
        )
        trade_repo.save_trade(trade, "backtest")
        trade_repo.save_trade(trade, "backtest")  # segunda vez no duplica
        trades = trade_repo.get_trades()
        assert len([t for t in trades if t.trade_id == "t_dup"]) == 1

    def test_get_trades_filter_by_symbol(self, trade_repo):
        from config.schemas import Trade, OrderSide
        for symbol, trade_id in [("AAPL", "t1"), ("SPY", "t2"), ("AAPL", "t3")]:
            trade = Trade(
                trade_id=trade_id,
                strategy_id="test",
                symbol=symbol,
                side=OrderSide.BUY,
                quantity=1.0,
                entry_price=100.0,
                exit_price=110.0,
                entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                exit_time=datetime(2024, 1, 5, tzinfo=timezone.utc),
            )
            trade_repo.save_trade(trade, "backtest")
        aapl_trades = trade_repo.get_trades(symbol="AAPL")
        assert len(aapl_trades) == 2
