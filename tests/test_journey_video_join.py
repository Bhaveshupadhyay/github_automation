"""A passing run publishes every journey's recording, joined in plan order."""
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from automation.domain.test_run import TestCaseResult, TestOutcome, TestRunResult
from automation.qa_test_runner_cli import _join_journey_videos
from automation.services.ffmpeg_media_processor_service import FFmpegMediaProcessorService


def _result(paths) -> TestRunResult:
    cases = [
        TestCaseResult(journey_name=f"J{i}", outcome=TestOutcome.PASSED, video_path=p) for i, p in enumerate(paths)
    ]
    return TestRunResult(overall_outcome=TestOutcome.PASSED, total_tests=len(cases), passed=len(cases), test_results=cases)


def _files(tmp_path: Path, n: int) -> list:
    paths = []
    for i in range(n):
        p = tmp_path / f"j{i}.webm"
        p.write_bytes(b"x")
        paths.append(str(p))
    return paths


class TestJoinJourneyVideos:
    def test_joins_every_recording_in_plan_order(self, tmp_path):
        paths = _files(tmp_path, 3)
        service = MagicMock()
        service.concatenate_videos.return_value = str(tmp_path / "all-journeys.mp4")

        with patch("automation.core.get_media_processor_service", return_value=service):
            joined = _join_journey_videos(_result(paths), str(tmp_path))

        assert joined == str(tmp_path / "all-journeys.mp4")
        service.concatenate_videos.assert_called_once_with(paths, str(tmp_path / "all-journeys.mp4"))

    def test_a_single_recording_is_not_joined(self, tmp_path):
        with patch("automation.core.get_media_processor_service") as factory:
            assert _join_journey_videos(_result(_files(tmp_path, 1)), str(tmp_path)) is None
        factory.assert_not_called()

    def test_missing_recordings_are_skipped(self, tmp_path):
        paths = _files(tmp_path, 2) + [str(tmp_path / "gone.webm")]
        service = MagicMock()

        with patch("automation.core.get_media_processor_service", return_value=service):
            _join_journey_videos(_result(paths), str(tmp_path))

        assert service.concatenate_videos.call_args.args[0] == paths[:2]

    def test_a_failed_join_falls_back_to_none(self, tmp_path):
        service = MagicMock()
        service.concatenate_videos.side_effect = RuntimeError("ffmpeg broke")

        with patch("automation.core.get_media_processor_service", return_value=service):
            assert _join_journey_videos(_result(_files(tmp_path, 2)), str(tmp_path)) is None


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg is not installed")
def test_ffmpeg_joins_recordings_end_to_end(tmp_path):
    """Two clips with restarted timestamps, as one browser context per journey records them."""
    clips = []
    for i, seconds in enumerate((1, 2)):
        clip = tmp_path / f"clip{i}.webm"
        subprocess.run(
            ["ffmpeg", "-v", "quiet", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=10:duration={seconds}",
             "-c:v", "libvpx", str(clip)],
            check=True,
        )
        clips.append(str(clip))

    out = FFmpegMediaProcessorService().concatenate_videos(clips, str(tmp_path / "all.mp4"))

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", out],
        capture_output=True, text=True, check=True,
    )
    assert float(probe.stdout) == pytest.approx(3.0, abs=0.3)
