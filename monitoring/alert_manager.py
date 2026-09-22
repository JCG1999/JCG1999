"""
Sistema de alertas para eventos críticos del sistema.

Niveles de alerta:
- INFO: eventos normales notables (sistema arrancado, estrategia activada)
- WARNING: anomalías no críticas (datos tardíos, orden rechazada por riesgo)
- CRITICAL: eventos que requieren atención inmediata (circuit breaker activado,
            error de conexión con broker, drawdown límite alcanzado)

Por diseño, las alertas CRITICAL también detienen el sistema automáticamente
si el circuit breaker correspondiente está configurado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from monitoring.logger import get_logger

logger = get_logger(__name__)


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    level: AlertLevel
    title: str
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


class AlertManager:
    """
    Gestiona el envío de alertas a los canales configurados.
    Los canales se añaden en la inicialización según la configuración.
    Si un canal falla, se loguea el error pero no se detiene el sistema.
    """

    def __init__(self, telegram_token: str = "", telegram_chat_id: str = "") -> None:
        self._telegram_token = telegram_token
        self._telegram_chat_id = telegram_chat_id
        self._alert_history: list[Alert] = []

    def send(self, level: AlertLevel, title: str, message: str, **metadata) -> None:
        alert = Alert(
            level=level,
            title=title,
            message=message,
            metadata=metadata,
        )
        self._alert_history.append(alert)

        log_msg = f"[{level.value}] {title}: {message}"
        if level == AlertLevel.CRITICAL:
            logger.critical(log_msg, **metadata)
        elif level == AlertLevel.WARNING:
            logger.warning(log_msg, **metadata)
        else:
            logger.info(log_msg, **metadata)

        if self._telegram_token and self._telegram_chat_id:
            self._send_telegram(alert)

    def info(self, title: str, message: str, **metadata) -> None:
        self.send(AlertLevel.INFO, title, message, **metadata)

    def warning(self, title: str, message: str, **metadata) -> None:
        self.send(AlertLevel.WARNING, title, message, **metadata)

    def critical(self, title: str, message: str, **metadata) -> None:
        self.send(AlertLevel.CRITICAL, title, message, **metadata)

    def _send_telegram(self, alert: Alert) -> None:
        """Envía la alerta a Telegram. Falla silenciosamente si hay error."""
        try:
            import httpx

            emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(
                alert.level.value, ""
            )
            text = f"{emoji} *{alert.title}*\n{alert.message}\n_{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}_"

            with httpx.Client(timeout=5.0) as client:
                client.post(
                    f"https://api.telegram.org/bot{self._telegram_token}/sendMessage",
                    json={
                        "chat_id": self._telegram_chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                )
        except Exception as e:
            logger.error(f"Error enviando alerta Telegram: {e}")

    @property
    def recent_alerts(self) -> list[Alert]:
        return self._alert_history[-50:]
