"""Cloudflare R2 (S3-compatible) storage provider for QA test media."""
import logging
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from automation.domain.storage import (
    CONTENT_TYPES,
    DEFAULT_CONTENT_TYPE,
    ArtifactKind,
    StorageProviderType,
    UploadedArtifact,
)
from automation.interfaces.storage_interface import IStorageProvider

logger = logging.getLogger("automation.storage.r2")

# Media is deleted by a bucket lifecycle rule after this many days. Videos are large
# and a PR's preview stops being interesting once the PR is merged.
LIFECYCLE_EXPIRY_DAYS = 30

# Every object this provider writes lives under one prefix, so the lifecycle rule can
# target QA media without touching anything else in a shared bucket.
OBJECT_PREFIX = "qa"

LIFECYCLE_RULE_ID = "qa-media-expiry"


class R2StorageProvider(IStorageProvider):
    """Publishes media to Cloudflare R2 over the S3-compatible API.

    Links are built from a configured public base URL (an r2.dev subdomain or a custom
    domain) rather than presigned URLs: a presigned R2 URL expires after at most seven
    days, which would silently break the video link in every older pull request comment.
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        bucket: Optional[str] = None,
        public_base_url: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        self._account_id = account_id or os.getenv("R2_ACCOUNT_ID", "")
        self._access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID", "")
        self._secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY", "")
        self._bucket = bucket or os.getenv("R2_BUCKET", "")
        self._public_base_url = (public_base_url or os.getenv("R2_PUBLIC_BASE_URL", "")).rstrip("/")
        self._endpoint_url = endpoint_url or os.getenv("R2_ENDPOINT_URL", "")
        self._client: Optional[Any] = None

    @property
    def provider_type(self) -> StorageProviderType:
        return StorageProviderType.R2

    @property
    def endpoint_url(self) -> str:
        """S3 endpoint for this account, unless one was configured explicitly."""
        if self._endpoint_url:
            return self._endpoint_url
        return f"https://{self._account_id}.r2.cloudflarestorage.com"

    def is_available(self) -> bool:
        """True when every credential and the public base URL are present.

        The public base URL is required, not optional: without it an upload would
        succeed but produce a URL nobody can open.
        """
        required = [
            ("R2_ACCESS_KEY_ID", self._access_key_id),
            ("R2_SECRET_ACCESS_KEY", self._secret_access_key),
            ("R2_BUCKET", self._bucket),
            ("R2_PUBLIC_BASE_URL", self._public_base_url),
        ]
        # An explicitly configured endpoint makes the account ID redundant.
        if not self._endpoint_url:
            required.append(("R2_ACCOUNT_ID", self._account_id))

        missing = [name for name, value in required if not value]
        if missing:
            logger.info(f"R2 storage unavailable; missing configuration: {', '.join(missing)}")
            return False
        return True

    def _get_client(self) -> Any:
        """Build the boto3 S3 client lazily.

        boto3 is an optional dependency (the `qa` extra), so importing it at module
        scope would break every other CLI in this package on a minimal install.
        """
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config
        except ImportError as e:
            raise RuntimeError(
                "boto3 is required for R2 uploads. Install it with: pip install 'github-automation-ai[qa]'"
            ) from e

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self._access_key_id,
            aws_secret_access_key=self._secret_access_key,
            # R2 ignores the region but the SDK requires one.
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
            ),
        )
        return self._client

    @staticmethod
    def resolve_content_type(filename: str) -> str:
        """Pick the MIME type a file must be served with, by extension."""
        return CONTENT_TYPES.get(Path(filename).suffix.lower(), DEFAULT_CONTENT_TYPE)

    def build_public_url(self, remote_key: str) -> str:
        """Join the configured public base to an object key, escaping path segments."""
        safe_key = "/".join(quote(segment, safe="") for segment in remote_key.split("/"))
        return f"{self._public_base_url}/{safe_key}"

    def upload_file(
        self,
        local_path: str,
        remote_filename: str,
        kind: ArtifactKind,
    ) -> UploadedArtifact:
        source = Path(local_path)
        if not source.is_file():
            raise RuntimeError(f"Cannot upload missing file: {local_path}")

        remote_key = remote_filename.lstrip("/")
        content_type = self.resolve_content_type(remote_filename)
        size_bytes = source.stat().st_size

        try:
            self._get_client().upload_file(
                Filename=str(source),
                Bucket=self._bucket,
                Key=remote_key,
                ExtraArgs={"ContentType": content_type},
            )
        except Exception as e:
            raise RuntimeError(f"R2 upload failed for {remote_key}: {e}") from e

        public_url = self.build_public_url(remote_key)
        logger.info(f"Uploaded {kind.value} to R2: {public_url} ({size_bytes} bytes)")

        return UploadedArtifact(
            local_path=str(source),
            remote_key=remote_key,
            public_url=public_url,
            kind=kind,
            content_type=content_type,
            size_bytes=size_bytes,
            provider=StorageProviderType.R2,
        )

    def _existing_lifecycle_rules(self, client: Any) -> list[dict]:
        """Read the bucket's current lifecycle rules, treating 'none set' as empty."""
        try:
            return client.get_bucket_lifecycle_configuration(Bucket=self._bucket).get("Rules", [])
        except Exception as e:
            # A bucket with no configuration raises NoSuchLifecycleConfiguration, which
            # is the expected state on first run rather than an error.
            response = getattr(e, "response", None)
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code == "NoSuchLifecycleConfiguration" or "NoSuchLifecycleConfiguration" in str(e):
                return []
            raise

    def apply_lifecycle_policy(self, expiry_days: int = LIFECYCLE_EXPIRY_DAYS) -> bool:
        """Install the rule that expires QA media after `expiry_days`.

        PutBucketLifecycleConfiguration replaces a bucket's *entire* configuration, so
        this reads the existing rules and merges rather than writing the QA rule alone.
        Writing it alone would silently delete every unrelated lifecycle rule on a
        shared bucket.

        Idempotent: re-applying replaces only the rule carrying this ID. Needs bucket
        admin permission, so it is a one-time operator step rather than something a
        per-PR pipeline run should attempt.
        """
        try:
            client = self._get_client()
            preserved = [r for r in self._existing_lifecycle_rules(client) if r.get("ID") != LIFECYCLE_RULE_ID]
            preserved.append(
                {
                    "ID": LIFECYCLE_RULE_ID,
                    "Status": "Enabled",
                    "Filter": {"Prefix": f"{OBJECT_PREFIX}/"},
                    "Expiration": {"Days": expiry_days},
                }
            )
            client.put_bucket_lifecycle_configuration(
                Bucket=self._bucket,
                LifecycleConfiguration={"Rules": preserved},
            )
            logger.info(
                f"Applied lifecycle rule '{LIFECYCLE_RULE_ID}': objects under "
                f"'{OBJECT_PREFIX}/' expire after {expiry_days} days "
                f"({len(preserved) - 1} unrelated rule(s) preserved)."
            )
            return True
        except Exception as e:
            logger.error(f"Failed to apply R2 lifecycle policy: {e}")
            return False


def build_remote_key(repo: str, pr_number: int, commit_sha: str, filename: str) -> str:
    """Namespace an object by repository, pull request and commit.

    The commit SHA in the path is load-bearing. GitHub proxies and caches images by URL,
    so reusing one key across pushes would leave reviewers looking at a cached GIF of the
    previous run while the comment text describes the current one.
    """
    owner_repo = repo.replace("/", "_") if repo else "unknown"
    short_sha = (commit_sha or "unknown")[:12]
    safe_name = Path(filename).name
    return f"{OBJECT_PREFIX}/{owner_repo}/pr-{pr_number}/{short_sha}/{safe_name}"
