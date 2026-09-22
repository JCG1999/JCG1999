"""
Tests del DataIngestor — pipeline completo de ingestión.

Usamos mocks para el provider y la base de datos para:
1. No hacer llamadas reales a internet
2. No escribir en base de datos real durante tests
3. Poder simular escenarios de error de forma controlada
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data.ingestor import DataIngestor
from data.providers.base import DataProviderError


def make_clean_df(symbol: str = "TEST", n: int = 20) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "open":   [100.0 + i for i in range(n)],
        "high":   [105.0 + i for i in range(n)],
        "low":    [98.0 + i for i in range(n)],
        "close":  [103.0 + i for i in range(n)],
        "volume": [1_000_000.0] * n,
        "symbol": [symbol] * n,
    }, index=index)


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.name = "mock_provider"
    provider.fetch_ohlcv.return_value = make_clean_df()
    return provider


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def ingestor(mock_provider, mock_db):
    from data.ingestor import DataIngestor
    from data.validators import DataValidator
    from data.normalizer import DataNormalizer
    from storage.timeseries import TimeSeriesRepository
    from storage.repository import TradingRepository

    ing = DataIngestor(provider=mock_provider, db=mock_db)
    # Mockear los repositorios para no tocar DB real
    ing._ts_repo = MagicMock()
    ing._ts_repo.upsert_many.return_value = 20
    ing._trade_repo = MagicMock()
    return ing


class TestIngestorSuccess:
    def test_successful_ingest_returns_success_summary(self, ingestor, mock_provider):
        summary = ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert summary.success is True
        assert summary.symbol == "TEST"

    def test_successful_ingest_stores_bars(self, ingestor):
        summary = ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert summary.bars_stored > 0

    def test_ts_repo_upsert_called(self, ingestor):
        ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert ingestor._ts_repo.upsert_many.called

    def test_ingestion_log_called(self, ingestor):
        ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert ingestor._trade_repo.log_ingestion.called


class TestIngestorProviderFailure:
    def test_provider_error_returns_failed_summary(self, ingestor, mock_provider):
        mock_provider.fetch_ohlcv.side_effect = DataProviderError("Network error")
        summary = ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert summary.success is False
        assert summary.error_message is not None

    def test_provider_error_does_not_store_bars(self, ingestor, mock_provider):
        mock_provider.fetch_ohlcv.side_effect = DataProviderError("Network error")
        ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert not ingestor._ts_repo.upsert_many.called

    def test_unexpected_exception_returns_failed_summary(self, ingestor, mock_provider):
        mock_provider.fetch_ohlcv.side_effect = RuntimeError("Unexpected")
        summary = ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert summary.success is False


class TestIngestorWithDirtyData:
    def test_data_with_some_errors_still_succeeds(self, ingestor, mock_provider):
        dirty_df = make_clean_df(n=20)
        # 2 barras con precio negativo → se eliminan en validación
        dirty_df.iloc[0, dirty_df.columns.get_loc("open")] = -1.0
        dirty_df.iloc[1, dirty_df.columns.get_loc("open")] = -1.0
        mock_provider.fetch_ohlcv.return_value = dirty_df

        summary = ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert summary.success is True
        assert summary.had_validation_errors is True

    def test_completely_corrupt_data_fails(self, ingestor, mock_provider):
        # Solo 3 barras, todas con precio negativo → quedan 0 → no usable
        dirty_df = make_clean_df(n=3)
        dirty_df["open"] = -1.0
        dirty_df["close"] = -1.0
        dirty_df["high"] = -1.0
        dirty_df["low"] = -1.0
        mock_provider.fetch_ohlcv.return_value = dirty_df

        summary = ingestor.ingest("TEST", date(2024, 1, 1), date(2024, 1, 31))
        assert summary.success is False


class TestBatchIngest:
    def test_batch_processes_all_symbols(self, ingestor):
        result = ingestor.ingest_batch(
            ["AAPL", "SPY", "QQQ"], date(2024, 1, 1), date(2024, 1, 31)
        )
        assert len(result.summaries) == 3

    def test_batch_failure_in_one_does_not_stop_others(self, ingestor, mock_provider):
        call_count = 0

        def side_effect(symbol, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if symbol == "FAIL":
                raise DataProviderError("Simulated failure")
            return make_clean_df(symbol, n=20)

        mock_provider.fetch_ohlcv.side_effect = side_effect
        result = ingestor.ingest_batch(
            ["AAPL", "FAIL", "SPY"], date(2024, 1, 1), date(2024, 1, 31)
        )
        assert len(result.successful_symbols) == 2
        assert "FAIL" in result.failed_symbols
        assert call_count == 3

    def test_batch_result_counts_total_bars(self, ingestor):
        ingestor._ts_repo.upsert_many.return_value = 20
        result = ingestor.ingest_batch(
            ["AAPL", "SPY"], date(2024, 1, 1), date(2024, 1, 31)
        )
        assert result.total_bars_stored == 40
