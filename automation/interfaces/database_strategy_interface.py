"""Interface for pluggable database strategies in automated QA testing."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from automation.domain.database_strategy import MigrationResult


class IDatabaseStrategy(ABC):
    """Abstract contract for database provisioning, migration execution, and cleanup."""

    @abstractmethod
    def get_connection_env(self) -> Dict[str, str]:
        """Returns environment variables providing database connectivity.

        Returns:
            Dictionary of key-value pairs (e.g. DATABASE_URL, PGHOST, etc.).
        """
        pass

    @abstractmethod
    def run_migrations(
        self,
        repo_dir: Path,
        env: Dict[str, str],
        migration_command: Optional[str] = None,
    ) -> MigrationResult:
        """Executes database schema migrations and seed scripts.

        Args:
            repo_dir: Path to the target repository containing migration scripts.
            env: Complete environment variables dictionary for execution.
            migration_command: Optional explicit migration command override.

        Returns:
            MigrationResult indicating success, output, and duration.
        """
        pass

    @abstractmethod
    def teardown(self) -> None:
        """Cleans up ephemeral test data, connections, or container state."""
        pass
