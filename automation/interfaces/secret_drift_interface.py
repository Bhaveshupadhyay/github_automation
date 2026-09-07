"""Interface for CI secret drift detection service."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union
from automation.domain.secret_drift import DriftReport


class ISecretDriftDetectorService(ABC):
    """Detects missing environment variable keys between .env.example and .env.qa.enc."""

    @abstractmethod
    def check_drift(
        self,
        example_path: Union[str, Path],
        encrypted_path: Union[str, Path],
    ) -> DriftReport:
        """Compares variable keys in .env.example against .env.qa.enc."""
        pass
