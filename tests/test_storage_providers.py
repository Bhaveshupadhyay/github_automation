"""Unit tests for the QA media storage providers and the fallback chain."""
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from automation.domain.storage import ArtifactKind, StorageProviderType, UploadedArtifact
from automation.services.fallback_storage_provider import FallbackStorageProvider
from automation.services.github_artifact_storage_provider import (
    STAGING_DIR_OUTPUT_KEY,
    GitHubArtifactStorageProvider,
)
from automation.services.r2_storage_provider import (
    LIFECYCLE_RULE_ID,
    OBJECT_PREFIX,
    R2StorageProvider,
    build_remote_key,
)

R2_ENV = {
    "account_id": "acct123",
    "access_key_id": "key",
    "secret_access_key": "secret",
    "bucket": "qa-media",
    "public_base_url": "https://media.example.com",
}


@pytest.fixture
def video_file(tmp_path: Path) -> str:
    path = tmp_path / "run.mp4"
    path.write_bytes(b"x" * 2048)
    return str(path)


class TestRemoteKey:
    def test_key_is_namespaced_by_repo_pr_and_commit(self):
        key = build_remote_key("acme/web", 42, "abcdef1234567890", "run.mp4")

        assert key == f"{OBJECT_PREFIX}/acme_web/pr-42/abcdef123456/run.mp4"

    def test_distinct_commits_produce_distinct_keys(self):
        """GitHub caches images by URL, so a reused key serves a stale GIF."""
        first = build_remote_key("acme/web", 42, "aaaaaaaaaaaa", "preview.gif")
        second = build_remote_key("acme/web", 42, "bbbbbbbbbbbb", "preview.gif")

        assert first != second

    def test_directory_traversal_in_filename_is_stripped(self):
        key = build_remote_key("acme/web", 42, "abc123", "../../../etc/passwd")

        assert ".." not in key
        assert key.endswith("/passwd")


class TestContentTypes:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("run.mp4", "video/mp4"),
            ("run.webm", "video/webm"),
            ("preview.gif", "image/gif"),
            ("trace.zip", "application/zip"),
            ("shot.png", "image/png"),
            ("mystery.bin", "application/octet-stream"),
        ],
    )
    def test_content_type_is_resolved_by_extension(self, filename, expected):
        """Without an explicit type, R2 serves octet-stream and the GIF will not render."""
        assert R2StorageProvider.resolve_content_type(filename) == expected

    def test_extension_matching_is_case_insensitive(self):
        assert R2StorageProvider.resolve_content_type("RUN.MP4") == "video/mp4"


class TestR2Availability:
    def test_available_when_fully_configured(self):
        assert R2StorageProvider(**R2_ENV).is_available() is True

    @pytest.mark.parametrize("missing", list(R2_ENV.keys()))
    def test_unavailable_when_any_setting_is_absent(self, missing, monkeypatch):
        # Clear the environment so defaults cannot mask the missing argument.
        for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL"):
            monkeypatch.delenv(var, raising=False)
        config = {**R2_ENV, missing: ""}

        assert R2StorageProvider(**config).is_available() is False

    def test_explicit_endpoint_makes_account_id_redundant(self, monkeypatch):
        monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
        config = {**R2_ENV, "account_id": "", "endpoint_url": "https://s3.example.com"}

        assert R2StorageProvider(**config).is_available() is True

    def test_endpoint_url_is_derived_from_account_id(self):
        provider = R2StorageProvider(**R2_ENV)

        assert provider.endpoint_url == "https://acct123.r2.cloudflarestorage.com"


