"""
Sistema de configuración centralizado.

Carga configuración en este orden (mayor prioridad primero):
1. Variables de entorno del sistema
2. Archivo .env en el directorio raíz
3. Valores por defecto definidos en el schema

Por qué este diseño:
- Los secrets NUNCA están en código ni en git. Solo en variables de entorno.
- Pydantic valida la configuración al arrancar, fallando rápido si falta algo.
- Un único punto de acceso (get_settings()) facilita el testing con mocks.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Directorio raíz del proyecto (un nivel arriba de config/)
ROOT_DIR = Path(__file__).parent.parent


class DatabaseSettings(BaseSettings):
    url: str = Field(
        default="sqlite:///data/trading.db",
        description="URL de conexión a la base de datos",
    )
    echo_sql: bool = Field(
        default=False,
        description="Loguear todas las queries SQL (solo para debugging)",
    )

    model_config = SettingsConfigDict(env_prefix="DATABASE_")


class AlpacaSettings(BaseSettings):
    api_key: str = Field(default="", description="Alpaca API Key")
    secret_key: str = Field(default="", description="Alpaca Secret Key")
    base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="URL base del broker. paper-api para paper trading",
    )

    model_config = SettingsConfigDict(env_prefix="ALPACA_")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        allowed = {
            "https://paper-api.alpaca.markets",
            "https://api.alpaca.markets",
        }
        if v not in allowed:
            raise ValueError(f"base_url debe ser una de: {allowed}")
        return v


class TelegramSettings(BaseSettings):
    bot_token: str = Field(default="", description="Token del bot de Telegram")
    chat_id: str = Field(default="", description="Chat ID de destino de alertas")

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)


class RiskSettings(BaseSettings):
    """
    Límites de riesgo globales del sistema.
    Estos valores son la última línea de defensa.
    Una estrategia puede tener sus propios límites más estrictos,
    pero nunca puede superar estos límites globales.
    """
    max_portfolio_risk_pct: float = Field(
        default=0.02,
        ge=0.001,
        le=0.1,
        description="Riesgo máximo por operación como % del portfolio (default 2%)",
    )
    max_daily_loss_pct: float = Field(
        default=0.03,
        ge=0.001,
        le=0.2,
        description="Pérdida máxima diaria permitida como % del portfolio (default 3%)",
    )
    max_drawdown_pct: float = Field(
        default=0.15,
        ge=0.01,
        le=0.5,
        description="Drawdown máximo desde el pico antes de detener el sistema (default 15%)",
    )
    max_position_size_pct: float = Field(
        default=0.10,
        ge=0.01,
        le=0.5,
        description="Tamaño máximo de una sola posición como % del portfolio (default 10%)",
    )
    max_open_positions: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Número máximo de posiciones abiertas simultáneamente",
    )

    model_config = SettingsConfigDict(env_prefix="RISK_")


class Settings(BaseSettings):
    """
    Configuración raíz del sistema.
    Se instancia una sola vez y se reutiliza via get_settings().
    """
    environment: Literal["development", "paper", "live"] = Field(
        default="development",
        description="Entorno de ejecución. 'live' requiere confirmación explícita.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
    )

    # Sub-configuraciones anidadas
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    alpaca: AlpacaSettings = Field(default_factory=AlpacaSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)

    # Rutas del proyecto
    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    logs_dir: Path = ROOT_DIR / "logs"
    reports_dir: Path = ROOT_DIR / "reports"

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    def model_post_init(self, __context: object) -> None:
        """Crea directorios necesarios si no existen."""
        for directory in [self.data_dir, self.logs_dir, self.reports_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def is_live(self) -> bool:
        return self.environment == "live"

    @property
    def is_paper(self) -> bool:
        return self.environment == "paper"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Retorna la instancia singleton de Settings.
    lru_cache garantiza que solo se instancia una vez en todo el proceso.
    En tests, usa: get_settings.cache_clear() para resetear entre tests.
    """
    return Settings()
