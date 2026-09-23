"""Interface for publishing QA media to a storage backend."""
from abc import ABC, abstractmethod

from automation.domain.storage import ArtifactKind, StorageProviderType, UploadedArtifact


class IStorageProvider(ABC):
    """Abstract contract for hosting recorded test media.

    Implementations must not know how the media was produced, and callers must not
    know where it is stored beyond the returned URL.
    """

    @property
    @abstractmethod
    def provider_type(self) -> StorageProviderType:
        """Identifies this backend in reports and logs."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this backend is configured and usable.

        Checked before an upload is attempted so a missing credential degrades to the
        fallback backend rather than raising mid-pipeline.
        """
        pass

    @abstractmethod
    def upload_file(
        self,
        local_path: str,
        remote_filename: str,
        kind: ArtifactKind,
    ) -> UploadedArtifact:
        """Publish one file and return its retrievable URL.

        Args:
            local_path: Path to the file on the runner.
            remote_filename: Destination name, already namespaced by repo/PR/commit.
            kind: Role the file plays in the report, used to pick the content type.

        Returns:
            UploadedArtifact describing where the file landed.

        Raises:
            RuntimeError: If the upload fails. Callers are expected to fall back.
        """
        pass
