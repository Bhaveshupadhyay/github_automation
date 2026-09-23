"""Domain models for QA media storage and upload results."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class StorageProviderType(str, Enum):
    """Identifies which storage backend produced an upload."""
    R2 = "r2"
    GITHUB_ARTIFACT = "github_artifact"


class ArtifactKind(str, Enum):
    """Role a media file plays in the published QA report."""
    VIDEO = "video"
    GIF = "gif"
    TRACE = "trace"
    SCREENSHOT = "screenshot"


# Maps a file extension to the MIME content type storage backends must serve it with.
# R2/S3 default to application/octet-stream, which makes browsers download rather than
# play a video and stops GitHub rendering a GIF inline.
CONTENT_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".zip": "application/zip",
}

DEFAULT_CONTENT_TYPE = "application/octet-stream"


class UploadedArtifact(BaseModel):
    """A media file that has been published to a storage backend."""
    local_path: str = Field(..., description="Path to the source file on the runner")
    remote_key: str = Field(..., description="Object key or artifact-relative path at the destination")
    public_url: str = Field(..., description="URL the PR comment links to")
    kind: ArtifactKind = Field(..., description="Role this file plays in the report")
    content_type: str = Field(default=DEFAULT_CONTENT_TYPE, description="MIME type the file is served with")
    size_bytes: int = Field(default=0, description="File size in bytes")
    provider: StorageProviderType = Field(..., description="Backend that stored the file")

    @property
    def is_embeddable(self) -> bool:
        """Whether this URL can be rendered inline in GitHub markdown.

        GitHub Actions artifacts are authenticated zip downloads, so a URL from that
        provider can only ever be a link, never an `![](...)` embed.
        """
        return self.provider is not StorageProviderType.GITHUB_ARTIFACT


class UploadOutcome(BaseModel):
    """Result of attempting to publish one file, including the failure path."""
    artifact: Optional[UploadedArtifact] = Field(default=None, description="The upload, when it succeeded")
    success: bool = Field(default=False, description="Whether the file was stored somewhere")
    provider_attempted: Optional[StorageProviderType] = Field(
        default=None, description="Backend tried first, whether or not it succeeded"
    )
    fell_back: bool = Field(default=False, description="True when the primary backend failed and the fallback was used")
    error_message: Optional[str] = Field(default=None, description="Diagnostic when no backend accepted the file")
