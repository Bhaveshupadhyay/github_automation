"""Unit tests for LifecycleSupervisorService: decryption, DB strategy injection, and health orchestration."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from automation.domain.lifecycle import ServiceStatus
from automation.interfaces.database_strategy_interface import IDatabaseStrategy
from automation.interfaces.health_check_interface import IHealthCheckService
from automation.interfaces.process_tree_interface import IProcessTreeManager
from automation.interfaces.qa_contract_interface import IQAContractValidatorService
from automation.interfaces.sops_interface import ISOpsService
from automation.services.lifecycle_supervisor_service import (
    LifecycleSupervisorService,
    parse_dotenv_string,
)
from automation.domain.qa_contract import QAContract
from automation.domain.database_strategy import MigrationResult


class TestLifecycleSupervisor(unittest.TestCase):
    """Verifies service orchestration, SOPS halting, health polling timeouts, and process cleanup."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.backend_dir = Path(self.temp_dir.name) / "backend"
        self.backend_dir.mkdir(parents=True, exist_ok=True)
        self.frontend_dir = Path(self.temp_dir.name) / "frontend"
        self.frontend_dir.mkdir(parents=True, exist_ok=True)

        # Create valid backend contract
        self.backend_contract_data = {
            "serviceType": "backend",
            "port": 8000,
            "healthCheckUrl": "http://localhost:8000/health",
            "lifecycle": {
                "start": "python -m uvicorn main:app --port 8000",
                "prepare": "python -c 'print(\"DB migrated\")'",
            },
        }
        (self.backend_dir / "qa-contract.json").write_text(json.dumps(self.backend_contract_data))

        # Create valid frontend contract
        self.frontend_contract_data = {
            "serviceType": "frontend",
            "port": 3000,
            "healthCheckUrl": "http://localhost:3000",
            "apiBaseUrlEnvVar": "NEXT_PUBLIC_API_BASE_URL",
            "lifecycle": {
                "start": "npm run start -- -p 3000",
            },
        }
        (self.frontend_dir / "qa-contract.json").write_text(json.dumps(self.frontend_contract_data))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_parse_dotenv_string(self) -> None:
        """Parses exported and plain dotenv variables with quotes stripped."""
        dotenv_content = """
        # Comment line
        DATABASE_URL="postgres://user:pass@host/db"
        export API_KEY='secret123'
        DEBUG=true
        EMPTY=
        """
        env = parse_dotenv_string(dotenv_content)
        self.assertEqual(env["DATABASE_URL"], "postgres://user:pass@host/db")
        self.assertEqual(env["API_KEY"], "secret123")
        self.assertEqual(env["DEBUG"], "true")
        self.assertEqual(env["EMPTY"], "")

    def test_missing_or_invalid_sops_key_halts_supervisor(self) -> None:
        """Missing or invalid SOPS key halts supervisor before launching any service."""
        # Create encrypted file marker
        (self.backend_dir / ".env.qa.enc").write_text("DUMMY_ENCRYPTED_DATA")

        mock_sops = MagicMock(spec=ISOpsService)
        mock_sops.decrypt_file.side_effect = ValueError("Decryption failed: Neither age_private_key was supplied nor SOPS_AGE_KEY environment variable is set.")

        mock_tree = MagicMock(spec=IProcessTreeManager)
        mock_validator = MagicMock(spec=IQAContractValidatorService)
        mock_health = MagicMock(spec=IHealthCheckService)

        supervisor = LifecycleSupervisorService(
            sops_service=mock_sops,
            qa_contract_validator=mock_validator,
            health_check_service=mock_health,
            process_tree_manager=mock_tree,
        )

        result = supervisor.start_services(backend_dir=self.backend_dir)

        self.assertFalse(result.success)
        self.assertIn("SOPS Decryption Error", result.error_message)
        # Ensure no process was spawned
        mock_tree.spawn_service_process.assert_not_called()

    def test_deliberately_failing_backend_times_out_and_cleans_up(self) -> None:
        """Failing backend health check triggers timeout error, halts supervisor, and terminates processes."""
        mock_sops = MagicMock(spec=ISOpsService)
        mock_validator = MagicMock(spec=IQAContractValidatorService)
        mock_validator.validate_contract_file.return_value = QAContract.model_validate(self.backend_contract_data)

        mock_health = MagicMock(spec=IHealthCheckService)
        mock_health.poll_health.return_value = False  # Deliberately failing health check

        mock_tree = MagicMock(spec=IProcessTreeManager)
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_tree.spawn_service_process.return_value = mock_proc

        supervisor = LifecycleSupervisorService(
            sops_service=mock_sops,
            qa_contract_validator=mock_validator,
            health_check_service=mock_health,
            process_tree_manager=mock_tree,
        )

        result = supervisor.start_services(
            backend_dir=self.backend_dir,
            backend_health_timeout=2.0,
        )

        self.assertFalse(result.success)
        self.assertIn("Backend health check timed out", result.error_message)
        self.assertEqual(result.backend_info.status, ServiceStatus.UNHEALTHY)
        # Verify termination was invoked
        mock_tree.terminate_all.assert_called_once()
        mock_tree.shred_transient_files.assert_called_once()

    def test_database_migration_failure_halts_startup(self) -> None:
        """Failing database migration aborts startup before launching backend service."""
        mock_sops = MagicMock(spec=ISOpsService)
        mock_validator = MagicMock(spec=IQAContractValidatorService)
        mock_validator.validate_contract_file.return_value = QAContract.model_validate(self.backend_contract_data)

        mock_db = MagicMock(spec=IDatabaseStrategy)
        mock_db.get_connection_env.return_value = {"DATABASE_URL": "postgres://test"}
        mock_db.run_migrations.return_value = MigrationResult(
            success=False,
            command="alembic upgrade head",
            exit_code=1,
            output="Relation already exists",
            duration_seconds=0.5,
        )

        mock_tree = MagicMock(spec=IProcessTreeManager)
        mock_health = MagicMock(spec=IHealthCheckService)

        supervisor = LifecycleSupervisorService(
            sops_service=mock_sops,
            qa_contract_validator=mock_validator,
            health_check_service=mock_health,
            process_tree_manager=mock_tree,
        )

        result = supervisor.start_services(
            backend_dir=self.backend_dir,
            db_strategy=mock_db,
        )

        self.assertFalse(result.success)
        self.assertIn("Database migration/prepare command failed", result.error_message)
        mock_tree.spawn_service_process.assert_not_called()

    def test_successful_startup_backend_and_frontend(self) -> None:
        """Both backend and frontend start successfully, health probes return True, and URL is injected."""
        # Create encrypted file to test decryption flow
        (self.backend_dir / ".env.qa.enc").write_text("ENC_DUMMY")

        mock_sops = MagicMock(spec=ISOpsService)
        mock_sops.decrypt_file.return_value = "DATABASE_URL=postgres://cloud-dev:5432/app\nSECRET_KEY=qa-secret"

        mock_validator = MagicMock(spec=IQAContractValidatorService)
        mock_validator.validate_contract_file.side_effect = [
            QAContract.model_validate(self.backend_contract_data),
            QAContract.model_validate(self.frontend_contract_data),
        ]

        mock_health = MagicMock(spec=IHealthCheckService)
        mock_health.poll_health.return_value = True

        mock_tree = MagicMock(spec=IProcessTreeManager)
        mock_be_proc = MagicMock()
        mock_be_proc.pid = 1001
        mock_fe_proc = MagicMock()
        mock_fe_proc.pid = 1002

        mock_tree.spawn_service_process.side_effect = [mock_be_proc, mock_fe_proc]

        supervisor = LifecycleSupervisorService(
            sops_service=mock_sops,
            qa_contract_validator=mock_validator,
            health_check_service=mock_health,
            process_tree_manager=mock_tree,
        )

        result = supervisor.start_services(
            backend_dir=self.backend_dir,
            frontend_dir=self.frontend_dir,
        )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.backend_info)
        self.assertIsNotNone(result.frontend_info)
        self.assertEqual(result.backend_info.status, ServiceStatus.HEALTHY)
        self.assertEqual(result.frontend_info.status, ServiceStatus.HEALTHY)
        self.assertEqual(result.backend_info.port, 8000)
        self.assertEqual(result.frontend_info.port, 3000)

        # Verify frontend was spawned with injected backend URL
        fe_call_args = mock_tree.spawn_service_process.call_args_list[1]
        fe_env = fe_call_args.kwargs.get("env") or fe_call_args[0][2]
        self.assertEqual(fe_env.get("NEXT_PUBLIC_API_BASE_URL"), "http://localhost:8000")

    def test_live_concurrent_health_verification(self) -> None:
        """Starts real live HTTP services on separate ports and confirms both return HTTP 200 simultaneously."""
        import sys
        import urllib.request

        be_dir = Path(self.temp_dir.name) / "live_be"
        be_dir.mkdir(parents=True, exist_ok=True)
        fe_dir = Path(self.temp_dir.name) / "live_fe"
        fe_dir.mkdir(parents=True, exist_ok=True)

        be_port = 8991
        fe_port = 3991

        be_contract = {
            "serviceType": "backend",
            "port": be_port,
            "healthCheckUrl": f"http://localhost:{be_port}/",
            "lifecycle": {
                "start": f"exec {sys.executable} -m http.server {be_port}",
            },
        }
        (be_dir / "qa-contract.json").write_text(json.dumps(be_contract))

        fe_contract = {
            "serviceType": "frontend",
            "port": fe_port,
            "healthCheckUrl": f"http://localhost:{fe_port}/",
            "apiBaseUrlEnvVar": "API_URL",
            "lifecycle": {
                "start": f"exec {sys.executable} -m http.server {fe_port}",
            },
        }
        (fe_dir / "qa-contract.json").write_text(json.dumps(fe_contract))

        # Real supervisor with real ProcessTreeManager and HealthCheckService
        supervisor = LifecycleSupervisorService()
        try:
            result = supervisor.start_services(
                backend_dir=be_dir,
                frontend_dir=fe_dir,
                backend_health_timeout=10.0,
                frontend_health_timeout=10.0,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.backend_info.status, ServiceStatus.HEALTHY)
            self.assertEqual(result.frontend_info.status, ServiceStatus.HEALTHY)

            # Confirm both endpoints return HTTP 200 simultaneously
            with urllib.request.urlopen(f"http://localhost:{be_port}/", timeout=2.0) as be_resp:
                self.assertEqual(be_resp.getcode(), 200)

            with urllib.request.urlopen(f"http://localhost:{fe_port}/", timeout=2.0) as fe_resp:
                self.assertEqual(fe_resp.getcode(), 200)
        finally:
            supervisor.terminate_all()


if __name__ == "__main__":
    unittest.main()

