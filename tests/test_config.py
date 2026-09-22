"""
Tests del sistema de configuración.

Qué verificamos:
1. Los valores por defecto son correctos y seguros.
2. Las variables de entorno se cargan correctamente.
3. La validación rechaza valores inválidos.
4. Los directorios se crean automáticamente.
5. Los flags de entorno funcionan.
"""
from __future__ import annotations

import os

import pytest


class TestSettingsDefaults:
    def test_default_environment_is_development(self, settings):
        assert settings.environment == "development"

    def test_default_log_level_is_info(self, monkeypatch):
        # conftest fuerza LOG_LEVEL=DEBUG; quitamos esa var para probar el default real
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.log_level == "INFO"

    def test_is_development_flag(self, settings):
        assert settings.is_development is True
        assert settings.is_paper is False
        assert settings.is_live is False

    def test_risk_defaults_are_conservative(self, settings):
        risk = settings.risk
        assert risk.max_portfolio_risk_pct == 0.02   # 2% por operación
        assert risk.max_daily_loss_pct == 0.03        # 3% pérdida diaria
        assert risk.max_drawdown_pct == 0.15          # 15% drawdown máximo

    def test_alpaca_default_is_paper_url(self, settings):
        assert "paper-api" in settings.alpaca.base_url


class TestSettingsFromEnv:
    def test_environment_from_env(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "paper")
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.environment == "paper"
        assert s.is_paper is True

    def test_invalid_environment_raises(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "invalid_env")
        from config.settings import get_settings
        get_settings.cache_clear()
        with pytest.raises(Exception):
            get_settings()

    def test_risk_limits_from_env(self, monkeypatch):
        monkeypatch.setenv("RISK__MAX_DAILY_LOSS_PCT", "0.05")
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.risk.max_daily_loss_pct == 0.05

    def test_risk_limit_too_high_raises(self, monkeypatch):
        # max_daily_loss_pct tiene le=0.2 — no puede ser 0.5
        monkeypatch.setenv("RISK__MAX_DAILY_LOSS_PCT", "0.5")
        from config.settings import get_settings
        get_settings.cache_clear()
        with pytest.raises(Exception):
            get_settings()


class TestAlpacaSettings:
    def test_invalid_base_url_raises(self, monkeypatch):
        monkeypatch.setenv("ALPACA_BASE_URL", "https://evil.example.com")
        from config.settings import get_settings
        get_settings.cache_clear()
        with pytest.raises(Exception):
            get_settings()

    def test_paper_url_is_valid(self, monkeypatch):
        monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.alpaca.base_url == "https://paper-api.alpaca.markets"


class TestTelegramSettings:
    def test_is_configured_false_when_empty(self, settings):
        assert settings.telegram.is_configured is False

    def test_is_configured_true_when_set(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
        from config.settings import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.telegram.is_configured is True
