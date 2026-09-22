"""Tests del sistema de logging y alertas."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from monitoring.alert_manager import AlertLevel, AlertManager
from monitoring.health_checker import HealthChecker, HealthStatus


class TestAlertManager:
    def test_send_info_alert(self):
        manager = AlertManager()
        manager.info("Sistema arrancado", "El sistema ha iniciado correctamente")
        assert len(manager.recent_alerts) == 1
        assert manager.recent_alerts[0].level == AlertLevel.INFO

    def test_send_critical_alert(self):
        manager = AlertManager()
        manager.critical("Circuit breaker", "Drawdown máximo superado", drawdown=0.16)
        assert manager.recent_alerts[0].level == AlertLevel.CRITICAL

    def test_recent_alerts_limited_to_50(self):
        manager = AlertManager()
        for i in range(60):
            manager.info(f"Alert {i}", "message")
        assert len(manager.recent_alerts) == 50

    def test_metadata_stored(self):
        manager = AlertManager()
        manager.warning("Test", "mensaje", symbol="AAPL", order_id="123")
        alert = manager.recent_alerts[0]
        assert alert.metadata["symbol"] == "AAPL"
        assert alert.metadata["order_id"] == "123"


class TestHealthChecker:
    def test_unknown_when_no_data_received(self):
        checker = HealthChecker()
        health = checker.check_data_freshness()
        assert health.status == HealthStatus.UNKNOWN

    def test_ok_with_fresh_data(self):
        checker = HealthChecker(max_data_staleness_seconds=60)
        checker.record_data_received(datetime.utcnow())
        health = checker.check_data_freshness()
        assert health.status == HealthStatus.OK

    def test_critical_with_stale_data(self):
        checker = HealthChecker(max_data_staleness_seconds=60)
        stale_time = datetime.utcnow() - timedelta(seconds=120)
        checker.record_data_received(stale_time)
        health = checker.check_data_freshness()
        assert health.status == HealthStatus.CRITICAL

    def test_overall_status_critical_if_any_critical(self):
        checker = HealthChecker(max_data_staleness_seconds=1)
        stale_time = datetime.utcnow() - timedelta(seconds=120)
        checker.record_data_received(stale_time)
        checker.run_all_checks()
        assert checker.overall_status == HealthStatus.CRITICAL

    def test_overall_status_unknown_when_no_checks(self):
        checker = HealthChecker()
        assert checker.overall_status == HealthStatus.UNKNOWN
