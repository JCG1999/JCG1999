"""
Modelos SQLAlchemy para la base de datos.

Decisiones de diseño:
- Una tabla por tipo de dato (OHLCV, trades, órdenes, etc.)
- UNIQUE constraint en (symbol, timestamp, interval) para OHLCV: permite upsert
- created_at en todas las tablas: auditoría de cuándo entró cada dato
- No usamos ForeignKeys en esta fase: simplifica el schema sin perder funcionalidad

Por qué SQLite primero:
- Sin servidor, sin configuración adicional
- Suficiente para backtesting (lectura) y paper trading (escritura moderada)
- El mismo código SQLAlchemy funciona con PostgreSQL cambiando solo la URL
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OHLCVRecord(Base):
    """
    Tabla de series temporales OHLCV.
    UNIQUE (symbol, timestamp, interval) permite INSERT OR REPLACE para evitar duplicados.
    """
    __tablename__ = "ohlcv"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    interval = Column(String(10), nullable=False, default="1d")
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    source = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", "interval", name="uq_ohlcv_symbol_ts_interval"),
        Index("ix_ohlcv_symbol_timestamp", "symbol", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<OHLCVRecord {self.symbol} {self.timestamp} close={self.close}>"


class TradeRecord(Base):
    """
    Registro de trades cerrados. Inmutable: solo INSERT, nunca UPDATE.
    """
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(64), unique=True, nullable=False)
    strategy_id = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)         # "buy" | "sell"
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True), nullable=False)
    gross_pnl = Column(Float, nullable=False)
    net_pnl = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    slippage = Column(Float, default=0.0)
    environment = Column(String(20), nullable=False)  # "backtest" | "paper" | "live"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_trades_strategy_id", "strategy_id"),
        Index("ix_trades_symbol", "symbol"),
        Index("ix_trades_entry_time", "entry_time"),
    )


class OrderRecord(Base):
    """
    Registro de órdenes enviadas al broker.
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False)
    strategy_id = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    order_type = Column(String(20), nullable=False)
    quantity = Column(Float, nullable=False)
    limit_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    status = Column(String(20), nullable=False)
    filled_price = Column(Float, nullable=True)
    filled_quantity = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    reject_reason = Column(String(500), nullable=True)
    environment = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    filled_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_orders_strategy_id", "strategy_id"),
        Index("ix_orders_status", "status"),
    )


class IngestionLogRecord(Base):
    """
    Log de cada proceso de ingestión de datos.
    Permite auditar qué datos se descargaron, cuándo y con qué resultado.
    """
    __tablename__ = "ingestion_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    interval = Column(String(10), nullable=False)
    source = Column(String(50), nullable=False)
    start_date = Column(String(20), nullable=False)   # ISO date string
    end_date = Column(String(20), nullable=False)
    bars_downloaded = Column(Integer, default=0)
    bars_stored = Column(Integer, default=0)
    had_errors = Column(Integer, default=0)            # 0 | 1 (SQLite no tiene bool)
    had_warnings = Column(Integer, default=0)
    error_summary = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
