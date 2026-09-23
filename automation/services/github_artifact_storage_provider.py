"""Fallback storage provider that stages media for GitHub Actions artifact upload."""
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from automation.domain.storage import (
    ArtifactKind,
    StorageProviderType,
    UploadedArtifact,
)
from automation.interfaces.storage_interface import IStorageProvider

logger = logging.getLogger("automation.storage.artifact")

DEFAULT_STAGING_DIR = "qa-artifacts"

# Name of the $GITHUB_OUTPUT key the workflow reads to find the staging directory.
STAGING_DIR_OUTPUT_KEY = "qa_artifact_dir"


class GitHubArtifactStorageProvider(IStorageProvider):
    """Stages files locally for `actions/upload-artifact` to collect.

    Python cannot upload a workflow artifact directly, so this provider does the half of
    the job it can: it copies media into a staging directory and publishes that path via
    `$GITHUB_OUTPUT`. A workflow step guarded by `if: always()` uploads the directory.

    The URL returned points at the workflow run, because an artifact is an authenticated
    zip download with no per-file address. That means media stored this way can be linked
    but never embedded inline in a comment.
    """

    def __init__(
        self,
        staging_dir: Optional[str] = None,
        repo: Optional[str] = None,
        run_id: Optional[str] = None,
        server_url: Optional[str] = None,
        github_output_path: Optional[str] = None,
    ):
        self._staging_dir = Path(staging_dir or os.getenv("QA_ARTIFACT_DIR", DEFAULT_STAGING_DIR))
        self._repo = repo or os.getenv("GITHUB_REPOSITORY", "")
        self._run_id = run_id or os.getenv("GITHUB_RUN_ID", "")
        self._server_url = (server_url or os.getenv("GITHUB_SERVER_URL", "https://github.com")).rstrip("/")
        self._github_output_path = github_output_path or os.getenv("GITHUB_OUTPUT", "")

    @property
    def provider_type(self) -> StorageProviderType:
        return StorageProviderType.GITHUB_ARTIFACT

    def is_available(self) -> bool:
        """Always true: this is the last resort and must never itself fall through."""
        return True

    @property
    def staging_dir(self) -> Path:
        return self._staging_dir

    def run_url(self) -> str:
        """URL of the workflow run whose artifacts hold the staged media."""
        if self._repo and self._run_id:
            return f"{self._server_url}/{self._repo}/actions/runs/{self._run_id}"
        return f"{self._server_url}"

    def _publish_staging_dir(self) -> None:
        """Expose the staging path to later workflow steps via $GITHUB_OUTPUT."""
        if not self._github_output_path:
            return
        try:
            with open(self._github_output_path, "a", encoding="utf-8") as f:
                f.write(f"{STAGING_DIR_OUTPUT_KEY}={self._staging_dir}\n")
        except OSError as e:
            # Losing the output only costs the upload step its input path; it must not
            # take down a pipeline that is already in its degraded path.
            logger.warning(f"Could not write staging dir to GITHUB_OUTPUT: {e}")

    def upload_file(
        self,
        local_path: str,
        remote_filename: str,
        kind: ArtifactKind,
    ) -> UploadedArtifact:
        source = Path(local_path)
        if not source.is_file():
            raise RuntimeError(f"Cannot stage missing file: {local_path}")

        # Flatten the namespaced key: artifact zips have no meaningful directory story,
        # and a deep tree just makes the download awkward to navigate.
        staged_name = Path(remote_filename).name
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        destination = self._staging_dir / staged_name

        try:
            shutil.copy2(source, destination)
        except OSError as e:
            raise RuntimeError(f"Failed to stage {source} for artifact upload: {e}") from e

        self._publish_staging_dir()
        size_bytes = destination.stat().st_size
        logger.info(f"Staged {kind.value} for artifact upload: {destination} ({size_bytes} bytes)")

        return UploadedArtifact(
            local_path=str(source),
            remote_key=str(destination),
            public_url=self.run_url(),
            kind=kind,
            content_type="application/zip",
            size_bytes=size_bytes,
            provider=StorageProviderType.GITHUB_ARTIFACT,
        )
