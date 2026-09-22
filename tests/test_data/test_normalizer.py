"""Tests del DataNormalizer."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from config.schemas import OHLCV
from data.normalizer import DataNormalizer


def make_clean_df(n: int = 5) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    df = pd.DataFrame({
        "open":   [100.0 + i for i in range(n)],
        "high":   [105.0 + i for i in range(n)],
        "low":    [98.0  + i for i in range(n)],
        "close":  [103.0 + i for i in range(n)],
        "volume": [1_000_000.0] * n,
        "symbol": ["TEST"] * n,
    }, index=timestamps)
    df.index.name = "timestamp"
    return df


class TestToOHLCVList:
    def test_converts_df_to_ohlcv_list(self):
        df = make_clean_df(5)
        result = DataNormalizer().to_ohlcv_list(df, "TEST")
        assert len(result) == 5
        assert all(isinstance(r, OHLCV) for r in result)

    def test_symbol_is_set_correctly(self):
        df = make_clean_df(3)
        result = DataNormalizer().to_ohlcv_list(df, "AAPL")
        assert all(r.symbol == "AAPL" for r in result)

    def test_values_match_dataframe(self):
        df = make_clean_df(1)
        result = DataNormalizer().to_ohlcv_list(df, "TEST")
        bar = result[0]
        assert bar.open == pytest.approx(100.0)
        assert bar.high == pytest.approx(105.0)
        assert bar.low == pytest.approx(98.0)
        assert bar.close == pytest.approx(103.0)
        assert bar.volume == pytest.approx(1_000_000.0)

    def test_timestamps_are_utc(self):
        df = make_clean_df(3)
        result = DataNormalizer().to_ohlcv_list(df, "TEST")
        for bar in result:
            assert bar.timestamp.tzinfo is not None
            assert bar.timestamp.tzinfo.utcoffset(bar.timestamp).total_seconds() == 0

    def test_empty_df_returns_empty_list(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = DataNormalizer().to_ohlcv_list(df, "TEST")
        assert result == []

    def test_result_is_sorted_chronologically(self):
        # DataFrame con fechas desordenadas
        df = make_clean_df(5)
        df = df.iloc[::-1]  # invertir orden
        result = DataNormalizer().to_ohlcv_list(df, "TEST")
        timestamps = [r.timestamp for r in result]
        assert timestamps == sorted(timestamps)

    def test_timezone_naive_index_becomes_utc(self):
        df = make_clean_df(3)
        df.index = df.index.tz_localize(None)  # eliminar timezone
        result = DataNormalizer().to_ohlcv_list(df, "TEST")
        assert len(result) == 3
        for bar in result:
            assert bar.timestamp.tzinfo is not None


class TestToDataFrame:
    def test_roundtrip_df_to_ohlcv_to_df(self):
        original_df = make_clean_df(5)
        normalizer = DataNormalizer()
        ohlcv_list = normalizer.to_ohlcv_list(original_df, "TEST")
        result_df = normalizer.to_dataframe(ohlcv_list)

        assert len(result_df) == 5
        assert list(result_df.columns) == ["symbol", "open", "high", "low", "close", "volume"]

    def test_empty_list_returns_empty_df(self):
        result = DataNormalizer().to_dataframe([])
        assert result.empty

    def test_values_preserved_in_roundtrip(self):
        original_df = make_clean_df(3)
        normalizer = DataNormalizer()
        ohlcv_list = normalizer.to_ohlcv_list(original_df, "TEST")
        result_df = normalizer.to_dataframe(ohlcv_list)

        assert result_df["close"].iloc[0] == pytest.approx(103.0)
        assert result_df["close"].iloc[1] == pytest.approx(104.0)
