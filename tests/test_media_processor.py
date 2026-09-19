"""Unit tests for FFmpegMediaProcessorService."""
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from automation.domain.media_processing import MediaArtifact, MediaProcessingResult
from automation.services.ffmpeg_media_processor_service import (
    FFmpegMediaProcessorService,
    VIDEO_TARGET_MAX_BYTES,
    GIF_TARGET_MAX_BYTES,
)


class TestCompressVideoCommand:
    """Verify correct FFmpeg command is constructed for H.264 compression."""

    @patch("automation.services.ffmpeg_media_processor_service.subprocess.run")
    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_compress_command_contains_h264_codec(self, mock_available, mock_run):
        """FFmpeg command should use libx264 video codec."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "test.webm")
            output_file = os.path.join(tmp_dir, "test.mp4")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")

            def ffmpeg_side_effect(*args, **kwargs):
                with open(output_file, "wb") as f:
                    f.write(b"x" * (1024 * 1024))  # 1 MB
                return MagicMock(returncode=0, stderr="", stdout="")

            mock_run.side_effect = ffmpeg_side_effect

            service.compress_video(input_file, output_file, crf=28)

            cmd_args = mock_run.call_args_list[0][0][0]
            assert "libx264" in cmd_args
            assert "-crf" in cmd_args
            assert "28" in cmd_args
            assert "aac" in cmd_args
            assert "+faststart" in cmd_args

    @patch("automation.services.ffmpeg_media_processor_service.subprocess.run")
    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_compress_uses_correct_crf(self, mock_available, mock_run):
        """Custom CRF value should be passed to FFmpeg."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "test.webm")
            output_file = os.path.join(tmp_dir, "test.mp4")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")

            def ffmpeg_side_effect(*args, **kwargs):
                with open(output_file, "wb") as f:
                    f.write(b"x" * (1024 * 1024))
                return MagicMock(returncode=0, stderr="", stdout="")

            mock_run.side_effect = ffmpeg_side_effect

            service.compress_video(input_file, output_file, crf=23)

            cmd_args = mock_run.call_args_list[0][0][0]
            assert "23" in cmd_args

    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_compress_missing_input_raises_error(self, mock_available):
        """Missing input file should raise FileNotFoundError."""
        service = FFmpegMediaProcessorService()

        with pytest.raises(FileNotFoundError, match="Input video not found"):
            service.compress_video("/nonexistent/video.webm", "/tmp/output.mp4")


class TestGifGenerationTwoPass:
    """Verify two-pass palette-based GIF generation command is correct."""

    @patch("automation.services.ffmpeg_media_processor_service.subprocess.run")
    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_gif_uses_two_pass_palette(self, mock_available, mock_run):
        """GIF generation should execute two FFmpeg passes (palette + encode)."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "test.mp4")
            output_file = os.path.join(tmp_dir, "test.gif")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")

            def ffmpeg_side_effect(*args, **kwargs):
                cmd = args[0]
                if "palettegen" in " ".join(cmd):
                    palette_path = [a for a in cmd if a.endswith(".png")]
                    if palette_path:
                        with open(palette_path[0], "wb") as f:
                            f.write(b"fake palette")
                else:
                    with open(output_file, "wb") as f:
                        f.write(b"x" * (512 * 1024))  # 512 KB
                return MagicMock(returncode=0, stderr="", stdout="")

            mock_run.side_effect = ffmpeg_side_effect

            service.generate_preview_gif(input_file, output_file, duration_seconds=8, fps=10, width=640)

            assert mock_run.call_count == 2

            pass1_cmd = " ".join(mock_run.call_args_list[0][0][0])
            assert "palettegen" in pass1_cmd

            pass2_cmd = " ".join(mock_run.call_args_list[1][0][0])
            assert "paletteuse" in pass2_cmd

    @patch("automation.services.ffmpeg_media_processor_service.subprocess.run")
    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_gif_respects_duration_and_fps(self, mock_available, mock_run):
        """Duration and FPS parameters should be passed to FFmpeg."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "test.mp4")
            output_file = os.path.join(tmp_dir, "test.gif")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")

            def ffmpeg_side_effect(*args, **kwargs):
                cmd = args[0]
                if "palettegen" in " ".join(cmd):
                    palette_path = [a for a in cmd if a.endswith(".png")]
                    if palette_path:
                        with open(palette_path[0], "wb") as f:
                            f.write(b"fake palette")
                else:
                    with open(output_file, "wb") as f:
                        f.write(b"x" * (512 * 1024))
                return MagicMock(returncode=0, stderr="", stdout="")

            mock_run.side_effect = ffmpeg_side_effect

            service.generate_preview_gif(
                input_file, output_file, duration_seconds=10, fps=15, width=800
            )

            pass1_cmd = " ".join(mock_run.call_args_list[0][0][0])
            assert "-t" in pass1_cmd
            assert "10" in pass1_cmd
            assert "fps=15" in pass1_cmd
            assert "800" in pass1_cmd

            # "-t" must precede the video input in both passes so it trims the video
            for call in mock_run.call_args_list[:2]:
                args = call[0][0]
                t_index = args.index("-t")
                assert args[t_index + 1] == "10"
                assert t_index < args.index("-i")

    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_gif_missing_input_raises_error(self, mock_available):
        """Missing input file should raise FileNotFoundError."""
        service = FFmpegMediaProcessorService()

        with pytest.raises(FileNotFoundError, match="Input video not found"):
            service.generate_preview_gif("/nonexistent/video.mp4", "/tmp/output.gif")


