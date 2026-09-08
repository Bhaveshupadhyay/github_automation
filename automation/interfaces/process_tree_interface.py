"""Interface for process group management and transient file shredding."""
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional, Union


class IProcessTreeManager(ABC):
    """Abstract contract for POSIX process group management, termination, and secret shredding."""

    @abstractmethod
    def spawn_service_process(
        self,
        cmd: str,
        cwd: Path,
        env: Dict[str, str],
        name: str,
        log_file: Optional[Path] = None,
    ) -> subprocess.Popen:
        """Spawns a process in a new process group with stdout/stderr directed to log_file."""
        pass

    @abstractmethod
    def register_process(self, proc: subprocess.Popen, name: str) -> None:
        """Registers a process for supervised tracking."""
        pass

    @abstractmethod
    def terminate_process(self, proc: subprocess.Popen, timeout: float = 5.0) -> bool:
        """Terminates a process group using two-stage SIGTERM -> SIGKILL."""
        pass

    @abstractmethod
    def terminate_all(self, timeout: float = 5.0) -> None:
        """Terminates all registered active child process groups."""
        pass

    @abstractmethod
    def register_transient_file(self, path: Union[str, Path]) -> None:
        """Registers a transient secret file for shredding on shutdown."""
        pass

    @abstractmethod
    def shred_transient_files(self) -> None:
        """Overwrites and unlinks all registered transient secret files."""
        pass

    @abstractmethod
    def install_signal_traps(self) -> None:
        """Installs signal handlers (SIGINT, SIGTERM) and atexit hook."""
        pass

    @abstractmethod
    def uninstall_signal_traps(self) -> None:
        """Restores original signal handlers."""
        pass
