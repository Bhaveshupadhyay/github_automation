"""Interface for media post-processing: video compression and GIF generation."""
from abc import ABC, abstractmethod

from automation.domain.media_processing import MediaArtifact, MediaProcessingResult


class IMediaProcessorService(ABC):
    """Abstract interface for FFmpeg-based media processing pipelines."""

    @abstractmethod
    def compress_video(
        self,
        input_path: str,
        output_path: str,
        crf: int = 28,
    ) -> MediaArtifact:
        """Re-encode a raw video recording into a compressed H.264 MP4.

        Args:
            input_path: Path to the raw .webm or .mp4 recording.
            output_path: Desired path for the compressed output MP4.
            crf: Constant Rate Factor for H.264 encoding (default: 28).

        Returns:
            MediaArtifact with output path and file size metadata.
        """
        pass

    @abstractmethod
    def generate_preview_gif(
        self,
        input_path: str,
        output_path: str,
        duration_seconds: int = 8,
        fps: int = 10,
        width: int = 640,
    ) -> MediaArtifact:
        """Extract a lightweight animated GIF preview from a video.

        Uses two-pass palette optimization for high-quality, small-size GIFs.

        Args:
            input_path: Path to the source video (compressed MP4 preferred).
            output_path: Desired path for the output GIF.
            duration_seconds: Number of seconds to extract (default: 8).
            fps: Frame rate of the output GIF (default: 10).
            width: Width of the output GIF in pixels (default: 640, height auto-scaled).

        Returns:
            MediaArtifact with output path and file size metadata.
        """
        pass

    @abstractmethod
    def process(
        self,
        raw_video_path: str,
        output_dir: str,
    ) -> MediaProcessingResult:
        """Full media processing pipeline: compress video + generate preview GIF.

        Args:
            raw_video_path: Path to the raw recording from Playwright or Maestro.
            output_dir: Directory to write compressed MP4 and preview GIF files.

        Returns:
            MediaProcessingResult containing both processed artifacts.
        """
        pass
