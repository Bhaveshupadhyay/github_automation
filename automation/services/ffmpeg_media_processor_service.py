"""Service for FFmpeg-based media post-processing: H.264 compression and optimized GIF generation."""
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from automation.domain.media_processing import MediaArtifact, MediaProcessingResult
from automation.interfaces.media_processor_interface import IMediaProcessorService

logger = logging.getLogger(__name__)

# Target file size thresholds for validation warnings
VIDEO_TARGET_MAX_BYTES = 5 * 1024 * 1024     # 5 MB for 60s recordings
GIF_TARGET_MAX_BYTES = 2.5 * 1024 * 1024     # 2.5 MB for inline GitHub previews


class FFmpegMediaProcessorService(IMediaProcessorService):
    """Processes raw test recordings into compressed MP4 and preview GIFs using FFmpeg.

    Features:
    - H.264 video compression with CRF-based quality control
    - Two-pass palette-optimized GIF generation for high quality at small sizes
    - Automatic binary availability detection
    - File size validation against target thresholds
    """

    def __init__(self, ffmpeg_binary: Optional[str] = None) -> None:
        self._ffmpeg_binary = ffmpeg_binary or shutil.which("ffmpeg") or "ffmpeg"
        if not self.is_ffmpeg_available():
            logger.warning(
                f"FFmpeg binary not found at '{self._ffmpeg_binary}'. "
                "Media processing will fail. Install FFmpeg: https://ffmpeg.org/download.html"
            )

    def is_ffmpeg_available(self) -> bool:
        """Returns True if the FFmpeg binary is discoverable and executable."""
        return shutil.which(self._ffmpeg_binary) is not None

    def _run_ffmpeg(self, args: list[str], description: str) -> subprocess.CompletedProcess:
        """Execute an FFmpeg command with standard error handling.

        Args:
            args: Command arguments (without the ffmpeg binary itself).
            description: Human-readable description of the operation for logging.

        Returns:
            CompletedProcess result.

        Raises:
            RuntimeError: If FFmpeg exits with a non-zero return code.
        """
        cmd = [self._ffmpeg_binary] + args
        logger.info(f"FFmpeg {description}: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for media processing
            )

            if result.returncode != 0:
                stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
                raise RuntimeError(
                    f"FFmpeg {description} failed (exit code {result.returncode}): {stderr_tail}"
                )

            return result

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"FFmpeg {description} timed out after 300 seconds."
            )

    def _get_video_duration(self, video_path: str) -> Optional[float]:
        """Extract video duration in seconds using ffprobe."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None

        try:
            result = subprocess.run(
                [
                    ffprobe, "-v", "quiet",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return None

    def compress_video(
        self,
        input_path: str,
        output_path: str,
        crf: int = 28,
    ) -> MediaArtifact:
        """Re-encode a raw recording into a compressed H.264 MP4.

        Uses H.264 video codec, AAC audio codec, and CRF-based quality control.
        The -movflags +faststart flag enables progressive streaming.
        """
        in_p = Path(input_path)
        out_p = Path(output_path)

        if not in_p.is_file():
            raise FileNotFoundError(f"Input video not found: {in_p.resolve()}")

        if not self.is_ffmpeg_available():
            raise RuntimeError(
                f"FFmpeg binary not found at '{self._ffmpeg_binary}'. "
                "Cannot compress video without FFmpeg installed."
            )

        out_p.parent.mkdir(parents=True, exist_ok=True)

        self._run_ffmpeg(
            [
                "-y",                       # Overwrite output
                "-i", str(in_p),            # Input file
                "-c:v", "libx264",          # H.264 video codec
                "-preset", "medium",        # Encoding speed/quality tradeoff
                "-crf", str(crf),           # Constant Rate Factor (quality)
                "-c:a", "aac",              # AAC audio codec
                "-movflags", "+faststart",  # Enable progressive streaming
                str(out_p),
            ],
            description=f"H.264 compression (CRF {crf})",
        )

        file_size = out_p.stat().st_size
        duration = self._get_video_duration(str(out_p))

        if file_size > VIDEO_TARGET_MAX_BYTES:
            logger.warning(
                f"Compressed video exceeds target size: "
                f"{file_size / (1024*1024):.1f} MB > {VIDEO_TARGET_MAX_BYTES / (1024*1024):.1f} MB. "
                f"Consider increasing CRF (current: {crf}) or reducing recording duration."
            )

        logger.info(
            f"Video compressed: {in_p.name} -> {out_p.name} "
            f"({file_size / (1024*1024):.2f} MB"
            f"{f', {duration:.1f}s' if duration else ''})"
        )

        return MediaArtifact(
            source_path=str(in_p.resolve()),
            output_path=str(out_p.resolve()),
            artifact_type="compressed_video",
            file_size_bytes=file_size,
            duration_seconds=duration,
        )

    def generate_preview_gif(
        self,
        input_path: str,
        output_path: str,
        duration_seconds: int = 8,
        fps: int = 10,
        width: int = 640,
    ) -> MediaArtifact:
        """Generate a lightweight animated GIF preview using two-pass palette optimization.

        Pass 1: Generates an optimized color palette from the source video.
        Pass 2: Applies the palette for high-quality, small-size GIF output.
        """
        in_p = Path(input_path)
        out_p = Path(output_path)

        if not in_p.is_file():
            raise FileNotFoundError(f"Input video not found: {in_p.resolve()}")

        if not self.is_ffmpeg_available():
            raise RuntimeError(
                f"FFmpeg binary not found at '{self._ffmpeg_binary}'. "
                "Cannot generate GIF without FFmpeg installed."
            )

        out_p.parent.mkdir(parents=True, exist_ok=True)

        # Temporary palette file in the same directory as output
        palette_path = out_p.parent / f".palette_{out_p.stem}.png"

        try:
            # Pass 1: Generate optimized color palette
            # "-t" goes before "-i" so it trims the video input, not an output or the palette input
            self._run_ffmpeg(
                [
                    "-y",
                    "-t", str(duration_seconds),
                    "-i", str(in_p),
                    "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen",
                    str(palette_path),
                ],
                description="GIF palette generation (pass 1/2)",
            )

            # Pass 2: Apply palette for high-quality GIF
            self._run_ffmpeg(
                [
                    "-y",
                    "-t", str(duration_seconds),
                    "-i", str(in_p),
                    "-i", str(palette_path),
                    "-filter_complex",
                    f"fps={fps},scale={width}:-1:flags=lanczos[x];[x][1:v]paletteuse",
                    str(out_p),
                ],
                description="GIF encoding with palette (pass 2/2)",
            )

        finally:
            # Clean up temporary palette file
            if palette_path.is_file():
                try:
                    palette_path.unlink()
                except OSError:
                    pass

        file_size = out_p.stat().st_size

        if file_size > GIF_TARGET_MAX_BYTES:
            logger.warning(
                f"Preview GIF exceeds target size: "
                f"{file_size / (1024*1024):.1f} MB > {GIF_TARGET_MAX_BYTES / (1024*1024):.1f} MB. "
                f"Consider reducing duration (current: {duration_seconds}s) or fps (current: {fps})."
            )

        logger.info(
            f"Preview GIF generated: {out_p.name} "
            f"({file_size / (1024*1024):.2f} MB, {duration_seconds}s @ {fps}fps, {width}px wide)"
        )

        return MediaArtifact(
            source_path=str(in_p.resolve()),
            output_path=str(out_p.resolve()),
            artifact_type="preview_gif",
            file_size_bytes=file_size,
            duration_seconds=float(duration_seconds),
        )

    def process(
        self,
        raw_video_path: str,
        output_dir: str,
        crf: int = 28,
        gif_duration_seconds: int = 8,
        gif_fps: int = 10,
        gif_width: int = 640,
    ) -> MediaProcessingResult:
        """Full media processing pipeline: compress video then generate preview GIF.

        If compression succeeds, uses the compressed MP4 as input for GIF generation
        (smaller file = faster GIF processing).

        Returns a result even on partial failure — e.g., video compresses but GIF fails —
        with any artifact that was produced, but success is True only when both succeed.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        raw_path = Path(raw_video_path)
        video_stem = raw_path.stem

        compressed_path = str(out_dir / f"{video_stem}_compressed.mp4")
        gif_path = str(out_dir / f"{video_stem}_preview.gif")

        compressed_video: Optional[MediaArtifact] = None
        preview_gif: Optional[MediaArtifact] = None
        errors: list[str] = []

        # Step 1: Compress video
        try:
            compressed_video = self.compress_video(raw_video_path, compressed_path, crf=crf)
        except Exception as e:
            error_msg = f"Video compression failed: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

        # Step 2: Generate preview GIF (use compressed video if available, else raw)
        gif_input = compressed_path if compressed_video else raw_video_path
        try:
            # Verify input exists before attempting GIF generation
            if Path(gif_input).is_file():
                preview_gif = self.generate_preview_gif(
                    gif_input,
                    gif_path,
                    duration_seconds=gif_duration_seconds,
                    fps=gif_fps,
                    width=gif_width,
                )
            else:
                error_msg = f"GIF input not available: {gif_input}"
                logger.error(error_msg)
                errors.append(error_msg)
        except Exception as e:
            error_msg = f"GIF generation failed: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

        success = compressed_video is not None and preview_gif is not None
        error_message = "; ".join(errors) if errors else None

        return MediaProcessingResult(
            compressed_video=compressed_video,
            preview_gif=preview_gif,
            success=success,
            error_message=error_message,
        )
