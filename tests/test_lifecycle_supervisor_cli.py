"""Unit tests for automation.lifecycle_supervisor_cli."""
import io
import json
import os
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


class TestLifecycleSupervisorCIHandoff(unittest.TestCase):
    """The markers a CI job relies on to know when services are up and how to stop them."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.backend_dir = self.root / "backend"
        self.backend_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _args(self, *extra: str) -> list:
        return [
            "lifecycle_supervisor_cli",
            "--backend-dir",
            str(self.backend_dir),
            "--result-json",
            str(self.root / "lifecycle.json"),
            "--ready-file",
            str(self.root / "ready"),
            "--pid-file",
            str(self.root / "supervisor.pid"),
            *extra,
        ]

    @patch("automation.lifecycle_supervisor_cli.get_lifecycle_supervisor")
    def test_failed_startup_writes_the_result_and_no_readiness_marker(self, mock_get_sup) -> None:
        """A waiting CI step must never see readiness for services that never started,
        and the next stage still needs a machine-readable reason."""
        mock_sup = MagicMock()
        mock_get_sup.return_value = mock_sup
        mock_sup.start_services.return_value = LifecycleResult(
            success=False,
            error_message="Backend health check timed out",
            startup_duration_seconds=5.0,
        )

        with patch("sys.argv", self._args("--check-only")):
            with patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as cm:
                    main()

        self.assertEqual(cm.exception.code, 1)
        self.assertFalse((self.root / "ready").exists())
        written = json.loads((self.root / "lifecycle.json").read_text(encoding="utf-8"))
        self.assertFalse(written["success"])
        self.assertIn("timed out", written["error_message"])

    @patch("automation.lifecycle_supervisor_cli.time.sleep", side_effect=KeyboardInterrupt)
    @patch("automation.lifecycle_supervisor_cli.get_lifecycle_supervisor")
    def test_daemon_mode_publishes_then_clears_its_markers(self, mock_get_sup, _sleep) -> None:
        """The markers are written only after the health probes pass, and removed on
        shutdown so a stale file cannot be read as liveness."""
        mock_sup = MagicMock()
        mock_get_sup.return_value = mock_sup

        observed = {}

        def _capture(*_args, **_kwargs):
            observed["ready_at_start"] = (self.root / "ready").exists()
            return LifecycleResult(
                success=True,
                backend_info=ServiceProcessInfo(
                    name="backend",
                    pid=4321,
                    port=8000,
                    health_url="http://localhost:8000/health",
                    status=ServiceStatus.HEALTHY,
                    start_command="python -m uvicorn",
                ),
                startup_duration_seconds=2.0,
            )

        mock_sup.start_services.side_effect = _capture

        with patch("sys.argv", self._args()):
            with patch("sys.stdout", new_callable=io.StringIO):
                main()

        self.assertFalse(observed["ready_at_start"])
        self.assertFalse((self.root / "ready").exists())
        self.assertFalse((self.root / "supervisor.pid").exists())
        mock_sup.terminate_all.assert_called_once()
        self.assertTrue(json.loads((self.root / "lifecycle.json").read_text(encoding="utf-8"))["success"])

    @patch("automation.lifecycle_supervisor_cli.get_lifecycle_supervisor")
    def test_an_exception_during_startup_still_writes_the_result(self, mock_get_sup) -> None:
        """Startup is where exceptions actually occur — an unreachable database, a
        malformed tunnel config. Writing the result only for a politely-returned failure
        omits the handoff artifact on the paths that most need explaining."""
        mock_sup = MagicMock()
        mock_get_sup.return_value = mock_sup
        mock_sup.start_services.side_effect = RuntimeError("could not reach the database host")

        with patch("sys.argv", self._args("--check-only")):
            with patch("sys.stdout", new_callable=io.StringIO):
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as cm:
                        main()

        self.assertEqual(cm.exception.code, 1)
        written = json.loads((self.root / "lifecycle.json").read_text(encoding="utf-8"))
        self.assertFalse(written["success"])
        self.assertIn("could not reach the database host", written["error_message"])
        # Anything spawned before the exception must not outlive the process.
        mock_sup.terminate_all.assert_called_once()
        self.assertFalse((self.root / "ready").exists())

    @patch("automation.lifecycle_supervisor_cli.get_database_strategy")
    @patch("automation.lifecycle_supervisor_cli.get_lifecycle_supervisor")
    def test_a_failure_building_the_database_strategy_is_also_reported(
        self, mock_get_sup, mock_get_db
    ) -> None:
        """This raises before the supervisor is ever called."""
        mock_get_sup.return_value = MagicMock()
        mock_get_db.side_effect = ValueError("WireGuard config is malformed")

        with patch("sys.argv", self._args("--check-only", "--db-strategy", "cloud_dev")):
            with patch("sys.stdout", new_callable=io.StringIO):
                with patch("sys.stderr", new_callable=io.StringIO):
                    with self.assertRaises(SystemExit) as cm:
                        main()

        self.assertEqual(cm.exception.code, 1)
        written = json.loads((self.root / "lifecycle.json").read_text(encoding="utf-8"))
        self.assertIn("WireGuard config is malformed", written["error_message"])

    @patch("automation.lifecycle_supervisor_cli.get_lifecycle_supervisor")
    def test_the_pid_file_names_this_process(self, mock_get_sup) -> None:
        """A CI teardown step signals this PID; the wrong one leaves services running."""
        mock_sup = MagicMock()
        mock_get_sup.return_value = mock_sup
        mock_sup.start_services.return_value = LifecycleResult(success=True, startup_duration_seconds=1.0)

        recorded = {}

        def _read_markers(_duration):
            recorded["pid"] = (self.root / "supervisor.pid").read_text(encoding="utf-8").strip()
            recorded["ready"] = (self.root / "ready").read_text(encoding="utf-8").strip()
            raise KeyboardInterrupt

        with patch("automation.lifecycle_supervisor_cli.time.sleep", side_effect=_read_markers):
            with patch("sys.argv", self._args()):
                with patch("sys.stdout", new_callable=io.StringIO):
                    main()

        self.assertEqual(recorded["pid"], str(os.getpid()))
        self.assertEqual(recorded["ready"], "ready")


if __name__ == "__main__":
    unittest.main()
