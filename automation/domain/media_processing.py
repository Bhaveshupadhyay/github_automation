"""Domain models for media processing: video compression and GIF generation."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class MediaArtifact(BaseModel):
    """A single processed media file (compressed video or preview GIF)."""
    source_path: str = Field(..., description="Absolute path to the raw input file")
    output_path: str = Field(..., description="Absolute path to the processed output file")
    artifact_type: Literal["compressed_video", "preview_gif"] = Field(
        ..., description="Type of media artifact produced"
    )
    file_size_bytes: int = Field(default=0, description="Output file size in bytes")
    duration_seconds: Optional[float] = Field(default=None, description="Media duration in seconds")


class MediaProcessingResult(BaseModel):
    """Outcome of the full media processing pipeline (compress + GIF)."""
    compressed_video: Optional[MediaArtifact] = Field(
        default=None, description="H.264 compressed MP4 artifact"
    )
    preview_gif: Optional[MediaArtifact] = Field(
        default=None, description="Animated preview GIF artifact"
    )
    success: bool = Field(default=False, description="Whether the processing pipeline completed successfully")
    error_message: Optional[str] = Field(default=None, description="Diagnostic error if processing failed")
