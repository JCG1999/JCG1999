# Robot de Trading Algorítmico

Sistema de trading algorítmico profesional, modular y orientado al control de riesgo.

## Estado actual

**Fase 0 — Fundamentos**: Estructura, configuración y logging ✅

## Estructura del proyecto

```
algo-trading/
├── config/          # Configuración centralizada (Settings + Schemas)
├── data/            # Capa de datos: descarga, validación, normalización
├── storage/         # Persistencia: series temporales y datos relacionales
├── features/        # Feature engine: indicadores técnicos y estadísticos
├── strategies/      # Estrategias: lógica de señales (SOLO señales)
├── risk/            # Gestión de riesgo: pre-trade, sizing, circuit breakers
├── execution/       # Ejecución: order manager, broker adapters
├── portfolio/       # Portfolio: posiciones, P&L, contabilidad
├── metrics/         # Métricas de rendimiento: Sharpe, Drawdown, etc.
├── backtesting/     # Motor de backtesting: usa el mismo código que live
├── monitoring/      # Logging, alertas, health checks
├── dashboard/       # Panel de control (Streamlit)
├── tests/           # Tests por módulo
├── scripts/         # Scripts de utilidad
└── main.py          # Punto de entrada principal
```

## Setup inicial

```bash
# 1. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales (NUNCA subir .env a git)

# 4. Verificar el entorno
python scripts/check_environment.py

# 5. Ejecutar los tests
pytest

# 6. Arrancar el sistema
python main.py
```

## Principios de diseño

1. **Separación estricta de responsabilidades**: estrategia, riesgo, ejecución y datos son módulos independientes.
2. **Código compartido entre backtest y live**: el backtesting engine usa el mismo código de estrategia y riesgo que el sistema en producción.
3. **Riesgo primero**: ninguna orden puede ejecutarse sin pasar por el Pre-Trade Risk Engine.
4. **Secrets nunca en código**: todas las credenciales van en variables de entorno (`.env`).
5. **Fallar rápido**: la configuración inválida se detecta al arrancar, no durante la operación.
6. **Logs completos y auditables**: cada decisión del sistema queda registrada.

## Marco de validación de estrategias

Una estrategia debe pasar estos pasos **en orden** antes de operar con dinero real:

1. **Hipótesis** → formulada por escrito, con razón económica
2. **Backtest in-sample** → métricas mínimas: Sharpe > 0.8, MaxDD < 25%, > 100 trades
3. **Validación OOS** → parámetros congelados, métricas degradan < 40%
4. **Walk-forward analysis** → consistencia en múltiples períodos
5. **Paper trading** → mínimo 30 días / 30 trades en simulación real
6. **Live con capital mínimo** → verificación de infraestructura real
7. **Escalado progresivo** → incrementos máximos del 50%, separados 30 días

## Roadmap

- [x] Fase 0: Estructura, configuración, logging
- [ ] Fase 1: Capa de datos (provider, validator, storage)
- [ ] Fase 2: Feature engine + backtesting básico
- [ ] Fase 3: Risk management + validación OOS
- [ ] Fase 4: Ejecución paper trading
- [ ] Fase 5: Live trading con capital mínimo
- [ ] Fase 6: Escalabilidad (Docker, cloud, múltiples estrategias)