class TestFFmpegNotInstalled:
    """Verify descriptive error when FFmpeg is not available."""

    def test_compress_without_ffmpeg_raises_error(self):
        """Service should raise RuntimeError with descriptive message."""
        with patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=False):
            service = FFmpegMediaProcessorService(ffmpeg_binary="/nonexistent/ffmpeg")

            with tempfile.TemporaryDirectory() as tmp_dir:
                input_file = os.path.join(tmp_dir, "test.webm")
                with open(input_file, "wb") as f:
                    f.write(b"fake video data")

                with pytest.raises(RuntimeError, match="FFmpeg binary not found"):
                    service.compress_video(input_file, os.path.join(tmp_dir, "out.mp4"))

    def test_gif_without_ffmpeg_raises_error(self):
        with patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=False):
            service = FFmpegMediaProcessorService(ffmpeg_binary="/nonexistent/ffmpeg")

            with tempfile.TemporaryDirectory() as tmp_dir:
                input_file = os.path.join(tmp_dir, "test.mp4")
                with open(input_file, "wb") as f:
                    f.write(b"fake video data")

                with pytest.raises(RuntimeError, match="FFmpeg binary not found"):
                    service.generate_preview_gif(input_file, os.path.join(tmp_dir, "out.gif"))


class TestOutputSizeValidation:
    """Verify warnings when output exceeds target sizes."""

    @patch("automation.services.ffmpeg_media_processor_service.subprocess.run")
    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_large_video_logs_warning(self, mock_available, mock_run, caplog):
        """Video exceeding 5MB target should log a warning."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "test.webm")
            output_file = os.path.join(tmp_dir, "test.mp4")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")

            def ffmpeg_side_effect(*args, **kwargs):
                with open(output_file, "wb") as f:
                    f.write(b"x" * (6 * 1024 * 1024))  # 6 MB
                return MagicMock(returncode=0, stderr="", stdout="")

            mock_run.side_effect = ffmpeg_side_effect

            import logging
            with caplog.at_level(logging.WARNING):
                service.compress_video(input_file, output_file)

            assert any("exceeds target size" in r.message for r in caplog.records)


class TestFullProcessPipeline:
    """Tests for the combined process() pipeline."""

    @patch("automation.services.ffmpeg_media_processor_service.subprocess.run")
    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_process_returns_both_artifacts(self, mock_available, mock_run):
        """Full pipeline should produce both compressed video and preview GIF."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "recording.webm")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")

            def ffmpeg_side_effect(*args, **kwargs):
                cmd = args[0]
                output_candidates = [a for a in cmd if tmp_dir in a and not a.startswith("-")]
                if output_candidates:
                    out = output_candidates[-1]
                    with open(out, "wb") as f:
                        f.write(b"x" * (1024 * 1024))
                return MagicMock(returncode=0, stderr="", stdout="")

            mock_run.side_effect = ffmpeg_side_effect

            result = service.process(input_file, tmp_dir)

            assert result.success is True
            assert result.compressed_video is not None
            assert result.preview_gif is not None

    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_process_handles_compression_failure(self, mock_available):
        """If compression fails, GIF should still be attempted from raw input."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "recording.webm")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")

            with patch.object(service, "compress_video", side_effect=RuntimeError("FFmpeg crash")):
                with patch.object(service, "generate_preview_gif") as mock_gif:
                    mock_gif.return_value = MediaArtifact(
                        source_path=input_file,
                        output_path=os.path.join(tmp_dir, "preview.gif"),
                        artifact_type="preview_gif",
                        file_size_bytes=512 * 1024,
                    )
                    result = service.process(input_file, tmp_dir)

            # Partial output is kept, but the pipeline as a whole did not succeed
            assert result.success is False
            assert result.compressed_video is None
            assert result.preview_gif is not None
            assert result.error_message is not None
            assert "compression failed" in result.error_message.lower()

    @patch.object(FFmpegMediaProcessorService, "is_ffmpeg_available", return_value=True)
    def test_process_forwards_options(self, mock_available):
        """CRF and GIF options passed to process() reach both stages."""
        service = FFmpegMediaProcessorService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = os.path.join(tmp_dir, "recording.webm")
            with open(input_file, "wb") as f:
                f.write(b"fake video data")
            # process() only feeds the compressed file to the GIF stage if it exists
            with open(os.path.join(tmp_dir, "recording_compressed.mp4"), "wb") as f:
                f.write(b"fake compressed data")

            with patch.object(service, "compress_video") as mock_compress, \
                    patch.object(service, "generate_preview_gif") as mock_gif:
                mock_compress.return_value = MediaArtifact(
                    source_path=input_file,
                    output_path=input_file,
                    artifact_type="compressed_video",
                )
                mock_gif.return_value = MediaArtifact(
                    source_path=input_file,
                    output_path=input_file,
                    artifact_type="preview_gif",
                )
                service.process(
                    input_file, tmp_dir, crf=35, gif_duration_seconds=4, gif_fps=5, gif_width=320
                )

            assert mock_compress.call_args.kwargs["crf"] == 35
            assert mock_gif.call_args.kwargs == {"duration_seconds": 4, "fps": 5, "width": 320}
