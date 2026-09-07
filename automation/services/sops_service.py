"""Service for Mozilla SOPS encryption, decryption, and key inspection."""
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Set, Optional, Union

from automation.interfaces.sops_interface import ISOpsService


class SOpsService(ISOpsService):
    """Encapsulates Mozilla SOPS CLI interactions and plaintext key auditing."""

    ENV_LINE_PATTERN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
    SOPS_METADATA_EXCLUDES = {
        "sops_version",
        "sops_mac",
        "sops_lastmodified",
        "sops_unencrypted_suffix",
    }

    def __init__(self, sops_binary: Optional[str] = None) -> None:
        self._sops_binary = sops_binary or shutil.which("sops") or "sops"

    def is_sops_available(self) -> bool:
        """Returns True if the sops binary is discoverable and executable."""
        return shutil.which(self._sops_binary) is not None

    def _is_sops_internal_key(self, key: str) -> bool:
        """Returns True if key is internal SOPS metadata rather than an application variable."""
        if key in self.SOPS_METADATA_EXCLUDES:
            return True
        if key.startswith("sops_") and any(
            key.startswith(prefix) for prefix in ("sops_age__", "sops_kms__", "sops_gcp_kms__", "sops_azure_kv__")
        ):
            return True
        return False

    def parse_encrypted_keys(self, encrypted_path: Union[str, Path]) -> Set[str]:
        """Extracts visible environment variable keys from .env.qa.enc without decryption.

        SOPS dotenv encryption keeps variable keys unencrypted and values encrypted.
        Verifies that SOPS metadata is present and all application values are encrypted.
        Internal SOPS metadata keys prefixed with 'sops_' are excluded.
        """
        path = Path(encrypted_path)
        if not path.is_file():
            raise FileNotFoundError(f"Encrypted secrets file not found: {path.resolve()}")

        keys: Set[str] = set()
        has_sops_metadata = False

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                match = self.ENV_LINE_PATTERN.match(line)
                if match:
                    key = match.group(1)
                    val = match.group(2).strip().strip("'\"")

                    if self._is_sops_internal_key(key):
                        has_sops_metadata = True
                        continue

                    if not val.startswith("ENC["):
                        raise ValueError(
                            f"File '{path}' is not a valid SOPS-encrypted file: "
                            f"key '{key}' has unencrypted value."
                        )

                    keys.add(key)

        if not has_sops_metadata:
            raise ValueError(f"File '{path}' does not contain valid SOPS encryption metadata.")

        return keys

    def encrypt_file(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        age_recipient: Optional[str] = None,
    ) -> None:
        """Encrypts a plaintext dotenv file using SOPS and age."""
        in_p = Path(input_path)
        out_p = Path(output_path)

        if not in_p.is_file():
            raise FileNotFoundError(f"Plaintext input file not found: {in_p.resolve()}")

        cmd = [self._sops_binary, "--encrypt", "--input-type", "dotenv", "--output-type", "dotenv"]
        if age_recipient:
            cmd.extend(["--age", age_recipient])
        cmd.append(str(in_p))

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"SOPS encryption failed ({result.returncode}): {result.stderr.strip()}")

        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(result.stdout, encoding="utf-8")

    def decrypt_file(
        self,
        encrypted_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        age_private_key: Optional[str] = None,
    ) -> str:
        """Decrypts a SOPS-encrypted dotenv file.

        Accepts age_private_key directly or reads SOPS_AGE_KEY from process environment.
        Writes output with owner-only permissions (0600) when output_path is provided.
        """
        enc_p = Path(encrypted_path)
        if not enc_p.is_file():
            raise FileNotFoundError(f"Encrypted file not found: {enc_p.resolve()}")

        env = os.environ.copy()
        if age_private_key:
            env["SOPS_AGE_KEY"] = age_private_key
        elif "SOPS_AGE_KEY" not in env:
            raise ValueError(
                "Decryption failed: Neither age_private_key was supplied nor SOPS_AGE_KEY environment variable is set."
            )

        cmd = [self._sops_binary, "--decrypt", "--input-type", "dotenv", "--output-type", "dotenv", str(enc_p)]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"SOPS decryption failed ({result.returncode}): {result.stderr.strip()}")

        decrypted_text = result.stdout
        if output_path:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            # Ensure owner-only permissions (0600) before writing secrets to disk
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(str(out_p), flags, 0o600)
            try:
                os.write(fd, decrypted_text.encode("utf-8"))
            finally:
                os.close(fd)
            os.chmod(str(out_p), 0o600)

        return decrypted_text
