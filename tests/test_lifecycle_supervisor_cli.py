"""Unit tests for automation.lifecycle_supervisor_cli."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.domain.lifecycle import LifecycleResult, ServiceProcessInfo, ServiceStatus
from automation.lifecycle_supervisor_cli import main


class TestLifecycleSupervisorCLI(unittest.TestCase):
    """Verifies CLI argument parsing, flags, and exit codes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.backend_dir = Path(self.temp_dir.name) / "backend"
        self.backend_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("sys.argv", ["lifecycle_supervisor_cli", "--help"])
    def test_cli_help(self) -> None:
        """--help exits cleanly with return code 0."""
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", new_callable=io.StringIO):
                main()
        self.assertEqual(cm.exception.code, 0)

    @patch("automation.lifecycle_supervisor_cli.get_lifecycle_supervisor")
    def test_cli_check_only_success(self, mock_get_sup) -> None:
        """--check-only flag starts services, validates health, calls terminate_all, and exits 0."""
        mock_sup = MagicMock()
        mock_get_sup.return_value = mock_sup

        mock_sup.start_services.return_value = LifecycleResult(
            success=True,
            backend_info=ServiceProcessInfo(
                name="backend",
                pid=1234,
                port=8000,
                health_url="http://localhost:8000/health",
                status=ServiceStatus.HEALTHY,
                start_command="python -m uvicorn",
            ),
            db_strategy="DevCloudDatabaseStrategy",
            startup_duration_seconds=1.2,
        )

        test_args = [
            "lifecycle_supervisor_cli",
            "--backend-dir",
            str(self.backend_dir),
            "--check-only",
            "--json",
        ]

        with patch("sys.argv", test_args):
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                with self.assertRaises(SystemExit) as cm:
                    main()

        self.assertEqual(cm.exception.code, 0)
        mock_sup.start_services.assert_called_once()
        mock_sup.terminate_all.assert_called_once()

        output = mock_out.getvalue()
        self.assertIn('"success": true', output)
        self.assertIn("Tearing down child services cleanly", output)

    @patch("automation.lifecycle_supervisor_cli.get_lifecycle_supervisor")
    def test_cli_failure_exits_code_1(self, mock_get_sup) -> None:
        """Failing startup exits with code 1."""
        mock_sup = MagicMock()
        mock_get_sup.return_value = mock_sup

        mock_sup.start_services.return_value = LifecycleResult(
            success=False,
            error_message="Backend health check timed out",
            startup_duration_seconds=5.0,
        )

        test_args = [
            "lifecycle_supervisor_cli",
            "--backend-dir",
            str(self.backend_dir),
            "--check-only",
        ]

        with patch("sys.argv", test_args):
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as cm:
                    main()

        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
