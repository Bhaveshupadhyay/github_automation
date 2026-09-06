"""Unit tests for QA Contract validation service and domain models."""
import unittest
from pathlib import Path
from pydantic import ValidationError

from automation.domain.qa_contract import QAContract, ServiceType, MobilePlatform
from automation.services.qa_contract_service import QAContractValidatorService
from automation.core.dependency import get_qa_contract_validator_service


class TestQAContractValidator(unittest.TestCase):
    """Test suite covering QA contract schema and domain rule enforcement."""

    def setUp(self) -> None:
        self.validator = get_qa_contract_validator_service()


    def test_validate_example_contracts(self) -> None:
        """Validates all provided example contracts in contracts/examples/."""
        backend_p = Path("contracts/examples/backend-qa-contract.json")
        frontend_p = Path("contracts/examples/frontend-qa-contract.json")
        mobile_p = Path("contracts/examples/mobile-qa-contract.json")

        backend = self.validator.validate_contract_file(backend_p)
        self.assertEqual(backend.service_type, ServiceType.BACKEND)
        self.assertEqual(backend.port, 8000)
        self.assertIn("alembic", backend.get_effective_lifecycle().prepare)

        frontend = self.validator.validate_contract_file(frontend_p)
        self.assertEqual(frontend.service_type, ServiceType.FRONTEND)
        self.assertEqual(frontend.port, 3000)
        self.assertEqual(frontend.api_base_url_env_var, "NEXT_PUBLIC_API_URL")

        mobile = self.validator.validate_contract_file(mobile_p)
        self.assertEqual(mobile.service_type, ServiceType.MOBILE)
        self.assertIsNotNone(mobile.mobile_config)
        self.assertEqual(mobile.mobile_config.platform, MobilePlatform.ANDROID)
        self.assertEqual(mobile.mobile_config.bundle_id, "com.company.app")

    def test_frontend_requires_api_base_url_env_var(self) -> None:
        """Frontend service must fail validation if apiBaseUrlEnvVar is omitted."""
        invalid_data = {
            "serviceType": "frontend",
            "port": 3000,
            "healthCheckUrl": "/",
            "lifecycle": {"start": "npm start"},
        }
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate_contract_dict(invalid_data)
        self.assertIn("apiBaseUrlEnvVar", str(ctx.exception))

    def test_mobile_requires_mobile_config(self) -> None:
        """Mobile service must fail validation if mobileConfig is omitted."""
        invalid_data = {
            "serviceType": "mobile",
            "port": 8081,
            "healthCheckUrl": "/status",
            "lifecycle": {"start": "flutter run"},
        }
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate_contract_dict(invalid_data)
        self.assertIn("mobileConfig", str(ctx.exception))

    def test_invalid_port_range(self) -> None:
        """Port must be within 1..65535."""
        invalid_data = {
            "serviceType": "backend",
            "port": 70000,
            "healthCheckUrl": "/health",
            "lifecycle": {"start": "uvicorn main:app"},
        }
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate_contract_dict(invalid_data)
        self.assertIn("port", str(ctx.exception).lower())

    def test_missing_start_hook(self) -> None:
        """Contract without a start hook must fail validation."""
        invalid_data = {
            "serviceType": "backend",
            "port": 8000,
            "healthCheckUrl": "/health",
            "lifecycle": {"prepare": "uv sync"},
        }
        with self.assertRaises(ValidationError) as ctx:
            self.validator.validate_contract_dict(invalid_data)
        self.assertIn("start", str(ctx.exception).lower())

    def test_nonexistent_contract_file(self) -> None:
        """Attempting to validate missing file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.validator.validate_contract_file("nonexistent-contract.json")


if __name__ == "__main__":
    unittest.main()
