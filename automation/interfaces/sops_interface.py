"""Interface for Mozilla SOPS and Age encryption operations."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Set, Optional, Union


class ISOpsService(ABC):
    """Abstract interface managing SOPS / Age operations."""

    @abstractmethod
    def is_sops_available(self) -> bool:
        """Returns True if the sops binary is accessible in PATH."""
        pass

    @abstractmethod
    def parse_encrypted_keys(self, encrypted_path: Union[str, Path]) -> Set[str]:
        """Extracts visible environment variable keys from encrypted .env.qa.enc."""
        pass

    @abstractmethod
    def encrypt_file(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        age_recipient: Optional[str] = None,
    ) -> None:
        """Encrypts a plaintext dotenv file into a SOPS-encrypted dotenv file."""
        pass

    @abstractmethod
    def decrypt_file(
        self,
        encrypted_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        age_private_key: Optional[str] = None,
    ) -> str:
        """Decrypts a SOPS-encrypted file into plaintext string and optionally writes to output_path."""
        pass
