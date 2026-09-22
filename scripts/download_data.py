"""
Script para descargar datos históricos y almacenarlos en la base de datos.

Uso:
    # Descargar activos por defecto (últimos 5 años)
    python scripts/download_data.py

    # Activos específicos
    python scripts/download_data.py --symbols AAPL MSFT TSLA

    # Rango de fechas específico
    python scripts/download_data.py --start 2019-01-01 --end 2024-01-01

    # Intervalo diferente
    python scripts/download_data.py --interval 1h --symbols BTC-USD ETH-USD

    # Ver qué datos tenemos en la DB
    python scripts/download_data.py --list

Activos por defecto: ETFs líquidos de referencia para el sistema inicial.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_settings
from data.ingestor import DataIngestor
from data.normalizer import DataNormalizer
from data.providers.yfinance_provider import YFinanceProvider
from data.validators import DataValidator
from monitoring.logger import setup_logging
from storage.database import get_database, reset_database
from storage.timeseries import TimeSeriesRepository

# Activos por defecto: mezcla de ETFs y acciones líquidas
# para probar el sistema con datos reales y representativos.
# No son recomendaciones de inversión.
DEFAULT_SYMBOLS = [
    # ETFs de referencia (benchmark)
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000
    # Acciones individuales líquidas
    "AAPL",  # Apple
    "MSFT",  # Microsoft
    "AMZN",  # Amazon
    # Volatilidad y sectores
    "GLD",   # Oro (ETF)
    "TLT",   # Bonos del Tesoro largo plazo
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Descarga datos históricos OHLCV y los almacena en la base de datos"
    )
    parser.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        help="Lista de símbolos a descargar (default: activos de referencia)",
    )
    parser.add_argument(
        "--start", type=str, default=None,
        help="Fecha de inicio en formato YYYY-MM-DD (default: 5 años atrás)",
    )
    parser.add_argument(
        "--end", type=str, default=None,
        help="Fecha de fin en formato YYYY-MM-DD (default: hoy)",
    )
    parser.add_argument(
        "--interval", type=str, default="1d",
        choices=["1d", "1h", "30m", "15m", "5m"],
        help="Intervalo temporal (default: 1d)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Muestra qué datos hay en la base de datos y sale",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Descarga aunque los datos ya existan en la DB (actualiza)",
    )
    return parser.parse_args()


def list_available_data(interval: str = "1d") -> None:
    db = get_database()
    ts_repo = TimeSeriesRepository(db)
    symbols = ts_repo.get_available_symbols(interval)

    if not symbols:
        print(f"\nNo hay datos almacenados para intervalo '{interval}'.")
        return

    print(f"\nDatos disponibles en la base de datos (intervalo: {interval}):")
    print(f"{'Símbolo':<12} {'Barras':>8} {'Desde':>12} {'Hasta':>12}")
    print("-" * 48)
    for symbol in symbols:
        count = ts_repo.count_bars(symbol, interval)
        latest = ts_repo.get_latest_timestamp(symbol, interval)
        from datetime import date as date_cls
        # Para 'desde' recuperamos 1 barra del principio
        df = ts_repo.fetch_range(symbol, date_cls(2000, 1, 1), date_cls(2030, 1, 1), interval)
        earliest = df.index.min().date() if not df.empty else "N/A"
        latest_date = latest.date() if latest else "N/A"
        print(f"{symbol:<12} {count:>8,} {str(earliest):>12} {str(latest_date):>12}")
    print()


def main():
    args = parse_args()
    settings = get_settings()
    setup_logging(log_level=settings.log_level, logs_dir=settings.logs_dir)

    if args.list:
        list_available_data(args.interval)
        return

    # Fechas
    end_date = date.today() if args.end is None else date.fromisoformat(args.end)
    if args.start is None:
        start_date = end_date - timedelta(days=365 * 5)
    else:
        start_date = date.fromisoformat(args.start)

    if start_date >= end_date:
        print(f"Error: start ({start_date}) debe ser anterior a end ({end_date})")
        sys.exit(1)

    print(f"\n{'='*55}")
    print(f"Descarga de datos históricos")
    print(f"{'='*55}")
    print(f"  Símbolos   : {', '.join(args.symbols)}")
    print(f"  Desde      : {start_date}")
    print(f"  Hasta      : {end_date}")
    print(f"  Intervalo  : {args.interval}")
    print(f"  Base datos : {settings.database.url}")
    print(f"{'='*55}\n")

    # Si no se fuerza la actualización, filtrar símbolos ya descargados
    symbols_to_download = args.symbols
    if not args.force:
        db = get_database()
        ts_repo = TimeSeriesRepository(db)
        skipped = []
        to_download = []
        for symbol in symbols_to_download:
            latest = ts_repo.get_latest_timestamp(symbol, args.interval)
            if latest and latest.date() >= end_date - timedelta(days=5):
                skipped.append(symbol)
            else:
                to_download.append(symbol)

        if skipped:
            print(f"  Símbolos ya actualizados (usa --force para re-descargar):")
            for s in skipped:
                print(f"    - {s}")
            print()

        symbols_to_download = to_download

    if not symbols_to_download:
        print("Todos los símbolos están actualizados. Usa --force para re-descargar.")
        return

    # Ejecutar ingestión
    reset_database()
    db = get_database()
    provider = YFinanceProvider(retry_attempts=3, retry_delay_seconds=2.0)
    ingestor = DataIngestor(
        provider=provider,
        db=db,
        validator=DataValidator(max_price_change_pct=0.50),  # más permisivo para crypto
        normalizer=DataNormalizer(),
    )

    result = ingestor.ingest_batch(symbols_to_download, start_date, end_date, args.interval)
    result.print_summary()

    if result.failed_symbols:
        print(f"ATENCIÓN: {len(result.failed_symbols)} símbolo(s) fallaron.")
        print("Revisar los logs para más detalle.")
        sys.exit(1)


if __name__ == "__main__":
    main()