class TestR2Upload:
    def test_upload_sets_the_content_type_and_returns_a_public_url(self, video_file):
        provider = R2StorageProvider(**R2_ENV)
        client = MagicMock()
        provider._client = client

        artifact = provider.upload_file(video_file, "qa/acme_web/pr-42/abc/run.mp4", ArtifactKind.VIDEO)

        _, kwargs = client.upload_file.call_args
        assert kwargs["ExtraArgs"] == {"ContentType": "video/mp4"}
        assert kwargs["Bucket"] == "qa-media"
        assert artifact.public_url == "https://media.example.com/qa/acme_web/pr-42/abc/run.mp4"
        assert artifact.provider is StorageProviderType.R2
        assert artifact.size_bytes == 2048

    def test_missing_file_raises(self, tmp_path):
        provider = R2StorageProvider(**R2_ENV)
        provider._client = MagicMock()

        with pytest.raises(RuntimeError, match="missing file"):
            provider.upload_file(str(tmp_path / "nope.mp4"), "qa/nope.mp4", ArtifactKind.VIDEO)

    def test_client_error_is_wrapped_so_callers_can_fall_back(self, video_file):
        provider = R2StorageProvider(**R2_ENV)
        client = MagicMock()
        client.upload_file.side_effect = Exception("connection reset")
        provider._client = client

        with pytest.raises(RuntimeError, match="R2 upload failed"):
            provider.upload_file(video_file, "qa/run.mp4", ArtifactKind.VIDEO)

    def test_r2_artifacts_are_embeddable(self, video_file):
        provider = R2StorageProvider(**R2_ENV)
        provider._client = MagicMock()

        artifact = provider.upload_file(video_file, "qa/run.mp4", ArtifactKind.VIDEO)

        assert artifact.is_embeddable is True


class TestLifecyclePolicy:
    def test_rule_targets_the_qa_prefix_with_a_30_day_expiry(self):
        provider = R2StorageProvider(**R2_ENV)
        client = MagicMock()
        provider._client = client

        assert provider.apply_lifecycle_policy() is True

        _, kwargs = client.put_bucket_lifecycle_configuration.call_args
        rule = kwargs["LifecycleConfiguration"]["Rules"][0]
        assert rule["ID"] == LIFECYCLE_RULE_ID
        assert rule["Status"] == "Enabled"
        assert rule["Expiration"]["Days"] == 30
        assert rule["Filter"]["Prefix"] == f"{OBJECT_PREFIX}/"

    def test_failure_is_reported_without_raising(self):
        provider = R2StorageProvider(**R2_ENV)
        client = MagicMock()
        client.put_bucket_lifecycle_configuration.side_effect = Exception("access denied")
        provider._client = client

        assert provider.apply_lifecycle_policy() is False


class TestGitHubArtifactProvider:
    def test_file_is_staged_and_run_url_returned(self, video_file, tmp_path):
        provider = GitHubArtifactStorageProvider(
            staging_dir=str(tmp_path / "staged"),
            repo="acme/web",
            run_id="9999",
            github_output_path="",
        )

        artifact = provider.upload_file(video_file, "qa/acme_web/pr-42/abc/run.mp4", ArtifactKind.VIDEO)

        assert Path(artifact.remote_key).is_file()
        assert artifact.public_url == "https://github.com/acme/web/actions/runs/9999"
        assert artifact.provider is StorageProviderType.GITHUB_ARTIFACT

    def test_artifact_urls_are_not_embeddable(self, video_file, tmp_path):
        """Artifacts are authenticated zips, so a GIF cannot render inline from one."""
        provider = GitHubArtifactStorageProvider(
            staging_dir=str(tmp_path / "staged"), github_output_path=""
        )

        artifact = provider.upload_file(video_file, "preview.gif", ArtifactKind.GIF)

        assert artifact.is_embeddable is False

    def test_staging_dir_is_published_to_github_output(self, video_file, tmp_path):
        output_file = tmp_path / "gh_output"
        output_file.touch()
        staging = tmp_path / "staged"
        provider = GitHubArtifactStorageProvider(
            staging_dir=str(staging), github_output_path=str(output_file)
        )

        provider.upload_file(video_file, "run.mp4", ArtifactKind.VIDEO)

        assert f"{STAGING_DIR_OUTPUT_KEY}={staging}" in output_file.read_text()

    def test_is_always_available(self):
        assert GitHubArtifactStorageProvider(github_output_path="").is_available() is True


