"""Unit tests for secret key drift detector service and domain models."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from automation.domain.secret_drift import DriftReport
from automation.interfaces.sops_interface import ISOpsService
from automation.services.secret_drift_service import SecretDriftDetectorService
from automation.core.dependency import get_secret_drift_detector_service


class TestSecretDriftDetector(unittest.TestCase):
    """Test suite verifying CI secret drift detection between .env.example and .env.qa.enc."""

    def setUp(self) -> None:
        self.mock_sops = MagicMock(spec=ISOpsService)
        self.detector = SecretDriftDetectorService(sops_service=self.mock_sops)

    def test_parse_example_keys(self) -> None:
        """Parses standard dotenv syntax including export prefixes, spaces, and skips comments."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".example") as f:
            f.write("""
            # Database Configuration
            DATABASE_URL=postgresql://localhost:5432/db
            PORT=8000
            
            # Authentication
            export JWT_SECRET=supersecret123
            API_KEY = abcxyz
            
            # Trailing comment
            """)
            temp_path = f.name

        try:
            keys = self.detector.parse_example_keys(temp_path)
            self.assertEqual(keys, {"DATABASE_URL", "PORT", "JWT_SECRET", "API_KEY"})
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_check_drift_valid(self) -> None:
        """When all example keys are present in encrypted secrets, report is valid."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".example") as f:
            f.write("FOO=1\nBAR=2\n")
            example_p = f.name

        self.mock_sops.parse_encrypted_keys.return_value = {"FOO", "BAR", "EXTRA_QA_SECRET"}

        try:
            report = self.detector.check_drift(example_p, ".env.qa.enc")
            self.assertTrue(report.is_valid)
            self.assertEqual(report.missing_keys, [])
            self.assertEqual(report.extra_keys, ["EXTRA_QA_SECRET"])
            self.assertIn("SECRET INTEGRITY VERIFIED", report.format_diagnostic_summary())
        finally:
            Path(example_p).unlink(missing_ok=True)

    def test_check_drift_missing_keys(self) -> None:
        """When example keys are missing from encrypted secrets, report fails with diagnostic message."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".example") as f:
            f.write("DB_HOST=localhost\nDB_PASS=secret\nREDIS_URL=redis://localhost\n")
            example_p = f.name

        # Encrypted file is missing DB_PASS and REDIS_URL
        self.mock_sops.parse_encrypted_keys.return_value = {"DB_HOST"}

        try:
            report = self.detector.check_drift(example_p, ".env.qa.enc")
            self.assertFalse(report.is_valid)
            self.assertEqual(report.missing_keys, ["DB_PASS", "REDIS_URL"])
            self.assertIn("KEY DRIFT GUARDRAIL FAILURE", report.error_message)
            self.assertIn("'DB_PASS'", report.error_message)
            self.assertIn("'REDIS_URL'", report.error_message)
            self.assertIn("sops .env.qa.enc", report.error_message)
        finally:
            Path(example_p).unlink(missing_ok=True)

    def test_fixture_files_integrity(self) -> None:
        """Audits fixture .env.example against fixture .env.qa.enc."""
        real_detector = get_secret_drift_detector_service()
        report = real_detector.check_drift("tests/fixtures/.env.example", "tests/fixtures/.env.qa.enc")
        self.assertTrue(report.is_valid, f"Fixture drift check failed: {report.error_message}")
        self.assertGreaterEqual(len(report.example_keys), 7)


if __name__ == "__main__":
    unittest.main()
