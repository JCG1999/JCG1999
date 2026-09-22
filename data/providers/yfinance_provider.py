"""
Proveedor de datos basado en yfinance.

Adecuado para:
- Backtesting histórico (datos diarios, semanas, meses)
- Desarrollo y pruebas sin coste

Limitaciones conocidas (importantes para backtesting honesto):
- Los datos pueden tener pequeñas discrepancias vs datos de pago
- El ajuste por dividendos/splits puede diferir de otras fuentes
- No es fiable para datos intradiarios históricos de largo plazo
- Rate limiting no documentado: evitar llamadas muy frecuentes

Por qué wrapeamos yfinance en lugar de usarlo directamente:
- Normaliza la salida a nuestra estructura interna
- Centraliza el manejo de errores y reintentos
- Permite mockear en tests sin acceso a red
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

from data.providers.base import DataProvider, DataProviderError
from monitoring.logger import get_logger

logger = get_logger(__name__)

# Columnas que yfinance puede retornar que no necesitamos
_COLUMNS_TO_DROP = ["Dividends", "Stock Splits", "Capital Gains"]

# Mapeo de columnas yfinance → nombres internos (minúsculas)
_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Adj Close": "adj_close",
}

# Intervalos válidos para yfinance
_VALID_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}


class YFinanceProvider(DataProvider):
    """
    Proveedor de datos usando la librería yfinance.
    No requiere credenciales. Uso libre con limitaciones de rate.
    """

    def __init__(self, retry_attempts: int = 3, retry_delay_seconds: float = 2.0) -> None:
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay_seconds

    @property
    def name(self) -> str:
        return "yfinance"

    def is_available(self) -> bool:
        """
        Verifica disponibilidad descargando un símbolo conocido.
        Si falla, asume que hay problema de conectividad.
        """
        try:
            import yfinance as yf
            ticker = yf.Ticker("SPY")
            info = ticker.fast_info
            return info is not None
        except Exception:
            return False

    def fetch_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Descarga OHLCV de yfinance y normaliza al formato interno.

        Normalización aplicada:
        1. Columnas renombradas a minúsculas
        2. Índice convertido a UTC
        3. Columnas innecesarias eliminadas
        4. Tipos de datos forzados a float64

        Nota sobre fechas en yfinance:
        - Para datos diarios: 'end' es exclusivo en yfinance.
          Sumamos un día para incluir la fecha 'end'.
        - Para datos intradiarios: el comportamiento varía.
        """
        if interval not in _VALID_INTERVALS:
            raise DataProviderError(
                f"Intervalo '{interval}' no soportado. Válidos: {_VALID_INTERVALS}",
                symbol=symbol,
                provider=self.name,
            )

        import yfinance as yf
        from datetime import timedelta

        # yfinance excluye el día 'end', así que sumamos 1 día para intervalos diarios
        end_inclusive = end
        if interval in {"1d", "5d", "1wk", "1mo", "3mo"}:
            end_inclusive = end + timedelta(days=1)

        last_exception: Optional[Exception] = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                logger.debug(
                    f"Descargando {symbol} [{interval}] {start} → {end}",
                    symbol=symbol,
                    attempt=attempt,
                )
                raw_df = yf.download(
                    tickers=symbol,
                    start=start.isoformat(),
                    end=end_inclusive.isoformat(),
                    interval=interval,
                    auto_adjust=True,   # aplica ajuste por splits/dividendos
                    progress=False,
                    threads=False,
                )
                return self._normalize(raw_df, symbol)

            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Intento {attempt}/{self._retry_attempts} fallido para {symbol}: {e}",
                    symbol=symbol,
                    attempt=attempt,
                )
                if attempt < self._retry_attempts:
                    time.sleep(self._retry_delay * attempt)

        raise DataProviderError(
            f"No se pudo descargar {symbol} después de {self._retry_attempts} intentos: {last_exception}",
            symbol=symbol,
            provider=self.name,
        )

    def _normalize(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Convierte el DataFrame crudo de yfinance al formato interno.

        Formato interno esperado:
        - Índice: DatetimeIndex timezone-aware (UTC)
        - Columnas: open, high, low, close, volume (float64)
        - Sin columnas extra
        - Sin filas con NaN en precios
        """
        if df.empty:
            logger.warning(f"yfinance retornó DataFrame vacío para {symbol}", symbol=symbol)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # yfinance a veces retorna MultiIndex cuando se piden varios tickers a la vez
        if isinstance(df.columns, pd.MultiIndex):
            df = df[symbol] if symbol in df.columns.get_level_values(0) else df.droplevel(1, axis=1)

        # Eliminar columnas no necesarias
        for col in _COLUMNS_TO_DROP:
            if col in df.columns:
                df = df.drop(columns=[col])

        # Renombrar columnas al estándar interno
        df = df.rename(columns=_COLUMN_MAP)

        # Asegurar que tenemos las columnas necesarias
        required = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise DataProviderError(
                f"Columnas faltantes en datos de {symbol}: {missing}",
                symbol=symbol,
                provider=self.name,
            )

        df = df[required].copy()

        # Convertir índice a UTC
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        # Forzar tipos numéricos
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Eliminar filas donde precio es NaN (puede ocurrir con auto_adjust en bordes)
        price_cols = ["open", "high", "low", "close"]
        df = df.dropna(subset=price_cols)

        df.index.name = "timestamp"
        df["symbol"] = symbol

        logger.debug(
            f"Datos descargados: {len(df)} barras",
            symbol=symbol,
            rows=len(df),
            start=str(df.index.min()) if not df.empty else "N/A",
            end=str(df.index.max()) if not df.empty else "N/A",
        )
        return df
