"""
Repositorio general para trades, órdenes y logs de ingestión.

Separado de timeseries.py porque tiene responsabilidades distintas:
- timeseries.py: datos de mercado (alta frecuencia, lectura intensiva)
- repository.py: datos del sistema (trades, órdenes, logs de auditoría)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select

from config.schemas import Order, Trade
from monitoring.logger import get_logger
from storage.database import Database
from storage.models import IngestionLogRecord, OrderRecord, TradeRecord

logger = get_logger(__name__)


class TradingRepository:
    """Persistencia de trades, órdenes y logs del sistema."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- Trades ----

    def save_trade(self, trade: Trade, environment: str) -> None:
        """Persiste un trade cerrado. Idempotente: ignora si ya existe."""
        record = TradeRecord(
            trade_id=trade.trade_id,
            strategy_id=trade.strategy_id,
            symbol=trade.symbol,
            side=trade.side.value,
            quantity=trade.quantity,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            entry_time=trade.entry_time,
            exit_time=trade.exit_time,
            gross_pnl=trade.gross_pnl,
            net_pnl=trade.net_pnl,
            commission=trade.commission,
            slippage=trade.slippage,
            environment=environment,
        )
        with self._db.session() as session:
            existing = session.execute(
                select(TradeRecord).where(TradeRecord.trade_id == trade.trade_id)
            ).scalar_one_or_none()
            if existing is None:
                session.add(record)
                logger.debug(
                    "Trade guardado",
                    trade_id=trade.trade_id,
                    symbol=trade.symbol,
                    net_pnl=trade.net_pnl,
                )

    def get_trades(
        self,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        environment: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> list[TradeRecord]:
        """Recupera trades con filtros opcionales."""
        with self._db.session() as session:
            stmt = select(TradeRecord)
            conditions = []
            if strategy_id:
                conditions.append(TradeRecord.strategy_id == strategy_id)
            if symbol:
                conditions.append(TradeRecord.symbol == symbol)
            if environment:
                conditions.append(TradeRecord.environment == environment)
            if start_time:
                conditions.append(TradeRecord.entry_time >= start_time)
            if end_time:
                conditions.append(TradeRecord.exit_time <= end_time)
            if conditions:
                stmt = stmt.where(and_(*conditions))
            stmt = stmt.order_by(TradeRecord.entry_time)
            return session.execute(stmt).scalars().all()

    # ---- Órdenes ----

    def save_order(self, order: Order, environment: str) -> None:
        """Persiste o actualiza una orden."""
        with self._db.session() as session:
            existing = session.execute(
                select(OrderRecord).where(OrderRecord.order_id == order.order_id)
            ).scalar_one_or_none()

            if existing:
                existing.status = order.status.value
                existing.filled_price = order.filled_price
                existing.filled_quantity = order.filled_quantity
                existing.commission = order.commission
                existing.reject_reason = order.reject_reason
                existing.filled_at = order.filled_at
            else:
                record = OrderRecord(
                    order_id=order.order_id,
                    strategy_id=order.strategy_id,
                    symbol=order.symbol,
                    side=order.side.value,
                    order_type=order.order_type.value,
                    quantity=order.quantity,
                    limit_price=order.limit_price,
                    stop_price=order.stop_price,
                    status=order.status.value,
                    filled_price=order.filled_price,
                    filled_quantity=order.filled_quantity,
                    commission=order.commission,
                    reject_reason=order.reject_reason,
                    environment=environment,
                    submitted_at=order.submitted_at,
                    filled_at=order.filled_at,
                )
                session.add(record)

    # ---- Logs de ingestión ----

    def log_ingestion(
        self,
        symbol: str,
        interval: str,
        source: str,
        start_date: str,
        end_date: str,
        bars_downloaded: int,
        bars_stored: int,
        had_errors: bool,
        had_warnings: bool,
        error_summary: Optional[str] = None,
    ) -> None:
        """Registra el resultado de un proceso de ingestión de datos."""
        record = IngestionLogRecord(
            symbol=symbol,
            interval=interval,
            source=source,
            start_date=start_date,
            end_date=end_date,
            bars_downloaded=bars_downloaded,
            bars_stored=bars_stored,
            had_errors=int(had_errors),
            had_warnings=int(had_warnings),
            error_summary=error_summary,
        )
        with self._db.session() as session:
            session.add(record)
