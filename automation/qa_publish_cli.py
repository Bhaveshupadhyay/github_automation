"""CLI entry point for publishing QA results to a pull request.

Usage:
    qa-publish --repo owner/name --pr 42 --sha abc123 --test-result result.json \
        [--media-result media.json] [--branch-result branch.json] [--trace trace.zip]

Uploads the recorded media, updates a single idempotent PR comment in place, and posts
a non-blocking Slack thread reply. Media upload failures degrade to GitHub Actions
artifacts rather than failing the build.

    qa-publish --apply-lifecycle

One-time bucket setup: installs the rule that expires QA media after 30 days.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qa-publish")


def _load_json(path: Optional[str], label: str) -> Optional[dict]:
    """Read one of the upstream phase outputs, tolerating absence."""
    if not path:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning(f"{label} file not found: {path}")
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Could not parse {label} file {path}: {e}")
        return None


def _default_head_sha() -> str:
    """Resolve the PR's head commit, preferring the event payload over GITHUB_SHA.

    On a `pull_request` event GITHUB_SHA is the synthetic merge commit of
    `refs/pull/N/merge`, which appears nowhere in the PR's commit list. Reporting it
    would show reviewers a SHA they cannot find, and would key stored media by a commit
    that is recreated whenever the base branch moves.
    """
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if event_path and Path(event_path).is_file():
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
            head_sha = (event.get("pull_request") or {}).get("head", {}).get("sha")
            if head_sha:
                return head_sha
        except (json.JSONDecodeError, OSError, AttributeError) as e:
            logger.debug(f"Could not read head SHA from the event payload: {e}")
    return os.getenv("GITHUB_SHA", "")


def _default_pr_number() -> Optional[int]:
    """Resolve the PR number from the event payload when not passed explicitly."""
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    if event_path and Path(event_path).is_file():
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
            number = event.get("number") or (event.get("pull_request") or {}).get("number")
            if number:
                return int(number)
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
            logger.debug(f"Could not read the PR number from the event payload: {e}")
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish QA test results and media to a pull request.",
        prog="qa-publish",
    )
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""), help="Target repository as 'owner/repo'.")
    parser.add_argument("--pr", type=int, default=None, help="Pull request number.")
    parser.add_argument(
        "--sha",
        default=None,
        help="Head commit SHA the tests ran against. Defaults to the PR head from the event payload.",
    )
    parser.add_argument("--test-result", default=None, help="Path to the TestRunResult JSON from the test runner.")
    parser.add_argument("--media-result", default=None, help="Path to the MediaProcessingResult JSON from qa-media.")
    parser.add_argument("--branch-result", default=None, help="Path to the BranchResolutionResult JSON.")
    parser.add_argument("--trace", default=None, help="Path to a Playwright trace archive to publish on failure.")
    parser.add_argument("--run-url", default=None, help="Workflow run URL to link from the comment.")
    parser.add_argument(
        "--no-slack", action="store_true", help="Skip the Slack notification even when a channel is configured."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Render the comment to stdout without uploading or posting."
    )
    parser.add_argument(
        "--apply-lifecycle",
        action="store_true",
        help="One-time setup: install the 30-day expiry rule on the storage bucket, then exit.",
    )
    return parser


def _apply_lifecycle() -> int:
    from automation.core import get_r2_storage_provider

    provider = get_r2_storage_provider()
    if not provider.is_available():
        logger.error("R2 is not configured. Set R2_* environment variables before applying the lifecycle policy.")
        return 1
    return 0 if provider.apply_lifecycle_policy() else 1


def main() -> int:
    args = _build_parser().parse_args()

    if args.apply_lifecycle:
        return _apply_lifecycle()

    from automation.core import (
        get_notification_service,
        get_pr_comment_publisher,
        get_qa_report_formatter,
        get_storage_provider,
    )
    from automation.domain.branch_resolver import BranchResolutionResult
    from automation.domain.media_processing import MediaProcessingResult
    from automation.domain.qa_report import QAReport
    from automation.domain.storage import ArtifactKind
    from automation.domain.test_run import TestOutcome, TestRunResult
    from automation.services.r2_storage_provider import build_remote_key

    if not args.repo or "/" not in args.repo:
        logger.error("A target repository is required, as --repo owner/name.")
        return 1

    if not args.pr:
        args.pr = _default_pr_number()
    if not args.pr:
        logger.error("A pull request number is required, as --pr N.")
        return 1

    if not args.sha:
        args.sha = _default_head_sha()
    if not args.sha:
        # Without a real SHA every run would share one object key, so a reviewer would
        # see the previous run's cached media beside the current run's text.
        logger.error(
            "A head commit SHA is required, as --sha. It could not be resolved from "
            "GITHUB_EVENT_PATH or GITHUB_SHA."
        )
        return 1

    # 1. Load the upstream phase outputs.
    test_raw = _load_json(args.test_result, "Test result")
    if test_raw is None:
        logger.error("A test result is required. Pass --test-result pointing at the runner's JSON output.")
        return 1

    try:
        test_result = TestRunResult.model_validate(test_raw)
    except ValidationError as e:
        logger.error(f"Test result JSON does not match the expected schema: {e}")
        return 1

    media_raw = _load_json(args.media_result, "Media result")
    media_result = None
    if media_raw is not None:
        try:
            media_result = MediaProcessingResult.model_validate(media_raw)
        except ValidationError as e:
            logger.warning(f"Media result JSON is malformed, continuing without media: {e}")

    branch_raw = _load_json(args.branch_result, "Branch resolution")
    branch_result = None
    if branch_raw is not None:
        try:
            branch_result = BranchResolutionResult.model_validate(branch_raw)
        except ValidationError as e:
            logger.warning(f"Branch resolution JSON is malformed, continuing without it: {e}")

    # 2. Publish the media, degrading to workflow artifacts on any failure.
    storage = get_storage_provider()
    uploads: dict[ArtifactKind, object] = {}

    def publish(local_path: Optional[str], kind: ArtifactKind) -> None:
        if not local_path or not Path(local_path).is_file():
            return
        key = build_remote_key(args.repo, args.pr, args.sha, local_path)
        outcome = storage.try_upload(local_path, key, kind)
        if outcome.success:
            uploads[kind] = outcome.artifact
        else:
            logger.warning(f"Could not publish {kind.value}: {outcome.error_message}")

    if not args.dry_run:
        if media_result and media_result.compressed_video:
            publish(media_result.compressed_video.output_path, ArtifactKind.VIDEO)
        if media_result and media_result.preview_gif:
            publish(media_result.preview_gif.output_path, ArtifactKind.GIF)

        trace_path = args.trace or test_result.trace_archive_path
        if trace_path and test_result.overall_outcome is TestOutcome.FAILED:
            publish(trace_path, ArtifactKind.TRACE)

    # 3. Assemble the report.
    report = QAReport(
        repo=args.repo,
        pr_number=args.pr,
        commit_sha=args.sha,
        test_result=test_result,
        backend_branch=branch_result.target_branch if branch_result else None,
        resolution_source=branch_result.resolution_source if branch_result else None,
        video=uploads.get(ArtifactKind.VIDEO),
        gif=uploads.get(ArtifactKind.GIF),
        trace=uploads.get(ArtifactKind.TRACE),
        run_url=args.run_url,
        storage_provider=storage.provider_type if uploads else None,
        storage_degraded=storage.degraded,
    )

    formatter = get_qa_report_formatter()
    body = formatter.format(report)

    if args.dry_run:
        print(body)
        return 0

    # 4. Update the single PR comment in place.
    publisher = get_pr_comment_publisher()
    comment = publisher.upsert_comment(args.repo, args.pr, body)

    if not comment.success:
        logger.error(f"Failed to publish the PR comment: {comment.error_message}")
        return 1

    action = "Created" if comment.created else "Updated"
    logger.info(f"{action} QA comment: {comment.comment_url}")
    if comment.duplicates_removed:
        logger.info(f"Removed {comment.duplicates_removed} duplicate QA comment(s) left by a concurrent run.")

    # 5. Notify Slack without blocking.
    if not args.no_slack and os.getenv("SLACK_CHANNEL"):
        try:
            get_notification_service().send_qa_result_notification(
                formatter.format_slack_text(report),
                pr_url=comment.comment_url,
            )
        except Exception as e:
            logger.warning(f"Slack notification skipped: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