class TestFallbackChain:
    def _artifact(self, provider_type: StorageProviderType) -> UploadedArtifact:
        return UploadedArtifact(
            local_path="/tmp/run.mp4",
            remote_key="qa/run.mp4",
            public_url="https://example.com/run.mp4",
            kind=ArtifactKind.VIDEO,
            provider=provider_type,
        )

    def test_primary_is_used_when_available(self, video_file):
        primary = MagicMock()
        primary.is_available.return_value = True
        primary.provider_type = StorageProviderType.R2
        primary.upload_file.return_value = self._artifact(StorageProviderType.R2)
        fallback = MagicMock()

        chain = FallbackStorageProvider(primary, fallback)
        chain.upload_file(video_file, "qa/run.mp4", ArtifactKind.VIDEO)

        primary.upload_file.assert_called_once()
        fallback.upload_file.assert_not_called()
        assert chain.degraded is False

    def test_falls_back_when_primary_raises(self, video_file):
        """Phase 5 criterion: an upload failure must not fail the build."""
        primary = MagicMock()
        primary.is_available.return_value = True
        primary.provider_type = StorageProviderType.R2
        primary.upload_file.side_effect = RuntimeError("R2 upload failed: 503")
        fallback = MagicMock()
        fallback.provider_type = StorageProviderType.GITHUB_ARTIFACT
        fallback.upload_file.return_value = self._artifact(StorageProviderType.GITHUB_ARTIFACT)

        chain = FallbackStorageProvider(primary, fallback)
        artifact = chain.upload_file(video_file, "qa/run.mp4", ArtifactKind.VIDEO)

        fallback.upload_file.assert_called_once()
        assert artifact.provider is StorageProviderType.GITHUB_ARTIFACT
        assert chain.degraded is True

    def test_falls_back_when_primary_is_unconfigured(self, video_file):
        primary = MagicMock()
        primary.is_available.return_value = False
        primary.provider_type = StorageProviderType.R2
        fallback = MagicMock()
        fallback.provider_type = StorageProviderType.GITHUB_ARTIFACT
        fallback.upload_file.return_value = self._artifact(StorageProviderType.GITHUB_ARTIFACT)

        chain = FallbackStorageProvider(primary, fallback)
        chain.upload_file(video_file, "qa/run.mp4", ArtifactKind.VIDEO)

        primary.upload_file.assert_not_called()
        fallback.upload_file.assert_called_once()

    def test_try_upload_reports_total_failure_without_raising(self, video_file):
        primary = MagicMock()
        primary.is_available.return_value = True
        primary.provider_type = StorageProviderType.R2
        primary.upload_file.side_effect = RuntimeError("R2 down")
        fallback = MagicMock()
        fallback.provider_type = StorageProviderType.GITHUB_ARTIFACT
        fallback.upload_file.side_effect = RuntimeError("disk full")

        chain = FallbackStorageProvider(primary, fallback)
        outcome = chain.try_upload(video_file, "qa/run.mp4", ArtifactKind.VIDEO)

        assert outcome.success is False
        assert "disk full" in outcome.error_message

    def test_provider_type_reflects_the_backend_that_served_the_upload(self, video_file):
        primary = MagicMock()
        primary.is_available.return_value = True
        primary.provider_type = StorageProviderType.R2
        primary.upload_file.side_effect = RuntimeError("boom")
        fallback = MagicMock()
        fallback.provider_type = StorageProviderType.GITHUB_ARTIFACT
        fallback.upload_file.return_value = self._artifact(StorageProviderType.GITHUB_ARTIFACT)

        chain = FallbackStorageProvider(primary, fallback)
        chain.upload_file(video_file, "qa/run.mp4", ArtifactKind.VIDEO)

        assert chain.provider_type is StorageProviderType.GITHUB_ARTIFACT
