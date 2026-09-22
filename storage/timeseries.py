"""
Repositorio para datos de series temporales OHLCV.

Operaciones principales:
- upsert_many: inserta o actualiza barras (evita duplicados)
- fetch_range: recupera datos para un símbolo en un rango de fechas
- get_latest_timestamp: saber hasta qué fecha tenemos datos de un símbolo
- get_available_symbols: qué símbolos tenemos en la DB

Por qué upsert en lugar de insert:
- Si descargamos los mismos datos dos veces (re-run del script de descarga)
  no queremos duplicados ni errores. El upsert simplemente sobreescribe.
- En SQLite: INSERT OR REPLACE (elimina y reinserta, actualiza el ID)
- En PostgreSQL: ON CONFLICT DO UPDATE (más eficiente, preserva el ID)

Por qué retornar DataFrames y no objetos ORM:
- El backtesting engine y el feature engine trabajan nativamente con pandas
- Construir un DataFrame desde una lista de ORM es un paso innecesario
- Los ORM son para la capa de persistencia; pandas para la capa de cálculo
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd
from sqlalchemy import and_, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config.schemas import OHLCV
from monitoring.logger import get_logger
from storage.database import Database
from storage.models import OHLCVRecord

logger = get_logger(__name__)


class TimeSeriesRepository:
    """
    Gestiona la persistencia y recuperación de datos OHLCV.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert_many(
        self,
        ohlcv_list: list[OHLCV],
        interval: str = "1d",
        source: str = "unknown",
    ) -> int:
        """
        Inserta o actualiza una lista de barras OHLCV.

        Returns:
            Número de barras procesadas.
        """
        if not ohlcv_list:
            return 0

        records = [
            {
                "symbol": bar.symbol,
                "timestamp": bar.timestamp,
                "interval": interval,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": source,
            }
            for bar in ohlcv_list
        ]

        with self._db.session() as session:
            # SQLite: INSERT OR REPLACE usando el UNIQUE constraint
            stmt = sqlite_insert(OHLCVRecord).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "timestamp", "interval"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "source": stmt.excluded.source,
                },
            )
            session.execute(stmt)

        logger.debug(
            f"Upsert completado: {len(records)} barras",
            symbol=ohlcv_list[0].symbol if ohlcv_list else "N/A",
            count=len(records),
        )
        return len(records)

    def fetch_range(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """
        Recupera datos OHLCV para un símbolo en un rango de fechas.

        Returns:
            DataFrame con columnas [open, high, low, close, volume]
            e índice DatetimeIndex UTC, ordenado cronológicamente.
            DataFrame vacío si no hay datos.
        """
        start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        end_dt = datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=timezone.utc)

        with self._db.session() as session:
            stmt = (
                select(OHLCVRecord)
                .where(
                    and_(
                        OHLCVRecord.symbol == symbol,
                        OHLCVRecord.interval == interval,
                        OHLCVRecord.timestamp >= start_dt,
                        OHLCVRecord.timestamp <= end_dt,
                    )
                )
                .order_by(OHLCVRecord.timestamp)
            )
            rows = session.execute(stmt).scalars().all()

        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        data = {
            "open": [r.open for r in rows],
            "high": [r.high for r in rows],
            "low": [r.low for r in rows],
            "close": [r.close for r in rows],
            "volume": [r.volume for r in rows],
        }
        index = pd.DatetimeIndex([r.timestamp for r in rows], name="timestamp")
        df = pd.DataFrame(data, index=index)
        df["symbol"] = symbol
        return df

    def get_latest_timestamp(
        self, symbol: str, interval: str = "1d"
    ) -> Optional[datetime]:
        """
        Retorna el timestamp de la barra más reciente almacenada para un símbolo.
        Útil para saber desde qué fecha actualizar los datos.
        """
        with self._db.session() as session:
            stmt = (
                select(OHLCVRecord.timestamp)
                .where(
                    and_(
                        OHLCVRecord.symbol == symbol,
                        OHLCVRecord.interval == interval,
                    )
                )
                .order_by(OHLCVRecord.timestamp.desc())
                .limit(1)
            )
            result = session.execute(stmt).scalar_one_or_none()
        return result

    def get_available_symbols(self, interval: str = "1d") -> list[str]:
        """Retorna todos los símbolos disponibles en la DB para un intervalo."""
        with self._db.session() as session:
            stmt = (
                select(OHLCVRecord.symbol)
                .where(OHLCVRecord.interval == interval)
                .distinct()
                .order_by(OHLCVRecord.symbol)
            )
            results = session.execute(stmt).scalars().all()
        return list(results)

    def count_bars(self, symbol: str, interval: str = "1d") -> int:
        """Retorna el número total de barras almacenadas para un símbolo."""
        with self._db.session() as session:
            stmt = text(
                "SELECT COUNT(*) FROM ohlcv WHERE symbol = :symbol AND interval = :interval"
            )
            result = session.execute(stmt, {"symbol": symbol, "interval": interval}).scalar()
        return result or 0
