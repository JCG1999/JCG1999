"""
Interfaz abstracta para proveedores de datos de mercado.

Por qué una clase abstracta aquí:
- Garantiza que cualquier proveedor (yfinance, Alpaca, Binance, CSV local)
  expone exactamente la misma interfaz al resto del sistema.
- Permite cambiar el proveedor sin tocar código fuera de este módulo.
- Facilita el testing: se puede usar un proveedor mock en tests sin red.

Intervalos soportados (string estándar):
  "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

import pandas as pd


class DataProvider(ABC):
    """
    Contrato que todo proveedor de datos debe cumplir.
    Retorna siempre un DataFrame con columnas estandarizadas:
      open, high, low, close, volume
    Y un índice DatetimeIndex timezone-aware (UTC).
    """

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Descarga datos OHLCV para un símbolo en un rango de fechas.

        Args:
            symbol: Ticker del activo (e.g., "AAPL", "SPY", "BTC-USD")
            start: Fecha de inicio (inclusive)
            end: Fecha de fin (inclusive)
            interval: Resolución temporal

        Returns:
            DataFrame con columnas [open, high, low, close, volume]
            e índice DatetimeIndex UTC. Vacío si no hay datos.

        Raises:
            DataProviderError: Si la descarga falla por razones del proveedor.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Verifica que el proveedor es accesible (conexión, credenciales)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre del proveedor, para logging y auditoría."""

    def fetch_multiple(
        self,
        symbols: list[str],
        start: date,
        end: date,
        interval: str = "1d",
    ) -> dict[str, pd.DataFrame]:
        """
        Descarga datos para múltiples símbolos.
        Implementación por defecto: llama a fetch_ohlcv en bucle.
        Los proveedores pueden sobrescribir esto para descargas en batch.
        """
        result = {}
        for symbol in symbols:
            try:
                result[symbol] = self.fetch_ohlcv(symbol, start, end, interval)
            except DataProviderError as e:
                result[symbol] = pd.DataFrame()
                from monitoring.logger import get_logger
                get_logger(__name__).warning(
                    f"Error descargando {symbol}: {e}",
                    symbol=symbol,
                    provider=self.name,
                )
        return result


class DataProviderError(Exception):
    """Error específico de un proveedor de datos."""

    def __init__(self, message: str, symbol: str = "", provider: str = "") -> None:
        super().__init__(message)
        self.symbol = symbol
        self.provider = provider
