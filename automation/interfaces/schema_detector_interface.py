"""Interface for schema auto-detection and database setup strategy resolution."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from automation.domain.schema_detection import SchemaDetectionResult


class ISchemaDetectorService(ABC):
    """Abstract contract for scanning repositories and detecting schema sources.

    Implementations scan the target repo file system (no network calls) and return
    a tiered detection result indicating the best strategy to set up databases
    for QA testing.
    """

    @abstractmethod
    def detect(self, repo_dir: Path) -> SchemaDetectionResult:
        """Scans a repository and detects schema sources, databases, and setup strategy.

        Args:
            repo_dir: Absolute path to the cloned target repository.

        Returns:
            SchemaDetectionResult with resolved tier, detected sources, and setup commands.
        """
        pass

    @abstractmethod
    def generate_setup_commands(self, result: SchemaDetectionResult) -> List[str]:
        """Generates ordered shell commands to set up databases from detection results.

        Args:
            result: A previously computed SchemaDetectionResult.

        Returns:
            Ordered list of shell commands to execute in the CI prepare step.
        """
        pass
