"""
Validación de datos de mercado antes de que entren al sistema.

Esta capa es el firewall de datos. Su contrato es:
- Recibe un DataFrame crudo de cualquier proveedor
- Detecta y clasifica todos los problemas encontrados
- Retorna los datos limpios y un informe de lo encontrado
- NUNCA silencia un problema sin registrarlo

Por qué no simplemente lanzar excepciones:
- Los datos pueden tener problemas parciales (algunas filas malas, otras buenas)
- Queremos loguear TODOS los problemas encontrados, no solo el primero
- El caller decide si los datos con warnings son aceptables para su uso

Tipos de issues:
- ERROR: dato que haría que el sistema genere señales o órdenes incorrectas
         → siempre se eliminan del dataset limpio
- WARNING: anomalía notable que puede ser legítima (e.g., gap de precio en
           evento corporativo) → se registra pero se mantiene

Umbrales de detección de anomalías:
Los valores por defecto son conservadores. Pueden ajustarse para activos
específicos (crypto tiene gaps y volatilidad mucho más alta que equities).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from monitoring.logger import get_logger

logger = get_logger(__name__)


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class IssueType(str, Enum):
    MISSING_COLUMNS = "missing_columns"
    NEGATIVE_PRICE = "negative_price"
    ZERO_PRICE = "zero_price"
    NEGATIVE_VOLUME = "negative_volume"
    HIGH_BELOW_LOW = "high_below_low"
    HIGH_BELOW_OHLC = "high_below_ohlc"
    LOW_ABOVE_OHLC = "low_above_ohlc"
    DUPLICATE_TIMESTAMP = "duplicate_timestamp"
    TIME_GAP = "time_gap"
    PRICE_OUTLIER = "price_outlier"
    NAN_VALUES = "nan_values"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class ValidationIssue:
    severity: IssueSeverity
    issue_type: IssueType
    description: str
    affected_count: int = 0
    affected_timestamps: list = field(default_factory=list)


@dataclass
class ValidationResult:
    symbol: str
    original_count: int
    clean_data: pd.DataFrame
    issues: list[ValidationIssue]

    @property
    def clean_count(self) -> int:
        return len(self.clean_data)

    @property
    def dropped_count(self) -> int:
        return self.original_count - self.clean_count

    @property
    def has_errors(self) -> bool:
        return any(i.severity == IssueSeverity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == IssueSeverity.WARNING for i in self.issues)

    @property
    def is_usable(self) -> bool:
        """
        True si los datos son utilizables (pueden tener warnings pero no errores
        que hayan resultado en pérdida total de datos).
        """
        return self.clean_count > 0

    def summary(self) -> str:
        lines = [
            f"Validación {self.symbol}: {self.original_count} barras originales → "
            f"{self.clean_count} limpias ({self.dropped_count} eliminadas)"
        ]
        for issue in self.issues:
            lines.append(f"  [{issue.severity.value.upper()}] {issue.issue_type.value}: {issue.description}")
        return "\n".join(lines)


class DataValidator:
    """
    Valida integridad de datos OHLCV.

    Uso:
        validator = DataValidator()
        result = validator.validate(df, symbol="AAPL")
        if result.has_errors:
            logger.warning(result.summary())
        clean_df = result.clean_data
    """

    def __init__(
        self,
        max_price_change_pct: float = 0.30,
        min_bars: int = 10,
        max_gap_days: int = 7,
    ) -> None:
        """
        Args:
            max_price_change_pct: Cambio de precio en una barra que se considera outlier.
                                  0.30 = 30%. Crypto puede necesitar valores más altos.
            min_bars: Mínimo de barras para considerar el dataset útil.
            max_gap_days: Días de gap entre barras que dispara un WARNING de gap.
        """
        self._max_price_change = max_price_change_pct
        self._min_bars = min_bars
        self._max_gap_days = max_gap_days

    def validate(self, df: pd.DataFrame, symbol: str) -> ValidationResult:
        """
        Ejecuta todas las validaciones sobre el DataFrame.
        Retorna datos limpios + informe de issues.
        """
        issues: list[ValidationIssue] = []
        original_count = len(df)

        if df.empty:
            return ValidationResult(
                symbol=symbol,
                original_count=0,
                clean_data=df,
                issues=[ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    issue_type=IssueType.INSUFFICIENT_DATA,
                    description="DataFrame vacío recibido",
                )],
            )

        # Trabajamos sobre una copia para no mutar el original
        clean = df.copy()

        # Orden de validaciones: primero las estructurales, luego las de contenido
        clean, issues = self._check_required_columns(clean, issues)
        if any(i.issue_type == IssueType.MISSING_COLUMNS for i in issues):
            # Sin columnas necesarias no podemos hacer más checks
            return ValidationResult(symbol=symbol, original_count=original_count, clean_data=pd.DataFrame(), issues=issues)

        clean, issues = self._check_nan_values(clean, issues)
        clean, issues = self._check_negative_prices(clean, issues)
        clean, issues = self._check_zero_prices(clean, issues)
        clean, issues = self._check_negative_volume(clean, issues)
        clean, issues = self._check_ohlc_consistency(clean, issues)
        clean, issues = self._check_duplicate_timestamps(clean, issues)
        clean, issues = self._check_time_gaps(clean, issues)
        clean, issues = self._check_price_outliers(clean, issues)
        issues = self._check_sufficient_data(clean, issues)

        result = ValidationResult(
            symbol=symbol,
            original_count=original_count,
            clean_data=clean,
            issues=issues,
        )

        if issues:
            logger.warning(result.summary(), symbol=symbol)
        else:
            logger.debug(
                f"Validación OK: {symbol} ({original_count} barras sin issues)",
                symbol=symbol,
            )

        return result

    def _check_required_columns(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.MISSING_COLUMNS,
                description=f"Columnas faltantes: {sorted(missing)}",
            ))
        return df, issues

    def _check_nan_values(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        price_cols = ["open", "high", "low", "close"]
        nan_mask = df[price_cols].isna().any(axis=1)
        count = nan_mask.sum()
        if count > 0:
            bad_timestamps = df.index[nan_mask].tolist()[:5]  # max 5 ejemplos
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.NAN_VALUES,
                description=f"{count} barras con precios NaN eliminadas",
                affected_count=count,
                affected_timestamps=bad_timestamps,
            ))
            df = df[~nan_mask]
        return df, issues

    def _check_negative_prices(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        price_cols = ["open", "high", "low", "close"]
        negative_mask = (df[price_cols] < 0).any(axis=1)
        count = negative_mask.sum()
        if count > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.NEGATIVE_PRICE,
                description=f"{count} barras con precios negativos eliminadas",
                affected_count=count,
                affected_timestamps=df.index[negative_mask].tolist()[:5],
            ))
            df = df[~negative_mask]
        return df, issues

    def _check_zero_prices(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        price_cols = ["open", "high", "low", "close"]
        zero_mask = (df[price_cols] == 0).any(axis=1)
        count = zero_mask.sum()
        if count > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.ZERO_PRICE,
                description=f"{count} barras con precio cero eliminadas",
                affected_count=count,
                affected_timestamps=df.index[zero_mask].tolist()[:5],
            ))
            df = df[~zero_mask]
        return df, issues

    def _check_negative_volume(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        negative_vol_mask = df["volume"] < 0
        count = negative_vol_mask.sum()
        if count > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.NEGATIVE_VOLUME,
                description=f"{count} barras con volumen negativo eliminadas",
                affected_count=count,
                affected_timestamps=df.index[negative_vol_mask].tolist()[:5],
            ))
            df = df[~negative_vol_mask]
        return df, issues

    def _check_ohlc_consistency(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        if df.empty:
            return df, issues

        # high debe ser >= low
        h_lt_l = df["high"] < df["low"]
        # high debe ser >= open y close
        h_lt_oc = (df["high"] < df["open"]) | (df["high"] < df["close"])
        # low debe ser <= open y close
        l_gt_oc = (df["low"] > df["open"]) | (df["low"] > df["close"])

        inconsistent = h_lt_l | h_lt_oc | l_gt_oc
        count = inconsistent.sum()
        if count > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.HIGH_BELOW_LOW,
                description=f"{count} barras con inconsistencia OHLC (high<low o similar) eliminadas",
                affected_count=count,
                affected_timestamps=df.index[inconsistent].tolist()[:5],
            ))
            df = df[~inconsistent]
        return df, issues

    def _check_duplicate_timestamps(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        duplicates = df.index.duplicated(keep="first")
        count = duplicates.sum()
        if count > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.DUPLICATE_TIMESTAMP,
                description=f"{count} timestamps duplicados eliminados (se mantiene el primero)",
                affected_count=count,
            ))
            df = df[~duplicates]
        return df, issues

    def _check_time_gaps(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        """
        Detecta gaps temporales grandes en los datos.
        Un gap puede ser legítimo (fin de semana, festivo) o un problema de datos.
        Solo reportamos gaps > max_gap_days como warning (no elimina datos).
        """
        if len(df) < 2:
            return df, issues

        time_diffs = pd.Series(df.index).diff().dropna()
        max_gap = time_diffs.max()

        if max_gap.days > self._max_gap_days:
            # Encontrar cuántos gaps grandes hay
            big_gaps = time_diffs[time_diffs.dt.days > self._max_gap_days]
            issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                issue_type=IssueType.TIME_GAP,
                description=(
                    f"{len(big_gaps)} gap(s) de >{self._max_gap_days} días detectado(s). "
                    f"Gap máximo: {max_gap.days} días. "
                    "Puede ser festivo/fin de semana o dato faltante."
                ),
                affected_count=len(big_gaps),
            ))
        return df, issues

    def _check_price_outliers(
        self, df: pd.DataFrame, issues: list
    ) -> tuple[pd.DataFrame, list]:
        """
        Detecta cambios de precio extremos entre barras consecutivas.
        Un cambio > max_price_change_pct en el close es sospechoso.
        Lo registramos como WARNING (puede ser split no ajustado, evento corporativo).
        No eliminamos el dato porque puede ser legítimo.
        """
        if len(df) < 2:
            return df, issues

        pct_changes = df["close"].pct_change().abs()
        outlier_mask = pct_changes > self._max_price_change
        count = outlier_mask.sum()

        if count > 0:
            issues.append(ValidationIssue(
                severity=IssueSeverity.WARNING,
                issue_type=IssueType.PRICE_OUTLIER,
                description=(
                    f"{count} barra(s) con cambio de precio >{self._max_price_change*100:.0f}% "
                    "respecto a la barra anterior. Verificar si es split no ajustado."
                ),
                affected_count=count,
                affected_timestamps=df.index[outlier_mask].tolist()[:5],
            ))
        return df, issues

    def _check_sufficient_data(
        self, df: pd.DataFrame, issues: list
    ) -> list:
        if len(df) < self._min_bars:
            issues.append(ValidationIssue(
                severity=IssueSeverity.ERROR,
                issue_type=IssueType.INSUFFICIENT_DATA,
                description=(
                    f"Solo {len(df)} barras disponibles después de limpieza "
                    f"(mínimo requerido: {self._min_bars})"
                ),
            ))
        return issues
