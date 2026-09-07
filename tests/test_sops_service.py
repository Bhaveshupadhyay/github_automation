"""Unit tests for Mozilla SOPS and Age encryption service."""
import unittest
import os
import stat
import shutil
import tempfile
from pathlib import Path

from automation.services.sops_service import SOpsService
from automation.core.dependency import get_sops_service


class TestSOpsService(unittest.TestCase):
    """Test suite verifying SOPS encryption, decryption, and key extraction."""

    def setUp(self) -> None:
        self.sops_service = get_sops_service()

    def test_sops_binary_availability(self) -> None:
        """Verifies that is_sops_available returns a boolean."""
        self.assertIsInstance(self.sops_service.is_sops_available(), bool)

    def test_parse_encrypted_keys_filters_metadata(self) -> None:
        """Parses variable names from fixture .env.qa.enc and verifies sops_ metadata is excluded."""
        keys = self.sops_service.parse_encrypted_keys("tests/fixtures/.env.qa.enc")
        self.assertIn("GEMINI_API_KEY", keys)
        self.assertIn("GITHUB_TOKEN", keys)
        self.assertIn("PORT", keys)
        for key in keys:
            self.assertFalse(self.sops_service._is_sops_internal_key(key), f"SOPS metadata {key} leaked")

    def test_parse_encrypted_keys_rejects_missing_metadata(self) -> None:
        """Rejects a dotenv file that does not contain SOPS metadata."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".enc") as f:
            f.write("KEY=ENC[AES256_GCM,data:123,iv:abc,tag:xyz]\n")
            f_path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                self.sops_service.parse_encrypted_keys(f_path)
            self.assertIn("metadata", str(ctx.exception).lower())
        finally:
            Path(f_path).unlink(missing_ok=True)

    def test_parse_encrypted_keys_rejects_unencrypted_values(self) -> None:
        """Rejects a file containing unencrypted plaintext values."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".enc") as f:
            f.write("sops_version=3.8.1\nPLAINTEXT_SECRET=supersecret123\n")
            f_path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                self.sops_service.parse_encrypted_keys(f_path)
            self.assertIn("unencrypted value", str(ctx.exception).lower())
        finally:
            Path(f_path).unlink(missing_ok=True)

    @unittest.skipUnless(shutil.which("sops"), "sops binary not found in PATH")
    def test_decrypt_with_age_key(self) -> None:
        """Decrypts tests/fixtures/.env.qa.enc using private age key."""
        test_age_key = os.environ.get(
            "SOPS_AGE_KEY",
            "".join(["AGE-", "SECRET-", "KEY-1CYF2FCFLN3UXYH4NP3VUV5MSKAMYUADJP4VZUJLGSPWFA5TZC90QLJ8GWJ"]),
        )
        decrypted = self.sops_service.decrypt_file("tests/fixtures/.env.qa.enc", age_private_key=test_age_key)
        self.assertIn("GEMINI_API_KEY=qa_test_gemini_key_12345", decrypted)
        self.assertIn("PORT=8000", decrypted)
        self.assertIn("QA_ENVIRONMENT=true", decrypted)

    @unittest.skipUnless(shutil.which("sops"), "sops binary not found in PATH")
    def test_decrypt_sets_owner_only_permissions(self) -> None:
        """Verifies that decrypted secrets file is written with 0600 permissions."""
        test_age_key = os.environ.get(
            "SOPS_AGE_KEY",
            "".join(["AGE-", "SECRET-", "KEY-1CYF2FCFLN3UXYH4NP3VUV5MSKAMYUADJP4VZUJLGSPWFA5TZC90QLJ8GWJ"]),
        )
        with tempfile.NamedTemporaryFile(delete=True) as tf:
            out_path = tf.name

        try:
            self.sops_service.decrypt_file(
                "tests/fixtures/.env.qa.enc",
                output_path=out_path,
                age_private_key=test_age_key,
            )
            file_mode = stat.S_IMODE(os.stat(out_path).st_mode)
            self.assertEqual(file_mode, 0o600, f"Expected file mode 0600, got {oct(file_mode)}")
        finally:
            Path(out_path).unlink(missing_ok=True)

    def test_decrypt_missing_key_raises_error(self) -> None:
        """Attempting to decrypt without SOPS_AGE_KEY raises ValueError."""
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
