"""Unit tests for the QA service factories in automation.core.dependency."""
import pytest

from automation.core import get_media_processor_service, get_test_runner_service
from automation.services.ffmpeg_media_processor_service import FFmpegMediaProcessorService
from automation.services.maestro_test_runner_service import MaestroTestRunnerService
from automation.services.playwright_test_runner_service import PlaywrightTestRunnerService


class TestGetTestRunnerService:
    def test_default_is_playwright(self):
        assert isinstance(get_test_runner_service(), PlaywrightTestRunnerService)

    def test_maestro_receives_app_id(self):
        runner = get_test_runner_service("maestro", app_id="com.acme.mobile")

        assert isinstance(runner, MaestroTestRunnerService)
        assert runner._app_id == "com.acme.mobile"

    @pytest.mark.parametrize("runner_type", ["playwrite", "appium", ""])
    def test_unknown_runner_type_raises(self, runner_type):
        """A misspelling must fail instead of silently falling back to Playwright."""
        with pytest.raises(ValueError, match="Unsupported test runner type"):
            get_test_runner_service(runner_type)


class TestGetMediaProcessorService:
    def test_returns_ffmpeg_processor(self):
        assert isinstance(get_media_processor_service(), FFmpegMediaProcessorService)
