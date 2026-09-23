"""CLI entry point for FFmpeg media post-processing: video compression and GIF generation.

Usage:
    qa-media --input VIDEO [--output-dir DIR] [--crf 28] [--gif-duration 8] [--gif-fps 10] [--gif-width 640]

Compresses raw test recordings into H.264 MP4 files and generates lightweight
animated GIF previews for embedding in GitHub PR comments.
"""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qa-media")


def main():
    parser = argparse.ArgumentParser(
        description="Process raw test recordings: compress to H.264 MP4 and generate preview GIF.",
        prog="qa-media",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the raw video recording (.webm or .mp4).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for processed files. Defaults to same directory as input.",
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=28,
        help="H.264 Constant Rate Factor for compression quality (default: 28, lower = better quality).",
    )
    parser.add_argument(
        "--gif-duration",
        type=int,
        default=8,
        help="Duration in seconds to extract for GIF preview (default: 8).",
    )
    parser.add_argument(
        "--gif-fps",
        type=int,
        default=10,
        help="Frame rate of the preview GIF (default: 10).",
    )
    parser.add_argument(
        "--gif-width",
        type=int,
        default=640,
        help="Width of the preview GIF in pixels (default: 640, height auto-scaled).",
    )
    parser.add_argument(
        "--result-json",
        default=None,
        help="Write the MediaProcessingResult as JSON to this path, for qa-publish to consume.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--compress-only",
        action="store_true",
        help="Only compress video, skip GIF generation.",
    )
    mode_group.add_argument(
        "--gif-only",
        action="store_true",
        help="Only generate GIF, skip video compression.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        logger.error(f"Input video not found: {input_path}")
        return 1

    output_dir = args.output_dir or str(input_path.parent)

    from automation.core import get_media_processor_service
    from automation.domain.media_processing import MediaProcessingResult

    service = get_media_processor_service()
    result: MediaProcessingResult | None = None

    if not service.is_ffmpeg_available():
        message = "FFmpeg is not installed or not on PATH. Install FFmpeg: https://ffmpeg.org/download.html"
        logger.error(message)
        _write_result_json(args.result_json, MediaProcessingResult(success=False, error_message=message))
        return 1

    logger.info(f"Input: {input_path}")
    logger.info(f"Output directory: {output_dir}")

    if args.compress_only:
        # Compress only
        out_path = str(Path(output_dir) / f"{input_path.stem}_compressed.mp4")
        try:
            artifact = service.compress_video(str(input_path), out_path, crf=args.crf)
            result = MediaProcessingResult(compressed_video=artifact, success=True)
            logger.info(
                f"✅ Video compressed: {artifact.output_path} "
                f"({artifact.file_size_bytes / (1024*1024):.2f} MB)"
            )
        except Exception as e:
            logger.error(f"❌ Compression failed: {e}")
            _write_result_json(args.result_json, MediaProcessingResult(success=False, error_message=str(e)))
            return 1

    elif args.gif_only:
        # GIF only
        out_path = str(Path(output_dir) / f"{input_path.stem}_preview.gif")
        try:
            artifact = service.generate_preview_gif(
                str(input_path), out_path,
                duration_seconds=args.gif_duration,
                fps=args.gif_fps,
                width=args.gif_width,
            )
            result = MediaProcessingResult(preview_gif=artifact, success=True)
            logger.info(
                f"✅ GIF generated: {artifact.output_path} "
                f"({artifact.file_size_bytes / (1024*1024):.2f} MB)"
            )
        except Exception as e:
            logger.error(f"❌ GIF generation failed: {e}")
            _write_result_json(args.result_json, MediaProcessingResult(success=False, error_message=str(e)))
            return 1

    else:
        # Full pipeline
        try:
            result = service.process(
                str(input_path),
                output_dir,
                crf=args.crf,
                gif_duration_seconds=args.gif_duration,
                gif_fps=args.gif_fps,
                gif_width=args.gif_width,
            )

            if result.success:
                logger.info("✅ Media processing complete:")
            if result.compressed_video:
                logger.info(
                    f"  📹 Video: {result.compressed_video.output_path} "
                    f"({result.compressed_video.file_size_bytes / (1024*1024):.2f} MB)"
                )
            if result.preview_gif:
                logger.info(
                    f"  🎞️  GIF:   {result.preview_gif.output_path} "
                    f"({result.preview_gif.file_size_bytes / (1024*1024):.2f} MB)"
                )
            if not result.success:
                logger.error(f"❌ Media processing failed: {result.error_message}")
                _write_result_json(args.result_json, result)
                return 1

        except Exception as e:
            logger.error(f"❌ Media processing failed: {e}")
            _write_result_json(args.result_json, MediaProcessingResult(success=False, error_message=str(e)))
            return 1

    _write_result_json(args.result_json, result)
    return 0


def _write_result_json(path, result) -> None:
    """Persist the processing result for the publish step to consume.

    Written even when processing failed, so qa-publish can still post a comment that
    reports the run without its media rather than silently omitting the section.
    """
    if not path or result is None:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        logger.info(f"Wrote media result JSON: {path}")
    except OSError as e:
        logger.warning(f"Could not write media result JSON to {path}: {e}")


if __name__ == "__main__":
    sys.exit(main())
