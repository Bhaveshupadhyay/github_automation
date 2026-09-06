"""Unit tests for Mozilla SOPS and Age encryption service."""
import unittest
import os
import tempfile
from pathlib import Path

from automation.services.sops_service import SOpsService
from automation.core.dependency import get_sops_service


class TestSOpsService(unittest.TestCase):
    """Test suite verifying SOPS encryption, decryption, and key extraction."""

    def setUp(self) -> None:
        self.sops_service = get_sops_service()

    def test_sops_binary_availability(self) -> None:
        """Verifies that the sops CLI binary is discoverable in PATH."""
        self.assertTrue(self.sops_service.is_sops_available())

    def test_parse_encrypted_keys_filters_metadata(self) -> None:
        """Parses variable names from fixture .env.qa.enc and verifies sops_ metadata is excluded."""
        keys = self.sops_service.parse_encrypted_keys("tests/fixtures/.env.qa.enc")
        self.assertIn("GEMINI_API_KEY", keys)
        self.assertIn("GITHUB_TOKEN", keys)
        self.assertIn("PORT", keys)
        for key in keys:
            self.assertFalse(key.lower().startswith("sops_"), f"SOPS metadata key {key} leaked into parsed keys")

    def test_decrypt_with_age_key(self) -> None:
        """Decrypts tests/fixtures/.env.qa.enc using test private age key."""
        test_age_key = "AGE-SECRET-KEY-1CYF2FCFLN3UXYH4NP3VUV5MSKAMYUADJP4VZUJLGSPWFA5TZC90QLJ8GWJ"
        decrypted = self.sops_service.decrypt_file("tests/fixtures/.env.qa.enc", age_private_key=test_age_key)
        self.assertIn("GEMINI_API_KEY=qa_test_gemini_key_12345", decrypted)
        self.assertIn("PORT=8000", decrypted)
        self.assertIn("QA_ENVIRONMENT=true", decrypted)

    def test_decrypt_missing_key_raises_error(self) -> None:
        """Attempting to decrypt without SOPS_AGE_KEY raises ValueError."""
        # Ensure SOPS_AGE_KEY is not in env for this call
        orig_val = os.environ.pop("SOPS_AGE_KEY", None)
        try:
            with self.assertRaises(ValueError) as ctx:
                self.sops_service.decrypt_file("tests/fixtures/.env.qa.enc", age_private_key=None)
            self.assertIn("SOPS_AGE_KEY", str(ctx.exception))
        finally:
            if orig_val is not None:
                os.environ["SOPS_AGE_KEY"] = orig_val

    def test_nonexistent_file_raises_not_found(self) -> None:
        """Nonexistent encrypted file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.sops_service.parse_encrypted_keys("nonexistent.enc")


if __name__ == "__main__":
    unittest.main()
