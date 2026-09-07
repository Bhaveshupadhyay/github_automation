"""Interface for service lifecycle supervision and process orchestration."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from automation.domain.lifecycle import LifecycleResult
from automation.interfaces.database_strategy_interface import IDatabaseStrategy


class ILifecycleSupervisor(ABC):
    """Abstract interface for supervising backend and frontend service lifecycles."""

    @abstractmethod
    def start_services(
        self,
        backend_dir: Path,
        frontend_dir: Optional[Path] = None,
        db_strategy: Optional[IDatabaseStrategy] = None,
        sops_age_key: Optional[str] = None,
        backend_health_timeout: float = 60.0,
        frontend_health_timeout: float = 60.0,
    ) -> LifecycleResult:
        """Starts backend and optional frontend services, verifying health readiness.

        Args:
            backend_dir: Path to the backend repository root containing qa-contract.json.
            frontend_dir: Optional path to the frontend repository root.
            db_strategy: Database provisioning strategy to utilize.
            sops_age_key: Private age key for SOPS decryption (defaults to SOPS_AGE_KEY env).
            backend_health_timeout: Maximum seconds to await backend readiness.
            frontend_health_timeout: Maximum seconds to await frontend readiness.

        Returns:
            LifecycleResult detailing process IDs, listening ports, and status.
        """
        pass

    @abstractmethod
    def terminate_all(self) -> None:
        """Gracefully (then forcefully) terminates all spawned processes and cleans transient files."""
        pass
