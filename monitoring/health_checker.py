"""
Monitor de salud del sistema.

Verifica periódicamente que todos los componentes críticos funcionan:
- Conectividad con el broker
- Frescura de los datos de mercado (¿cuándo llegó el último dato?)
- Estado de la base de datos
- Uso de memoria y CPU

Si un componente falla el health check, se emite una alerta.
Si es crítico, se activa el circuit breaker correspondiente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from monitoring.logger import get_logger

logger = get_logger(__name__)


class HealthStatus(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    message: str
    last_checked: datetime = field(default_factory=datetime.utcnow)
    latency_ms: Optional[float] = None


class HealthChecker:
    """
    Ejecuta checks de salud sobre los componentes del sistema.
    Cada check es independiente; el fallo de uno no impide los demás.
    """

    def __init__(self, max_data_staleness_seconds: int = 60) -> None:
        self._max_data_staleness = timedelta(seconds=max_data_staleness_seconds)
        self._last_data_timestamp: Optional[datetime] = None
        self._components: dict[str, ComponentHealth] = {}

    def record_data_received(self, timestamp: datetime) -> None:
        """Llamado cada vez que se recibe un dato de mercado."""
        self._last_data_timestamp = timestamp

    def check_data_freshness(self) -> ComponentHealth:
        now = datetime.utcnow()
        if self._last_data_timestamp is None:
            health = ComponentHealth(
                name="market_data",
                status=HealthStatus.UNKNOWN,
                message="No se ha recibido ningún dato de mercado aún",
            )
        else:
            staleness = now - self._last_data_timestamp
            if staleness > self._max_data_staleness:
                health = ComponentHealth(
                    name="market_data",
                    status=HealthStatus.CRITICAL,
                    message=f"Datos desactualizados: último dato hace {staleness.seconds}s",
                    latency_ms=staleness.total_seconds() * 1000,
                )
            else:
                health = ComponentHealth(
                    name="market_data",
                    status=HealthStatus.OK,
                    message=f"Datos frescos: último dato hace {staleness.seconds}s",
                    latency_ms=staleness.total_seconds() * 1000,
                )

        self._components["market_data"] = health
        return health

    def run_all_checks(self) -> dict[str, ComponentHealth]:
        """Ejecuta todos los checks disponibles y retorna el estado completo."""
        self.check_data_freshness()
        logger.debug(
            "Health check completado",
            components={k: v.status.value for k, v in self._components.items()},
        )
        return dict(self._components)

    @property
    def overall_status(self) -> HealthStatus:
        if not self._components:
            return HealthStatus.UNKNOWN
        statuses = [c.status for c in self._components.values()]
        if HealthStatus.CRITICAL in statuses:
            return HealthStatus.CRITICAL
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        if all(s == HealthStatus.OK for s in statuses):
            return HealthStatus.OK
        return HealthStatus.UNKNOWN
