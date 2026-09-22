"""
Punto de entrada principal del robot de trading.

Ciclo de vida:
1. Carga y valida configuración.
2. Inicializa logging.
3. Verifica que el entorno es el correcto (development/paper/live).
4. Arranca los componentes en orden.
5. Ejecuta el loop principal.
6. Maneja señales de parada limpia (SIGTERM, SIGINT).

Por qué un main.py explícito:
- Centraliza el arranque. Un único punto donde todo empieza.
- Facilita la parada limpia: capturamos señales del OS.
- Permite verificar el entorno ANTES de que cualquier componente se conecte al broker.
"""
from __future__ import annotations

import signal
import sys
from typing import NoReturn

from config.settings import get_settings
from monitoring.logger import get_logger, setup_logging

logger = get_logger(__name__)

_shutdown_requested = False


def _handle_shutdown(signum: int, frame: object) -> None:
    """Captura SIGTERM y SIGINT para parada limpia."""
    global _shutdown_requested
    logger.warning(f"Señal de parada recibida (signal={signum}). Iniciando shutdown limpio...")
    _shutdown_requested = True


def _check_live_confirmation(settings) -> None:
    """
    Doble verificación antes de operar en real.
    El sistema no puede arrancarse en modo 'live' por accidente.
    """
    if settings.is_live:
        print("\n" + "=" * 60)
        print("ATENCIÓN: El sistema está configurado para operar en REAL.")
        print("Esto implicará uso de dinero real.")
        print("=" * 60)
        confirmation = input("Escribe 'CONFIRMO OPERAR EN REAL' para continuar: ")
        if confirmation.strip() != "CONFIRMO OPERAR EN REAL":
            print("Confirmación incorrecta. Sistema detenido.")
            sys.exit(0)


def main() -> None:
    settings = get_settings()

    setup_logging(
        log_level=settings.log_level,
        logs_dir=settings.logs_dir,
    )

    logger.info(
        "Sistema de trading iniciando",
        environment=settings.environment,
        log_level=settings.log_level,
    )

    _check_live_confirmation(settings)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    logger.info("Sistema listo. Loop principal pendiente de implementación (Fase 4).")
    logger.info(
        "Configuración de riesgo cargada",
        max_risk_per_trade=f"{settings.risk.max_portfolio_risk_pct*100}%",
        max_daily_loss=f"{settings.risk.max_daily_loss_pct*100}%",
        max_drawdown=f"{settings.risk.max_drawdown_pct*100}%",
    )

    # El loop principal se implementará en Fase 4 (Ejecución)
    # Por ahora, el sistema arranca, valida configuración y termina limpiamente.
    logger.info("Sistema detenido limpiamente.")


if __name__ == "__main__":
    main()
