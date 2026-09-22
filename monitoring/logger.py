"""
Sistema de logging centralizado.

Por qué loguru en lugar del logging estándar de Python:
- Sintaxis más simple y menos boilerplate.
- Logs estructurados en JSON natively (crítico para análisis posterior).
- Rotación de archivos integrada.
- Niveles de color automáticos en terminal.

Cada módulo obtiene su logger con: logger = get_logger(__name__)
El contexto del módulo se incluye automáticamente en cada línea de log.

Por qué logs estructurados (JSON):
- Permiten búsquedas eficientes: "dame todas las órdenes rechazadas del símbolo AAPL"
- Pueden enviarse a sistemas de agregación (Grafana, ELK) sin parsear texto
- Son la base de las métricas de auditoría
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _loguru_logger


def setup_logging(log_level: str = "INFO", logs_dir: Path | None = None) -> None:
    """
    Configura el sistema de logging para todo el proceso.
    Debe llamarse una sola vez al arrancar la aplicación.

    Crea dos sinks:
    1. Consola: formato legible por humanos, con colores
    2. Archivo: formato JSON estructurado, con rotación diaria
    """
    _loguru_logger.remove()  # Elimina el handler por defecto

    # Sink 1: consola — legible por humanos
    _loguru_logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # Sink 2: archivo JSON — para auditoría y análisis
    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        _loguru_logger.add(
            logs_dir / "trading_{time:YYYY-MM-DD}.log",
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} | {message} | {extra}",
            rotation="00:00",       # Nuevo archivo cada día a medianoche
            retention="90 days",    # Guardar logs de los últimos 90 días
            compression="gz",       # Comprimir logs antiguos
            serialize=True,         # Formato JSON
            enqueue=True,           # Thread-safe: escritura asíncrona
            backtrace=True,
            diagnose=False,         # Sin detalles de variables en producción
        )


def get_logger(name: str):
    """
    Retorna un logger con el nombre del módulo como contexto.

    Uso:
        logger = get_logger(__name__)
        logger.info("Orden enviada", order_id="abc123", symbol="AAPL")
    """
    return _loguru_logger.bind(module=name)
