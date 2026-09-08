"""Unit tests for ProcessTreeManager: process group supervision, termination, and secret shredding."""
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from automation.services.process_tree_manager import ProcessTreeManager


class TestProcessTreeManager(unittest.TestCase):
    """Verifies process group creation, graceful and forceful termination, and file shredding."""

    def setUp(self) -> None:
        self.manager = ProcessTreeManager()

    def tearDown(self) -> None:
        self.manager.terminate_all(timeout=1.0)
        self.manager.shred_transient_files()
        self.manager.uninstall_signal_traps()

    def test_spawn_and_terminate_process_graceful(self) -> None:
        """Spawns a process and confirms graceful termination with SIGTERM."""
        # Process sleeps for 30 seconds unless terminated
        proc = self.manager.spawn_service_process(
            cmd=f"{sys.executable} -c 'import time; time.sleep(30)'",
            cwd=Path.cwd(),
            env=os.environ.copy(),
            name="test-sleep",
        )
        self.assertIsNotNone(proc.pid)
        self.assertIsNone(proc.poll())  # still running

        # Terminate
        terminated = self.manager.terminate_process(proc, timeout=2.0)
        self.assertTrue(terminated)
        self.assertIsNotNone(proc.poll())

    def test_forceful_termination_when_process_ignores_sigterm(self) -> None:
        """Process that ignores SIGTERM is forcefully terminated via SIGKILL after grace period."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            ready_path = Path(tmp.name)
        ready_path.unlink(missing_ok=True)

        try:
            cmd = (
                f"exec {sys.executable} -c '"
                f"import signal, time, pathlib; "
                f"signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"pathlib.Path(\"{ready_path}\").touch(); "
                f"time.sleep(30)'"
            )
            proc = self.manager.spawn_service_process(
                cmd=cmd,
                cwd=Path.cwd(),
                env=os.environ.copy(),
                name="test-stubborn",
            )
            self.assertIsNotNone(proc.pid)
            self.assertIsNone(proc.poll())

            # Explicit readiness synchronization with bounded timeout
            poll_start = time.monotonic()
            while not ready_path.exists() and (time.monotonic() - poll_start) < 3.0:
                time.sleep(0.02)

            self.assertTrue(ready_path.exists(), "Child failed to install SIG_IGN before termination test")

            start = time.monotonic()
            # Use short timeout (0.5s) to trigger SIGKILL quickly
            terminated = self.manager.terminate_process(proc, timeout=0.5)
            duration = time.monotonic() - start

            self.assertTrue(terminated)
            self.assertIsNotNone(proc.poll())
            self.assertGreaterEqual(duration, 0.5)
        finally:
            ready_path.unlink(missing_ok=True)

    def test_terminate_all_cleans_multiple_processes(self) -> None:
        """terminate_all terminates all registered processes in reverse order."""
        proc1 = self.manager.spawn_service_process(
            cmd=f"{sys.executable} -c 'import time; time.sleep(30)'",
            cwd=Path.cwd(),
            env=os.environ.copy(),
            name="service-1",
        )
        proc2 = self.manager.spawn_service_process(
            cmd=f"{sys.executable} -c 'import time; time.sleep(30)'",
            cwd=Path.cwd(),
            env=os.environ.copy(),
            name="service-2",
        )

        self.assertIsNone(proc1.poll())
        self.assertIsNone(proc2.poll())

        self.manager.terminate_all(timeout=2.0)

        self.assertIsNotNone(proc1.poll())
        self.assertIsNotNone(proc2.poll())
        self.assertEqual(len(self.manager._tracked_processes), 0)

    def test_spawn_with_log_file(self) -> None:
        """Service output is written to specified log file."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
            log_path = Path(tmp.name)

        try:
            proc = self.manager.spawn_service_process(
                cmd=f"{sys.executable} -c 'print(\"HELLO_SUPERVISOR_LOG\")'",
                cwd=Path.cwd(),
                env=os.environ.copy(),
                name="test-logging",
                log_file=log_path,
            )
            proc.wait(timeout=5.0)
            self.manager.terminate_all(timeout=1.0)  # flushes log handles

            content = log_path.read_text(encoding="utf-8")
            self.assertIn("HELLO_SUPERVISOR_LOG", content)
        finally:
            log_path.unlink(missing_ok=True)

    def test_shred_transient_files_destroys_content_and_unlinks(self) -> None:
        """Transient secret files are overwritten and deleted."""
        with tempfile.NamedTemporaryFile(suffix=".transient", delete=False) as tmp:
            tmp.write(b"SUPER_SECRET_DATABASE_PASSWORD_XYZ123")
            transient_path = Path(tmp.name)

        self.assertTrue(transient_path.is_file())
        self.manager.register_transient_file(transient_path)
        self.manager.shred_transient_files()

        self.assertFalse(transient_path.exists())

    def test_install_and_uninstall_signal_traps(self) -> None:
        """Signal traps can be installed and uninstalled cleanly."""
        self.manager.install_signal_traps()
        self.assertTrue(self.manager._traps_installed)

        # Re-install is idempotent
        self.manager.install_signal_traps()
        self.assertTrue(self.manager._traps_installed)

        self.manager.uninstall_signal_traps()
        self.assertFalse(self.manager._traps_installed)


if __name__ == "__main__":
    unittest.main()
