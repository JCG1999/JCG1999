"""
Tests del sistema de providers.

IMPORTANTE: estos tests NO hacen llamadas reales a yfinance.
Los tests que requieren red son frágiles, lentos y no deberían estar en el
test suite unitario. En su lugar, mockeamos yfinance.download.

El proveedor real se prueba manualmente con el script download_data.py.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data.providers.base import DataProvider, DataProviderError
from data.providers.yfinance_provider import YFinanceProvider


def make_yfinance_df(symbol: str = "AAPL", n: int = 10) -> pd.DataFrame:
    """Simula la salida de yfinance.download()"""
    index = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    df = pd.DataFrame({
        "Open":   [150.0 + i for i in range(n)],
        "High":   [155.0 + i for i in range(n)],
        "Low":    [148.0 + i for i in range(n)],
        "Close":  [153.0 + i for i in range(n)],
        "Volume": [5_000_000.0] * n,
    }, index=index)
    df.index.name = "Date"
    return df


class TestDataProviderInterface:
    def test_base_class_is_abstract(self):
        with pytest.raises(TypeError):
            DataProvider()  # no se puede instanciar directamente

    def test_yfinance_provider_is_data_provider(self):
        assert isinstance(YFinanceProvider(), DataProvider)

    def test_yfinance_provider_name(self):
        assert YFinanceProvider().name == "yfinance"


class TestYFinanceProviderNormalization:
    """Tests de normalización sin llamadas reales a yfinance."""

    @patch("yfinance.download")
    def test_fetch_returns_correct_columns(self, mock_download):
        mock_download.return_value = make_yfinance_df()
        provider = YFinanceProvider()
        result = provider.fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31))
        assert set(["open", "high", "low", "close", "volume"]).issubset(set(result.columns))

    @patch("yfinance.download")
    def test_fetch_returns_utc_index(self, mock_download):
        mock_download.return_value = make_yfinance_df()
        provider = YFinanceProvider()
        result = provider.fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31))
        assert result.index.tzinfo is not None

    @patch("yfinance.download")
    def test_fetch_empty_df_returns_empty(self, mock_download):
        mock_download.return_value = pd.DataFrame()
        provider = YFinanceProvider()
        result = provider.fetch_ohlcv("FAKE", date(2024, 1, 1), date(2024, 1, 31))
        assert result.empty

    @patch("yfinance.download")
    def test_columns_are_lowercase(self, mock_download):
        mock_download.return_value = make_yfinance_df()
        provider = YFinanceProvider()
        result = provider.fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31))
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns

    @patch("yfinance.download")
    def test_dividends_column_removed(self, mock_download):
        df = make_yfinance_df()
        df["Dividends"] = 0.0
        mock_download.return_value = df
        provider = YFinanceProvider()
        result = provider.fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31))
        assert "Dividends" not in result.columns
        assert "dividends" not in result.columns

    def test_invalid_interval_raises(self):
        provider = YFinanceProvider()
        with pytest.raises(DataProviderError):
            provider.fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31), interval="invalid")

    @patch("yfinance.download")
    def test_retry_on_failure(self, mock_download):
        mock_download.side_effect = [
            Exception("Timeout"),
            Exception("Timeout"),
            make_yfinance_df(),
        ]
        provider = YFinanceProvider(retry_attempts=3, retry_delay_seconds=0.0)
        result = provider.fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31))
        assert not result.empty
        assert mock_download.call_count == 3

    @patch("yfinance.download")
    def test_raises_after_all_retries_fail(self, mock_download):
        mock_download.side_effect = Exception("Network error")
        provider = YFinanceProvider(retry_attempts=2, retry_delay_seconds=0.0)
        with pytest.raises(DataProviderError):
            provider.fetch_ohlcv("AAPL", date(2024, 1, 1), date(2024, 1, 31))


class TestFetchMultiple:
    @patch("yfinance.download")
    def test_fetch_multiple_returns_dict(self, mock_download):
        mock_download.return_value = make_yfinance_df()
        provider = YFinanceProvider()
        result = provider.fetch_multiple(
            ["AAPL", "SPY"], date(2024, 1, 1), date(2024, 1, 31)
        )
        assert isinstance(result, dict)
        assert "AAPL" in result
        assert "SPY" in result

    @patch("yfinance.download")
    def test_one_failure_does_not_stop_others(self, mock_download):
        def side_effect(*args, **kwargs):
            tickers = kwargs.get("tickers", args[0] if args else "")
            if "FAIL" in str(tickers):
                raise Exception("Simulated failure")
            return make_yfinance_df()

        mock_download.side_effect = side_effect
        provider = YFinanceProvider(retry_attempts=1, retry_delay_seconds=0.0)
        result = provider.fetch_multiple(
            ["AAPL", "FAIL", "SPY"], date(2024, 1, 1), date(2024, 1, 31)
        )
        assert "AAPL" in result
        assert "SPY" in result
        assert result["FAIL"].empty
