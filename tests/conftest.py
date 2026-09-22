"""
Fixtures compartidos por todos los tests.

Por qué conftest.py:
- pytest lo descubre automáticamente y lo aplica a todos los tests del directorio.
- Centraliza la creación de objetos compartidos (settings, DB en memoria, etc.).
- Evita duplicación: si cambia la forma de construir un objeto, se cambia aquí.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Forzar entorno de test antes de importar settings
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("DATABASE__URL", "sqlite:///:memory:")


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """
    Limpia el cache de get_settings() antes de cada test.
    Sin esto, cambios en variables de entorno dentro de un test
    no afectan a la instancia de Settings ya cacheada.
    """
    from config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings():
    from config.settings import get_settings
    return get_settings()


@pytest.fixture
def sample_ohlcv_data():
    """Datos OHLCV de ejemplo para tests. Representan 5 barras diarias."""
    from config.schemas import OHLCV
    return [
        OHLCV(
            symbol="TEST",
            timestamp=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
            open=100.0 + i,
            high=105.0 + i,
            low=98.0 + i,
            close=103.0 + i,
            volume=1_000_000.0,
        )
        for i in range(5)
    ]


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Directorio temporal para tests que escriben archivos."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir
