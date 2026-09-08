"""Unit tests for WireGuard service and adaptive AUTO database strategy resolution."""
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.domain.database_strategy import (
    DatabaseConfig,
    DatabaseStrategyType,
    NetworkProbeResult,
    WireGuardConfig,
)
from automation.services.database_strategies import (
    DevCloudDatabaseStrategy,
    EphemeralRunnerDatabaseStrategy,
    _extract_host_port,
    create_database_strategy,
)
from automation.services.wireguard_service import WireGuardService


class TestWireGuardService(unittest.TestCase):
    """Verifies WireGuard tunnel management, file shredding, and TCP socket probing."""

    def setUp(self) -> None:
        self.svc = WireGuardService(wg_quick_binary="wg-quick")

    def test_is_available_returns_bool(self) -> None:
        """Verifies is_available returns a boolean check."""
        self.assertIsInstance(self.svc.is_available(), bool)

    @patch("socket.create_connection")
    def test_probe_host_success(self, mock_create_conn) -> None:
        """Successful TCP handshake returns reachable=True with latency."""
        mock_conn = MagicMock()
        mock_create_conn.return_value = mock_conn

        result = self.svc.probe_host("my-azure-db.internal", 5432, timeout_seconds=2.0)

        self.assertTrue(result.reachable)
        self.assertEqual(result.host, "my-azure-db.internal")
        self.assertEqual(result.port, 5432)
        self.assertGreaterEqual(result.latency_ms, 0.0)
        self.assertIsNone(result.error_message)

    @patch("socket.create_connection", side_effect=socket.timeout("timed out"))
    def test_probe_host_timeout(self, mock_create_conn) -> None:
        """Socket timeout returns reachable=False and captures timeout error."""
        result = self.svc.probe_host("my-azure-db.internal", 5432, timeout_seconds=1.0)

        self.assertFalse(result.reachable)
        self.assertIn("timed out", result.error_message.lower())

    @patch("socket.create_connection", side_effect=ConnectionRefusedError("Connection refused"))
    def test_probe_host_connection_refused(self, mock_create_conn) -> None:
        """Connection refused returns reachable=False with error message."""
        result = self.svc.probe_host("127.0.0.1", 9999, timeout_seconds=1.0)

        self.assertFalse(result.reachable)
        self.assertIn("refused", result.error_message.lower())

    @patch.object(WireGuardService, "is_available", return_value=True)
    @patch("subprocess.run")
    def test_connect_with_raw_config_creates_secure_file(self, mock_run, mock_is_avail) -> None:
        """Raw WireGuard config is written to a temporary file with restrictive permissions."""
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res

        raw_conf = "[Interface]\nPrivateKey = secret=\nAddress = 10.0.0.2/32\n[Peer]\nPublicKey = pub="
        cfg = WireGuardConfig(raw_config=raw_conf, interface_name="wg_test0")

        success = self.svc.connect(cfg)

        self.assertTrue(success)
        self.assertEqual(self.svc._active_interface, "wg_test0")
        self.assertIsNotNone(self.svc._transient_config_path)
        self.assertTrue(self.svc._transient_config_path.exists())

        # Check permissions: only readable by owner (0o600)
        mode = oct(self.svc._transient_config_path.stat().st_mode & 0o777)
        self.assertEqual(mode, "0o600")

        # Disconnect and verify file is shredded and deleted
        self.svc.disconnect("wg_test0")
        self.assertIsNone(self.svc._transient_config_path)

    @patch.object(WireGuardService, "is_available", return_value=True)
    @patch("subprocess.run")
    def test_connect_failure_shreds_transient_config(self, mock_run, mock_is_avail) -> None:
        """If wg-quick up fails, transient config is shredded and deleted immediately."""
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stderr = "RTNETLINK answers: File exists"
        mock_run.return_value = mock_res

        cfg = WireGuardConfig(raw_config="[Interface]\nPrivateKey = secret=", interface_name="wg_fail")

        success = self.svc.connect(cfg)

        self.assertFalse(success)
        self.assertIsNone(self.svc._active_interface)
        self.assertIsNone(self.svc._transient_config_path)


class TestAutoDatabaseStrategyResolution(unittest.TestCase):
    """Verifies that AUTO strategy adapts: probes cloud DB, uses WireGuard if present, and falls back to local."""

    def test_extract_host_port_parses_uris(self) -> None:
        """Extracts host and port correctly from database connection URLs."""
        h, p = _extract_host_port("postgresql://user:pass@mydb.azure.com:5433/reels")
        self.assertEqual(h, "mydb.azure.com")
        self.assertEqual(p, 5433)

        h2, p2 = _extract_host_port("postgres://user:pass@mydb.internal/app")
        self.assertEqual(h2, "mydb.internal")
        self.assertEqual(p2, 5432)

        h3, p3 = _extract_host_port(None, default_host="fallback.host", default_port=5439)
        self.assertEqual(h3, "fallback.host")
        self.assertEqual(p3, 5439)

    def test_auto_strategy_resolves_cloud_dev_when_probe_succeeds(self) -> None:
        """When WireGuard connects and probe succeeds, CLOUD_DEV strategy is selected."""
        mock_wg_svc = MagicMock()
        mock_wg_svc.connect.return_value = True
        mock_wg_svc.probe_host.return_value = NetworkProbeResult(
            reachable=True,
            host="my-azure-db.internal",
            port=5432,
            latency_ms=12.5,
        )

        cfg = DatabaseConfig(
            strategy_type=DatabaseStrategyType.AUTO,
            connection_string="postgresql://user:pass@my-azure-db.internal:5432/reels",
            wireguard_config=WireGuardConfig(raw_config="[Interface]..."),
        )

        strategy = create_database_strategy(cfg, wireguard_service=mock_wg_svc)

        self.assertIsInstance(strategy, DevCloudDatabaseStrategy)
        self.assertEqual(strategy.connection_string, "postgresql://user:pass@my-azure-db.internal:5432/reels")
        mock_wg_svc.connect.assert_called_once()
        mock_wg_svc.probe_host.assert_called_once_with("my-azure-db.internal", 5432, timeout_seconds=2.0)

        # Verify teardown disconnects WireGuard
        strategy.teardown()
        mock_wg_svc.disconnect.assert_called_once()

    def test_auto_strategy_falls_back_to_ephemeral_when_probe_fails(self) -> None:
        """When WireGuard connection or TCP probe fails, AUTO gracefully falls back to EPHEMERAL_CONTAINER."""
        mock_wg_svc = MagicMock()
        mock_wg_svc.connect.return_value = True
        # Firewall blocks connection
        mock_wg_svc.probe_host.return_value = NetworkProbeResult(
            reachable=False,
            host="blocked-azure-db.internal",
            port=5432,
            error_message="Firewall timed out",
        )

        cfg = DatabaseConfig(
            strategy_type=DatabaseStrategyType.AUTO,
            connection_string="postgresql://user:pass@blocked-azure-db.internal:5432/reels",
            wireguard_config=WireGuardConfig(raw_config="[Interface]..."),
            database_name="reels_test",
        )

        strategy = create_database_strategy(cfg, wireguard_service=mock_wg_svc)

        # Must fall back to EphemeralRunnerDatabaseStrategy
        self.assertIsInstance(strategy, EphemeralRunnerDatabaseStrategy)
        self.assertEqual(strategy.host, "localhost")
        self.assertEqual(strategy.port, 5432)
        self.assertEqual(strategy.database_name, "reels_test")

        # Must disconnect the non-working WireGuard interface
        mock_wg_svc.disconnect.assert_called_once()

    def test_auto_strategy_falls_back_when_no_secrets_and_no_remote_db(self) -> None:
        """When no WireGuard secret exists and connection string is localhost, EPHEMERAL_CONTAINER is selected."""
        mock_wg_svc = MagicMock()

        cfg = DatabaseConfig(
            strategy_type=DatabaseStrategyType.AUTO,
            connection_string=None,
            host="localhost",
            port=5432,
            database_name="local_dev",
        )

        strategy = create_database_strategy(cfg, wireguard_service=mock_wg_svc)

        self.assertIsInstance(strategy, EphemeralRunnerDatabaseStrategy)
        self.assertEqual(strategy.database_name, "local_dev")
        # WireGuard was never touched
        mock_wg_svc.connect.assert_not_called()

    def test_di_wiring_resolves_wireguard_service(self) -> None:
        """Functional DI creates WireGuardService singleton and injects it into strategy."""
        from automation.core import get_database_strategy, get_wireguard_service

        wg = get_wireguard_service()
        self.assertIsInstance(wg, WireGuardService)

        strat = get_database_strategy()
        self.assertIsInstance(strat, DevCloudDatabaseStrategy)


if __name__ == "__main__":
    unittest.main()
