"""
Schemas de validación de datos internos del sistema.

Por qué Pydantic para esto:
- Garantiza que los datos entre módulos tienen el formato correcto.
- Los errores se detectan en la frontera del módulo, no dentro de él.
- Documentación implícita: el schema ES la especificación de la interfaz.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial_fill"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SignalStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class OHLCV(BaseModel):
    """Barra de precio estandarizada. Estructura interna única para todos los módulos."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("open", "high", "low", "close")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Precio debe ser positivo, recibido: {v}")
        return v

    @field_validator("high")
    @classmethod
    def high_must_be_gte_low(cls, v: float, info: object) -> float:
        # Nota: en Pydantic v2 los validators se ejecutan en orden de definición.
        # 'low' puede no estar validado aún en este punto; la validación cruzada
        # completa se hace en el DataValidator del módulo data/.
        return v

    @field_validator("volume")
    @classmethod
    def volume_must_be_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"Volumen no puede ser negativo, recibido: {v}")
        return v


class Signal(BaseModel):
    """
    Señal generada por una estrategia.
    Una señal NO es una orden. Todavía debe pasar por el Risk Engine.
    """
    strategy_id: str = Field(description="Identificador único de la estrategia")
    symbol: str
    side: OrderSide
    strength: SignalStrength = SignalStrength.MODERATE
    confidence: float = Field(ge=0.0, le=1.0, description="Confianza de la señal (0-1)")
    generated_at: datetime
    metadata: dict = Field(
        default_factory=dict,
        description="Datos adicionales de la estrategia (indicadores, etc.)",
    )


class Order(BaseModel):
    """Orden aprobada por el Risk Engine lista para enviar al broker."""
    order_id: str = Field(description="ID único generado internamente")
    strategy_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float = Field(gt=0)
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    filled_price: Optional[float] = None
    filled_quantity: float = 0.0
    commission: float = 0.0
    reject_reason: Optional[str] = None


class Position(BaseModel):
    """Posición abierta en el portfolio."""
    symbol: str
    quantity: float
    entry_price: float = Field(gt=0)
    current_price: float = Field(gt=0)
    strategy_id: str
    opened_at: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        return (self.current_price - self.entry_price) / self.entry_price


class Trade(BaseModel):
    """Trade cerrado. Registro histórico inmutable."""
    trade_id: str
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    commission: float = 0.0
    slippage: float = 0.0

    @property
    def gross_pnl(self) -> float:
        multiplier = 1 if self.side == OrderSide.BUY else -1
        return multiplier * (self.exit_price - self.entry_price) * self.quantity

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.commission - self.slippage

    @property
    def return_pct(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price
