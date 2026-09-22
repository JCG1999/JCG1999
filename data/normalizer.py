"""
Normalización de datos: convierte un DataFrame validado a objetos OHLCV tipados.

Responsabilidad única: transformación de formato.
Recibe DataFrames ya validados (sin NaN, sin precios negativos) y los
convierte a la lista de objetos OHLCV definida en config/schemas.py.

Por qué convertir a objetos OHLCV:
- Los módulos posteriores (features, backtesting) trabajan con tipos conocidos
- Los errores de tipo se detectan aquí, no dentro de la lógica de negocio
- Facilita el testing: los tests de estrategia no dependen del formato del DataFrame

Nota: esta capa es intencionalemente thin. La validación ya ocurrió en validators.py.
Si llegan datos sucios aquí es un bug del caller, no de este módulo.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from config.schemas import OHLCV
from monitoring.logger import get_logger

logger = get_logger(__name__)


class DataNormalizer:
    """
    Convierte DataFrames validados a listas de objetos OHLCV.

    Garantías:
    - Todos los timestamps son timezone-aware (UTC)
    - El símbolo está presente en cada objeto
    - Los tipos numéricos son float Python nativo
    """

    def to_ohlcv_list(self, df: pd.DataFrame, symbol: str) -> list[OHLCV]:
        """
        Convierte un DataFrame validado a lista de objetos OHLCV.

        Args:
            df: DataFrame con columnas [open, high, low, close, volume]
                e índice DatetimeIndex UTC. Ya validado.
            symbol: Ticker del activo.

        Returns:
            Lista de OHLCV ordenada cronológicamente.
        """
        if df.empty:
            return []

        df_sorted = df.sort_index()
        result = []

        for timestamp, row in df_sorted.iterrows():
            try:
                ts = self._ensure_utc(timestamp)
                ohlcv = OHLCV(
                    symbol=symbol,
                    timestamp=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
                result.append(ohlcv)
            except Exception as e:
                logger.warning(
                    f"Error convirtiendo barra a OHLCV en {timestamp}: {e}",
                    symbol=symbol,
                    timestamp=str(timestamp),
                )
                continue

        logger.debug(
            f"Normalización completada: {len(result)} objetos OHLCV",
            symbol=symbol,
            count=len(result),
        )
        return result

    def to_dataframe(self, ohlcv_list: list[OHLCV]) -> pd.DataFrame:
        """
        Convierte una lista de objetos OHLCV de vuelta a DataFrame.
        Útil para el backtesting engine que trabaja sobre DataFrames.
        """
        if not ohlcv_list:
            return pd.DataFrame(columns=["symbol", "open", "high", "low", "close", "volume"])

        records = [
            {
                "symbol": o.symbol,
                "open": o.open,
                "high": o.high,
                "low": o.low,
                "close": o.close,
                "volume": o.volume,
            }
            for o in ohlcv_list
        ]
        index = pd.DatetimeIndex([o.timestamp for o in ohlcv_list], name="timestamp")
        df = pd.DataFrame(records, index=index)
        return df.sort_index()

    @staticmethod
    def _ensure_utc(ts) -> datetime:
        """Garantiza que el timestamp es timezone-aware en UTC."""
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)
        # fallback: intentar parsear
        return datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc)
