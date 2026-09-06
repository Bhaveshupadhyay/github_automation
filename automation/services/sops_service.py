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

    ENV_KEY_PATTERN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")

    def __init__(self, sops_binary: Optional[str] = None) -> None:
        self._sops_binary = sops_binary or shutil.which("sops") or "sops"

    def is_sops_available(self) -> bool:
        """Returns True if the sops binary is discoverable and executable."""
        return shutil.which(self._sops_binary) is not None

    def parse_encrypted_keys(self, encrypted_path: Union[str, Path]) -> Set[str]:
        """Extracts visible environment variable keys from .env.qa.enc without decryption.

        SOPS dotenv encryption keeps variable keys unencrypted and values encrypted.
        Internal SOPS metadata keys prefixed with 'sops_' are excluded.
        """
        path = Path(encrypted_path)
        if not path.is_file():
            raise FileNotFoundError(f"Encrypted secrets file not found: {path.resolve()}")

        keys: Set[str] = set()
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                match = self.ENV_KEY_PATTERN.match(line)
                if match:
                    key = match.group(1)
                    # Exclude SOPS internal metadata keys
                    if not key.lower().startswith("sops_"):
                        keys.add(key)

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
            out_p.write_text(decrypted_text, encoding="utf-8")

        return decrypted_text
