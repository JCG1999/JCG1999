"""
Orquestador del pipeline de ingestión de datos.

Pipeline completo por símbolo:
  1. Fetch → proveedor de datos
  2. Validate → detector de anomalías y datos corruptos
  3. Normalize → conversión a objetos OHLCV tipados
  4. Store → persistencia en base de datos
  5. Log → registro de auditoría de la ingestión

Por qué un Ingestor separado en lugar de llamar directamente al provider:
- Garantiza que NUNCA entra un dato sin validar al storage
- Centraliza el logging de auditoría de ingestiones
- Facilita agregar pasos al pipeline (e.g., enriquecimiento con datos corporativos)
- Permite cambiar el proveedor sin cambiar el pipeline

Decisión de diseño — qué hacer si la validación detecta errores:
- Si tiene errores Y los datos limpios son suficientes: continúa con los datos limpios,
  logea los errores, registra en el ingestion log
- Si los datos están completamente corruptos: aborta la ingestión del símbolo,
  registra el fallo, continúa con el siguiente símbolo
- Nunca detiene la ingestión de otros símbolos por el fallo de uno
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from data.normalizer import DataNormalizer
from data.providers.base import DataProvider, DataProviderError
from data.validators import DataValidator
from monitoring.logger import get_logger
from storage.database import Database
from storage.repository import TradingRepository
from storage.timeseries import TimeSeriesRepository

logger = get_logger(__name__)


@dataclass
class IngestionSummary:
    """Resultado de una ingestión de un símbolo."""
    symbol: str
    interval: str
    success: bool
    bars_downloaded: int = 0
    bars_stored: int = 0
    had_validation_errors: bool = False
    had_validation_warnings: bool = False
    error_message: Optional[str] = None


@dataclass
class BatchIngestionResult:
    """Resultado de una ingestión de múltiples símbolos."""
    summaries: list[IngestionSummary] = field(default_factory=list)

    @property
    def total_bars_stored(self) -> int:
        return sum(s.bars_stored for s in self.summaries)

    @property
    def successful_symbols(self) -> list[str]:
        return [s.symbol for s in self.summaries if s.success]

    @property
    def failed_symbols(self) -> list[str]:
        return [s.symbol for s in self.summaries if not s.success]

    def print_summary(self) -> None:
        print(f"\n{'='*55}")
        print(f"{'RESUMEN DE INGESTIÓN':^55}")
        print(f"{'='*55}")
        print(f"  Símbolos procesados : {len(self.summaries)}")
        print(f"  Exitosos            : {len(self.successful_symbols)}")
        print(f"  Fallidos            : {len(self.failed_symbols)}")
        print(f"  Barras almacenadas  : {self.total_bars_stored:,}")
        if self.failed_symbols:
            print(f"  Fallidos            : {', '.join(self.failed_symbols)}")
        print(f"{'='*55}\n")
        for s in self.summaries:
            status = "OK " if s.success else "ERR"
            warn = "W" if s.had_validation_warnings else " "
            err  = "E" if s.had_validation_errors else " "
            print(f"  [{status}][{warn}{err}] {s.symbol:<12} "
                  f"{s.bars_stored:>6} barras almacenadas")
        print()


class DataIngestor:
    """
    Orquesta el pipeline completo de ingestión de datos de mercado.
    """

    def __init__(
        self,
        provider: DataProvider,
        db: Database,
        validator: Optional[DataValidator] = None,
        normalizer: Optional[DataNormalizer] = None,
    ) -> None:
        self._provider = provider
        self._ts_repo = TimeSeriesRepository(db)
        self._trade_repo = TradingRepository(db)
        self._validator = validator or DataValidator()
        self._normalizer = normalizer or DataNormalizer()

    def ingest(
        self,
        symbol: str,
        start: date,
        end: date,
        interval: str = "1d",
    ) -> IngestionSummary:
        """
        Ejecuta el pipeline completo para un símbolo.
        Nunca lanza excepciones al caller: los errores se capturan y se devuelven
        en el IngestionSummary para que el caller decida qué hacer.
        """
        logger.info(
            f"Iniciando ingestión: {symbol} [{interval}] {start} → {end}",
            symbol=symbol,
            interval=interval,
            start=str(start),
            end=str(end),
        )

        # Step 1: Fetch
        try:
            raw_df = self._provider.fetch_ohlcv(symbol, start, end, interval)
        except DataProviderError as e:
            logger.error(f"Error descargando {symbol}: {e}", symbol=symbol)
            summary = IngestionSummary(
                symbol=symbol,
                interval=interval,
                success=False,
                error_message=str(e),
            )
            self._log_ingestion(summary, start, end)
            return summary
        except Exception as e:
            logger.error(f"Error inesperado descargando {symbol}: {e}", symbol=symbol)
            summary = IngestionSummary(
                symbol=symbol,
                interval=interval,
                success=False,
                error_message=f"Error inesperado: {e}",
            )
            self._log_ingestion(summary, start, end)
            return summary

        bars_downloaded = len(raw_df)

        # Step 2: Validate
        validation_result = self._validator.validate(raw_df, symbol)

        if not validation_result.is_usable:
            logger.error(
                f"Datos de {symbol} no utilizables después de validación",
                symbol=symbol,
            )
            summary = IngestionSummary(
                symbol=symbol,
                interval=interval,
                success=False,
                bars_downloaded=bars_downloaded,
                had_validation_errors=True,
                error_message=f"Datos no utilizables: {validation_result.summary()}",
            )
            self._log_ingestion(summary, start, end)
            return summary

        # Step 3: Normalize
        ohlcv_list = self._normalizer.to_ohlcv_list(validation_result.clean_data, symbol)

        # Step 4: Store
        bars_stored = self._ts_repo.upsert_many(
            ohlcv_list,
            interval=interval,
            source=self._provider.name,
        )

        summary = IngestionSummary(
            symbol=symbol,
            interval=interval,
            success=True,
            bars_downloaded=bars_downloaded,
            bars_stored=bars_stored,
            had_validation_errors=validation_result.has_errors,
            had_validation_warnings=validation_result.has_warnings,
        )

        # Step 5: Log de auditoría
        self._log_ingestion(summary, start, end)

        logger.info(
            f"Ingestión completada: {symbol} → {bars_stored} barras",
            symbol=symbol,
            bars_stored=bars_stored,
            had_errors=validation_result.has_errors,
            had_warnings=validation_result.has_warnings,
        )
        return summary

    def ingest_batch(
        self,
        symbols: list[str],
        start: date,
        end: date,
        interval: str = "1d",
    ) -> BatchIngestionResult:
        """
        Ingesta múltiples símbolos.
        El fallo de un símbolo no interrumpe los demás.
        """
        result = BatchIngestionResult()
        total = len(symbols)

        for i, symbol in enumerate(symbols, 1):
            logger.info(f"Procesando {i}/{total}: {symbol}")
            summary = self.ingest(symbol, start, end, interval)
            result.summaries.append(summary)

        return result

    def _log_ingestion(
        self, summary: IngestionSummary, start: date, end: date
    ) -> None:
        try:
            self._trade_repo.log_ingestion(
                symbol=summary.symbol,
                interval=summary.interval,
                source=self._provider.name,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                bars_downloaded=summary.bars_downloaded,
                bars_stored=summary.bars_stored,
                had_errors=summary.had_validation_errors or not summary.success,
                had_warnings=summary.had_validation_warnings,
                error_summary=summary.error_message,
            )
        except Exception as e:
            logger.warning(f"No se pudo registrar log de ingestión: {e}")
