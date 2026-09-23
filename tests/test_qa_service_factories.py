"""Unit tests for the QA service factories in automation.core.dependency."""
import pytest

from automation.core import (
    get_github_artifact_storage_provider,
    get_media_processor_service,
    get_pr_comment_publisher,
    get_qa_report_formatter,
    get_r2_storage_provider,
    get_storage_provider,
    get_test_runner_service,
)
from automation.domain.storage import StorageProviderType
from automation.services.fallback_storage_provider import FallbackStorageProvider
from automation.services.ffmpeg_media_processor_service import FFmpegMediaProcessorService
from automation.services.github_artifact_storage_provider import GitHubArtifactStorageProvider
from automation.services.github_pr_comment_publisher import GitHubPRCommentPublisher
from automation.services.maestro_test_runner_service import MaestroTestRunnerService
from automation.services.playwright_test_runner_service import PlaywrightTestRunnerService
from automation.services.qa_report_formatter import QAReportFormatter
from automation.services.r2_storage_provider import R2StorageProvider


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


class TestStorageFactories:
    def test_r2_provider_is_returned(self):
        assert isinstance(get_r2_storage_provider(), R2StorageProvider)

    def test_artifact_provider_is_returned(self):
        assert isinstance(get_github_artifact_storage_provider(), GitHubArtifactStorageProvider)

    def test_default_chain_is_r2_then_artifacts(self):
        chain = get_storage_provider()

        assert isinstance(chain, FallbackStorageProvider)
        assert isinstance(chain._primary, R2StorageProvider)
        assert isinstance(chain._fallback, GitHubArtifactStorageProvider)

    def test_chain_accepts_injected_providers(self):
        primary = GitHubArtifactStorageProvider(github_output_path="")
        chain = get_storage_provider(primary=primary)

        assert chain._primary is primary

    def test_chain_is_always_available_via_the_fallback(self, monkeypatch):
        """With no R2 credentials the chain must still accept uploads."""
        for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL"):
            monkeypatch.delenv(var, raising=False)

        chain = get_storage_provider()

        assert chain.is_available() is True
        assert chain.provider_type is StorageProviderType.R2  # not yet used


class TestPublisherFactories:
    def test_pr_comment_publisher_is_returned(self):
        assert isinstance(get_pr_comment_publisher(), GitHubPRCommentPublisher)

    def test_bot_login_is_injected(self):
        publisher = get_pr_comment_publisher(token="t", bot_login="my-bot")

        assert publisher._bot_login == "my-bot"

    def test_report_formatter_is_returned(self):
        assert isinstance(get_qa_report_formatter(), QAReportFormatter)
