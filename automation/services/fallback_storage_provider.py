"""Composite storage provider implementing the zero-failure fallback chain."""
import logging
from typing import Optional

from automation.domain.storage import ArtifactKind, StorageProviderType, UploadOutcome, UploadedArtifact
from automation.interfaces.storage_interface import IStorageProvider

logger = logging.getLogger("automation.storage.fallback")


class FallbackStorageProvider(IStorageProvider):
    """Tries a primary backend and degrades to a secondary one on any failure.

    Upload failure must never fail the build: a missing preview video is an
    inconvenience, while a red pipeline on a working pull request is a broken signal.
    """

    def __init__(self, primary: IStorageProvider, fallback: IStorageProvider):
        self._primary = primary
        self._fallback = fallback
        self._last_used: Optional[StorageProviderType] = None
        self._degraded = False

    @property
    def provider_type(self) -> StorageProviderType:
        """Backend that actually served the most recent upload."""
        return self._last_used or self._primary.provider_type

    @property
    def degraded(self) -> bool:
        """True once any upload in this session has fallen back."""
        return self._degraded

    def is_available(self) -> bool:
        return self._primary.is_available() or self._fallback.is_available()

    def upload_file(
        self,
        local_path: str,
        remote_filename: str,
        kind: ArtifactKind,
    ) -> UploadedArtifact:
        """Upload via the primary backend, falling back on unavailability or error."""
        if self._primary.is_available():
            try:
                artifact = self._primary.upload_file(local_path, remote_filename, kind)
                self._last_used = artifact.provider
                return artifact
            except Exception as e:
                logger.warning(
                    f"Primary storage ({self._primary.provider_type.value}) failed for "
                    f"{remote_filename}: {e}. Falling back to "
                    f"{self._fallback.provider_type.value}."
                )
        else:
            logger.info(
                f"Primary storage ({self._primary.provider_type.value}) is not configured. "
                f"Using {self._fallback.provider_type.value}."
            )

        artifact = self._fallback.upload_file(local_path, remote_filename, kind)
        self._last_used = artifact.provider
        self._degraded = True
        return artifact

    def try_upload(
        self,
        local_path: str,
        remote_filename: str,
        kind: ArtifactKind,
    ) -> UploadOutcome:
        """Upload without raising, for callers that must continue regardless.

        Returns an outcome carrying the failure rather than propagating it, so the
        publish pipeline can still post a comment describing a run whose media is
        missing entirely.
        """
        attempted = self._primary.provider_type if self._primary.is_available() else self._fallback.provider_type
        try:
            artifact = self.upload_file(local_path, remote_filename, kind)
            return UploadOutcome(
                artifact=artifact,
                success=True,
                provider_attempted=attempted,
                fell_back=artifact.provider is not self._primary.provider_type,
            )
        except Exception as e:
            logger.error(f"All storage backends failed for {remote_filename}: {e}")
            return UploadOutcome(
                success=False,
                provider_attempted=attempted,
                fell_back=True,
                error_message=str(e),
            )
