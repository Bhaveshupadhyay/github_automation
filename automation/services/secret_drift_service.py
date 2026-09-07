"""Service detecting configuration secret drift between .env.example and .env.qa.enc."""
import re
from pathlib import Path
from typing import Set, Union, Optional

from automation.domain.secret_drift import DriftReport
from automation.interfaces.secret_drift_interface import ISecretDriftDetectorService
from automation.interfaces.sops_interface import ISOpsService
from automation.services.sops_service import SOpsService


class SecretDriftDetectorService(ISecretDriftDetectorService):
    """Audits environment variable consistency between public documentation and encrypted secrets."""

    ENV_KEY_REGEX = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

    def __init__(self, sops_service: Optional[ISOpsService] = None) -> None:
        self._sops_service = sops_service or SOpsService()

    def parse_example_keys(self, example_path: Union[str, Path]) -> Set[str]:
        """Extracts variable names from a plaintext .env.example file."""
        path = Path(example_path)
        if not path.is_file():
            raise FileNotFoundError(f"Plaintext example template not found: {path.resolve()}")

        keys: Set[str] = set()
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = self.ENV_KEY_REGEX.match(line)
                if match:
                    keys.add(match.group(1))
        return keys

    def check_drift(
        self,
        example_path: Union[str, Path],
        encrypted_path: Union[str, Path],
    ) -> DriftReport:
        """Compares required keys in .env.example against visible keys in .env.qa.enc."""
        example_keys = self.parse_example_keys(example_path)
        qa_keys = self._sops_service.parse_encrypted_keys(encrypted_path)

        missing = sorted(list(example_keys - qa_keys))
        extra = sorted(list(qa_keys - example_keys))
        is_valid = len(missing) == 0

        report = DriftReport(
            is_valid=is_valid,
            missing_keys=missing,
            extra_keys=extra,
            example_keys=sorted(list(example_keys)),
            qa_keys=sorted(list(qa_keys)),
        )

        if not is_valid:
            report.error_message = report.format_diagnostic_summary()

        return report
