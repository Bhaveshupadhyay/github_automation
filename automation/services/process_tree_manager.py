"""Service for POSIX process tree group management, bounded termination, and secret shredding."""
import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from automation.interfaces.process_tree_interface import IProcessTreeManager

logger = logging.getLogger(__name__)


class ProcessTreeManager(IProcessTreeManager):
    """Manages child process groups with guaranteed two-stage termination and secret shredding.

    Spawns child processes in separate POSIX process groups (start_new_session=True)
    so all child processes and subprocesses can be signaled atomically.
    Implements a 5-second graceful SIGTERM grace period before forceful SIGKILL.
    """

    def __init__(self) -> None:
        self._tracked_processes: List[Tuple[subprocess.Popen, str]] = []
        self._transient_files: Set[Path] = set()
        self._open_log_files: List[Any] = []
        self._old_sigint_handler: Any = None
        self._old_sigterm_handler: Any = None
        self._traps_installed: bool = False
        self._lock = threading.RLock()

    def spawn_service_process(
        self,
        cmd: str,
        cwd: Path,
        env: Dict[str, str],
        name: str,
        log_file: Optional[Path] = None,
    ) -> subprocess.Popen:
        """Spawns a service process with start_new_session=True and directs output to log_file."""
        stdout_dest = subprocess.DEVNULL
        stderr_dest = subprocess.DEVNULL
        if log_file:
            log_p = Path(log_file)
            log_p.parent.mkdir(parents=True, exist_ok=True)
            fp = open(log_p, "a", encoding="utf-8")
            with self._lock:
                self._open_log_files.append(fp)
            stdout_dest = fp
            stderr_dest = subprocess.STDOUT

        logger.info(f"Spawning service '{name}' [cwd={cwd}]: {cmd}")
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(cwd),
            env=env,
            stdout=stdout_dest,
            stderr=stderr_dest,
            start_new_session=True,
        )

        self.register_process(proc, name)
        logger.info(f"Service '{name}' spawned successfully (PID: {proc.pid})")
        return proc

    def register_process(self, proc: subprocess.Popen, name: str) -> None:
        """Registers a process for supervised tracking."""
        with self._lock:
            if not any(p[0] == proc for p in self._tracked_processes):
                self._tracked_processes.append((proc, name))

    def terminate_process(self, proc: subprocess.Popen, timeout: float = 5.0) -> bool:
        """Terminates a process group using two-stage SIGTERM -> SIGKILL."""
        if proc.poll() is not None:
            return True

        pid = proc.pid
        logger.info(f"Terminating process group for PID {pid} (timeout={timeout}s)...")

        # Stage 1: Graceful termination (SIGTERM to process group)
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    return True
            else:
                proc.terminate()
        except OSError as e:
            logger.warning(f"Error sending SIGTERM to PID {pid}: {e}")

        # Wait for graceful exit up to timeout
        try:
            proc.wait(timeout=timeout)
            logger.info(f"Process {pid} exited gracefully.")
            return True
        except subprocess.TimeoutExpired:
            logger.warning(
                f"Process {pid} did not exit within {timeout}s grace period. "
                f"Sending SIGKILL (kill -9) to process group..."
            )

        # Stage 2: Forceful kill (SIGKILL to process group)
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    return True
            else:
                proc.kill()
        except OSError as e:
            logger.warning(f"Error sending SIGKILL to PID {pid}: {e}")

        # Final reap
        try:
            proc.wait(timeout=2.0)
            logger.info(f"Process {pid} terminated forcefully.")
            return True
        except Exception as e:
            logger.error(f"Failed to reap process {pid}: {e}")
            return False

    def terminate_all(self, timeout: float = 5.0) -> None:
        """Terminates all registered active child process groups in reverse order."""
        with self._lock:
            processes = list(reversed(self._tracked_processes))
            self._tracked_processes.clear()

        for proc, name in processes:
            logger.info(f"Supervised teardown: terminating {name} (PID: {proc.pid})")
            self.terminate_process(proc, timeout=timeout)

        # Close open log file handles
        with self._lock:
            for fp in self._open_log_files:
                try:
                    fp.flush()
                    fp.close()
                except Exception:
                    pass
            self._open_log_files.clear()

    def register_transient_file(self, path: Union[str, Path]) -> None:
        """Registers a transient secret file for shredding on shutdown."""
        with self._lock:
            self._transient_files.add(Path(path).resolve())

    def shred_transient_files(self) -> None:
        """Overwrites and unlinks all registered transient secret files."""
        with self._lock:
            files_to_shred = list(self._transient_files)
            self._transient_files.clear()

        for path in files_to_shred:
            if not path.is_file():
                continue
            logger.info(f"Securely shredding transient secrets file: {path}")
            try:
                size = path.stat().st_size
                if size > 0:
                    with open(path, "wb") as f:
                        f.write(b"\x00" * size)
                        f.flush()
                        os.fsync(f.fileno())
                path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Failed to securely shred {path}: {e}")
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

    def install_signal_traps(self) -> None:
        """Installs signal handlers (SIGINT, SIGTERM) and atexit hook."""
        if self._traps_installed:
            return

        atexit.register(self._cleanup_on_exit)

        if threading.current_thread() is threading.main_thread():
            try:
                self._old_sigint_handler = signal.getsignal(signal.SIGINT)
                self._old_sigterm_handler = signal.getsignal(signal.SIGTERM)

                def _signal_handler(signum: int, frame: Any) -> None:
                    sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
                    logger.warning(f"Signal {sig_name} received. Initiating emergency process termination...")
                    self.terminate_all(timeout=5.0)
                    self.shred_transient_files()
                    sys.exit(128 + signum)

                signal.signal(signal.SIGINT, _signal_handler)
                signal.signal(signal.SIGTERM, _signal_handler)
                self._traps_installed = True
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not install signal handlers: {e}")

    def uninstall_signal_traps(self) -> None:
        """Restores original signal handlers."""
        if not self._traps_installed:
            return

        if threading.current_thread() is threading.main_thread():
            if self._old_sigint_handler is not None:
                signal.signal(signal.SIGINT, self._old_sigint_handler)
            if self._old_sigterm_handler is not None:
                signal.signal(signal.SIGTERM, self._old_sigterm_handler)
        self._traps_installed = False

    def _cleanup_on_exit(self) -> None:
        """Invoked by atexit to guarantee cleanup on standard interpreter termination."""
        self.terminate_all(timeout=5.0)
        self.shred_transient_files()
