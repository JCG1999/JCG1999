"""
Script de verificación del entorno de desarrollo.

Ejecutar después de instalar dependencias:
    python scripts/check_environment.py

Verifica que todas las librerías críticas están instaladas
y que la configuración básica es correcta.
"""
from __future__ import annotations

import sys


def check_python_version():
    version = sys.version_info
    ok = version >= (3, 11)
    status = "OK" if ok else "FALLO"
    print(f"  [{status}] Python {version.major}.{version.minor}.{version.micro} (requerido: 3.11+)")
    return ok


def check_import(module_name: str, display_name: str | None = None) -> bool:
    name = display_name or module_name
    try:
        __import__(module_name)
        print(f"  [OK] {name}")
        return True
    except ImportError as e:
        print(f"  [FALLO] {name}: {e}")
        return False


def check_config():
    try:
        from config.settings import get_settings
        s = get_settings()
        print(f"  [OK] Configuración cargada (entorno: {s.environment})")
        return True
    except Exception as e:
        print(f"  [FALLO] Configuración: {e}")
        return False


def main():
    print("\n" + "=" * 50)
    print("Verificación del entorno de trading")
    print("=" * 50)

    results = []

    print("\n--- Python ---")
    results.append(check_python_version())

    print("\n--- Librerías core ---")
    for mod, name in [
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("pydantic", "pydantic"),
        ("pydantic_settings", "pydantic-settings"),
        ("loguru", "loguru"),
        ("sqlalchemy", "SQLAlchemy"),
        ("dotenv", "python-dotenv"),
        ("yaml", "PyYAML"),
        ("httpx", "httpx"),
    ]:
        results.append(check_import(mod, name))

    print("\n--- Librerías de trading ---")
    for mod, name in [
        ("pandas_ta", "pandas-ta"),
        ("yfinance", "yfinance"),
    ]:
        results.append(check_import(mod, name))

    print("\n--- Testing ---")
    results.append(check_import("pytest", "pytest"))
    results.append(check_import("freezegun", "freezegun"))

    print("\n--- Configuración del sistema ---")
    results.append(check_config())

    print("\n" + "=" * 50)
    if all(results):
        print("Todo correcto. El entorno está listo.")
    else:
        failed = results.count(False)
        print(f"{failed} verificación(es) fallaron. Revisar los errores anteriores.")
        print("Instalar dependencias con: pip install -r requirements.txt")
        sys.exit(1)
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
