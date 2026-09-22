"""
Tests del DataValidator.

Principio: cada test verifica UN comportamiento específico.
Los tests de validación son especialmente importantes porque
un bug aquí puede dejar pasar datos corruptos al resto del sistema.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from data.validators import DataValidator, IssueType, IssueSeverity


def make_df(rows: list[dict]) -> pd.DataFrame:
    """Construye un DataFrame OHLCV desde una lista de dicts."""
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    idx = pd.DatetimeIndex([r["ts"] for r in rows], name="timestamp")
    # Si los timestamps ya llevan timezone, convertir; si no, localizar
    if idx.tzinfo is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    df.index = idx
    return df.drop(columns=["ts"])


def make_bar(
    ts: datetime,
    open_=100.0,
    high=105.0,
    low=98.0,
    close=103.0,
    volume=1_000_000.0,
) -> dict:
    return {"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def daily_bars(n: int, start_day: int = 1, base_price: float = 100.0) -> pd.DataFrame:
    """Genera n barras diarias limpias para tests."""
    rows = [
        make_bar(
            ts=datetime(2024, 1, start_day + i, tzinfo=timezone.utc),
            open_=base_price + i,
            high=base_price + i + 5,
            low=base_price + i - 2,
            close=base_price + i + 3,
        )
        for i in range(n)
    ]
    return make_df(rows)


class TestValidatorHappyPath:
    def test_clean_data_passes_without_issues(self):
        df = daily_bars(20)
        result = DataValidator().validate(df, "TEST")
        assert not result.has_errors
        assert not result.has_warnings
        assert result.clean_count == 20
        assert result.dropped_count == 0

    def test_is_usable_true_on_clean_data(self):
        df = daily_bars(20)
        result = DataValidator().validate(df, "TEST")
        assert result.is_usable

    def test_empty_df_returns_error(self):
        result = DataValidator().validate(pd.DataFrame(), "TEST")
        assert result.has_errors
        assert not result.is_usable


class TestMissingColumns:
    def test_missing_close_column(self):
        df = daily_bars(10).drop(columns=["close"])
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        issues_types = [i.issue_type for i in result.issues]
        assert IssueType.MISSING_COLUMNS in issues_types

    def test_missing_multiple_columns(self):
        df = daily_bars(10).drop(columns=["close", "volume"])
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors


class TestNegativeAndZeroPrices:
    def test_negative_open_removed(self):
        df = daily_bars(15)
        df.iloc[5, df.columns.get_loc("open")] = -1.0
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        assert result.clean_count == 14
        assert any(i.issue_type == IssueType.NEGATIVE_PRICE for i in result.issues)

    def test_zero_close_removed(self):
        df = daily_bars(15)
        df.iloc[3, df.columns.get_loc("close")] = 0.0
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        assert result.clean_count == 14
        assert any(i.issue_type == IssueType.ZERO_PRICE for i in result.issues)

    def test_negative_volume_removed(self):
        df = daily_bars(15)
        df.iloc[2, df.columns.get_loc("volume")] = -500.0
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        assert result.clean_count == 14

    def test_zero_volume_is_kept(self):
        """Volumen cero puede ocurrir legítimamente (activos poco líquidos)."""
        df = daily_bars(15)
        df.iloc[2, df.columns.get_loc("volume")] = 0.0
        result = DataValidator().validate(df, "TEST")
        assert result.clean_count == 15  # no se elimina


class TestNaNValues:
    def test_nan_in_close_removed(self):
        df = daily_bars(15)
        df.iloc[7, df.columns.get_loc("close")] = float("nan")
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        assert result.clean_count == 14
        assert any(i.issue_type == IssueType.NAN_VALUES for i in result.issues)

    def test_nan_in_volume_not_removed(self):
        """NaN en volumen no elimina la barra (precio es lo crítico)."""
        df = daily_bars(15)
        df.iloc[7, df.columns.get_loc("volume")] = float("nan")
        result = DataValidator().validate(df, "TEST")
        assert result.clean_count == 15


class TestOHLCConsistency:
    def test_high_below_low_removed(self):
        rows = [make_bar(datetime(2024, 1, i + 1, tzinfo=timezone.utc)) for i in range(10)]
        df = make_df(rows)
        # Hacer que high < low en la fila 3
        df.iloc[3, df.columns.get_loc("high")] = 90.0
        df.iloc[3, df.columns.get_loc("low")] = 95.0
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        assert result.clean_count == 9
        assert any(i.issue_type == IssueType.HIGH_BELOW_LOW for i in result.issues)

    def test_high_below_close_removed(self):
        df = daily_bars(10)
        # high=50 < close=103 → inconsistente
        df.iloc[5, df.columns.get_loc("high")] = 50.0
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        assert result.clean_count == 9

    def test_consistent_ohlc_passes(self):
        df = daily_bars(10)
        result = DataValidator().validate(df, "TEST")
        assert not result.has_errors


class TestDuplicateTimestamps:
    def test_duplicate_timestamps_removed(self):
        rows = [make_bar(datetime(2024, 1, 1, tzinfo=timezone.utc)) for _ in range(3)]
        rows += [make_bar(datetime(2024, 1, 2, tzinfo=timezone.utc))]
        # Construir manualmente con índice duplicado
        df = pd.DataFrame([{k: v for k, v in r.items() if k != "ts"} for r in rows])
        idx = pd.DatetimeIndex([r["ts"] for r in rows], name="timestamp")
        df.index = idx.tz_convert("UTC") if idx.tzinfo is not None else idx.tz_localize("UTC")
        result = DataValidator().validate(df, "TEST")
        assert result.has_errors
        assert result.clean_count == 2  # 2 únicos timestamps
        assert any(i.issue_type == IssueType.DUPLICATE_TIMESTAMP for i in result.issues)


class TestTimeGaps:
    def test_large_gap_generates_warning(self):
        # Dos bloques separados por 20 días → gap grande
        rows = (
            [make_bar(datetime(2024, 1, i + 1, tzinfo=timezone.utc)) for i in range(5)]
            + [make_bar(datetime(2024, 2, i + 1, tzinfo=timezone.utc)) for i in range(5)]
        )
        df = make_df(rows)
        result = DataValidator(max_gap_days=7).validate(df, "TEST")
        assert result.has_warnings
        assert any(i.issue_type == IssueType.TIME_GAP for i in result.issues)
        assert not result.has_errors  # es warning, no error

    def test_weekend_gap_no_warning(self):
        """Gap de 3 días (fin de semana) no debe disparar warning con max_gap_days=7."""
        rows = [
            make_bar(datetime(2024, 1, 5, tzinfo=timezone.utc)),   # viernes
            make_bar(datetime(2024, 1, 8, tzinfo=timezone.utc)),   # lunes
        ]
        df = make_df(rows)
        result = DataValidator(max_gap_days=7, min_bars=2).validate(df, "TEST")
        assert not result.has_warnings


class TestPriceOutliers:
    def test_sudden_50pct_jump_generates_warning(self):
        rows = [
            make_bar(datetime(2024, 1, 1, tzinfo=timezone.utc), close=100.0),
            make_bar(datetime(2024, 1, 2, tzinfo=timezone.utc), close=100.0),
            make_bar(datetime(2024, 1, 3, tzinfo=timezone.utc), close=160.0, high=165.0),  # +60%
            make_bar(datetime(2024, 1, 4, tzinfo=timezone.utc), close=162.0, high=167.0),
            make_bar(datetime(2024, 1, 5, tzinfo=timezone.utc), close=163.0, high=168.0),
        ]
        df = make_df(rows)
        result = DataValidator(max_price_change_pct=0.30).validate(df, "TEST")
        assert result.has_warnings
        assert any(i.issue_type == IssueType.PRICE_OUTLIER for i in result.issues)
        # El dato sospechoso NO se elimina (puede ser legítimo)
        assert result.clean_count == 5

    def test_normal_price_changes_no_warning(self):
        df = daily_bars(20)
        result = DataValidator(max_price_change_pct=0.30).validate(df, "TEST")
        outlier_issues = [i for i in result.issues if i.issue_type == IssueType.PRICE_OUTLIER]
        assert len(outlier_issues) == 0


class TestInsufficientData:
    def test_too_few_bars_after_cleaning(self):
        df = daily_bars(5)  # 5 barras → 3 con precio negativo → queda 2
        df.iloc[0, df.columns.get_loc("open")] = -1.0
        df.iloc[1, df.columns.get_loc("open")] = -1.0
        df.iloc[2, df.columns.get_loc("open")] = -1.0
        result = DataValidator(min_bars=5).validate(df, "TEST")
        assert result.has_errors
        insufficient = [i for i in result.issues if i.issue_type == IssueType.INSUFFICIENT_DATA]
        assert len(insufficient) == 1


class TestValidationSummary:
    def test_summary_contains_symbol(self):
        df = daily_bars(20)
        df.iloc[0, df.columns.get_loc("open")] = -1.0
        result = DataValidator().validate(df, "AAPL")
        summary = result.summary()
        assert "AAPL" in summary

    def test_severity_in_summary(self):
        df = daily_bars(20)
        df.iloc[0, df.columns.get_loc("open")] = -1.0
        result = DataValidator().validate(df, "TEST")
        summary = result.summary()
        assert "ERROR" in summary
