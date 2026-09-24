"""Unit tests for QAReportFormatter markdown rendering."""
import pytest

from automation.domain.branch_resolver import ResolutionSource
from automation.domain.qa_report import QAReport
from automation.domain.storage import ArtifactKind, StorageProviderType, UploadedArtifact
from automation.domain.test_run import TestCaseResult, TestOutcome, TestRunResult
from automation.services.github_pr_comment_publisher import COMMENT_MARKER, MAX_COMMENT_CHARS
from automation.services.qa_report_formatter import FAIL_BADGE, PASS_BADGE, QAReportFormatter


def artifact(kind: ArtifactKind, provider=StorageProviderType.R2, url="https://media.example.com/x") -> UploadedArtifact:
    return UploadedArtifact(
        local_path="/tmp/x",
        remote_key="qa/x",
        public_url=url,
        kind=kind,
        provider=provider,
    )


def passing_report(**overrides) -> QAReport:
    defaults = dict(
        repo="acme/web",
        pr_number=42,
        commit_sha="fed3210987654321",
        test_result=TestRunResult(
            overall_outcome=TestOutcome.PASSED,
            total_tests=2,
            passed=2,
            failed=0,
            duration_seconds=38.4,
        ),
        backend_branch="dev",
        resolution_source=ResolutionSource.DEFAULT_FALLBACK,
        gif=artifact(ArtifactKind.GIF, url="https://media.example.com/preview.gif"),
        video=artifact(ArtifactKind.VIDEO, url="https://media.example.com/run.mp4"),
        storage_provider=StorageProviderType.R2,
    )
    defaults.update(overrides)
    return QAReport(**defaults)


def failing_report(**overrides) -> QAReport:
    defaults = dict(
        repo="acme/web",
        pr_number=42,
        commit_sha="abc1234567890000",
        test_result=TestRunResult(
            overall_outcome=TestOutcome.FAILED,
            total_tests=2,
            passed=1,
            failed=1,
            duration_seconds=22.0,
            test_results=[
                TestCaseResult(journey_name="Log in with valid credentials", outcome=TestOutcome.PASSED),
                TestCaseResult(
                    journey_name="Rejects an incorrect password",
                    outcome=TestOutcome.FAILED,
                    failure_message="TimeoutError: locator.click: Timeout 30000ms exceeded.\nWaiting for getByRole('button', { name: 'Log in' })",
                ),
            ],
        ),
        backend_branch="feat/auth-api",
        resolution_source=ResolutionSource.EXPLICIT_PR_BODY,
        video=artifact(ArtifactKind.VIDEO, url="https://media.example.com/fail.mp4"),
        trace=artifact(ArtifactKind.TRACE, url="https://media.example.com/trace.zip"),
        storage_provider=StorageProviderType.R2,
    )
    defaults.update(overrides)
    return QAReport(**defaults)


@pytest.fixture
def formatter() -> QAReportFormatter:
    return QAReportFormatter()


class TestMarkerAndBadges:
    def test_body_always_opens_with_the_marker(self, formatter):
        """The publisher locates its prior comment by this marker."""
        assert formatter.format(passing_report()).startswith(COMMENT_MARKER)

    def test_passing_run_uses_the_green_badge(self, formatter):
        assert PASS_BADGE in formatter.format(passing_report())

    def test_failing_run_uses_the_red_badge(self, formatter):
        body = formatter.format(failing_report())

        assert FAIL_BADGE in body
        assert PASS_BADGE not in body


class TestPassingReport:
    def test_gif_is_embedded_inline(self, formatter):
        body = formatter.format(passing_report())

        assert "![QA preview](https://media.example.com/preview.gif)" in body

    def test_video_is_linked(self, formatter):
        assert "https://media.example.com/run.mp4" in formatter.format(passing_report())

    def test_backend_branch_and_resolution_source_are_shown(self, formatter):
        body = formatter.format(passing_report())

        assert "`dev`" in body
        assert "default fallback" in body

    def test_journey_counts_are_reported(self, formatter):
        assert "2 passed, 0 failed" in formatter.format(passing_report())

    def test_no_failure_section_on_success(self, formatter):
        body = formatter.format(passing_report())

        assert "What failed" not in body
        assert "To re-test" not in body


class TestFailingReport:
    def test_assertion_message_is_included(self, formatter):
        body = formatter.format(failing_report())

        assert "TimeoutError" in body
        assert "Timeout 30000ms exceeded" in body

    def test_failing_journey_is_named(self, formatter):
        assert "Rejects an incorrect password" in formatter.format(failing_report())

    def test_passing_journey_is_not_listed_as_a_failure(self, formatter):
        body = formatter.format(failing_report())
        failure_section = body.split("### What failed")[1]

        assert "Log in with valid credentials" not in failure_section

    def test_failure_video_is_linked(self, formatter):
        assert "https://media.example.com/fail.mp4" in formatter.format(failing_report())

    def test_trace_is_linked_with_viewer_instructions(self, formatter):
        body = formatter.format(failing_report())

        assert "https://media.example.com/trace.zip" in body
        assert "trace.playwright.dev" in body

    def test_retest_instructions_are_present(self, formatter):
        assert "To re-test" in formatter.format(failing_report())

    def test_missing_assertion_message_is_handled(self, formatter):
        report = failing_report(
            test_result=TestRunResult(
                overall_outcome=TestOutcome.FAILED,
                total_tests=1,
                failed=1,
                test_results=[
                    TestCaseResult(journey_name="Some journey", outcome=TestOutcome.FAILED)
                ],
            )
        )

        assert "No assertion message" in formatter.format(report)


class TestFallbackStorageRendering:
    def test_artifact_gif_is_linked_not_embedded(self, formatter):
        """An artifact URL is an authenticated zip and cannot render inline."""
        report = passing_report(
            gif=artifact(ArtifactKind.GIF, StorageProviderType.GITHUB_ARTIFACT, "https://github.com/acme/web/actions/runs/1"),
            storage_provider=StorageProviderType.GITHUB_ARTIFACT,
            storage_degraded=True,
        )

        body = formatter.format(report)

        assert "![QA preview]" not in body
        assert "download from workflow artifacts" in body

    def test_fully_degraded_storage_is_explained(self, formatter):
        report = passing_report(
            gif=artifact(ArtifactKind.GIF, StorageProviderType.GITHUB_ARTIFACT),
            video=artifact(ArtifactKind.VIDEO, StorageProviderType.GITHUB_ARTIFACT),
            storage_degraded=True,
        )

        assert "Cloud storage was unavailable" in formatter.format(report)

    def test_media_row_names_the_artifact_backend(self, formatter):
        report = passing_report(
            gif=artifact(ArtifactKind.GIF, StorageProviderType.GITHUB_ARTIFACT),
            video=artifact(ArtifactKind.VIDEO, StorageProviderType.GITHUB_ARTIFACT),
        )

        assert "| **Media** | GitHub Actions artifacts |" in formatter.format(report)

    def test_mixed_providers_are_reported_as_partial(self, formatter):
        """One upload can fall back while a later one succeeds on the primary."""
        report = passing_report(
            video=artifact(ArtifactKind.VIDEO, StorageProviderType.R2),
            gif=artifact(ArtifactKind.GIF, StorageProviderType.GITHUB_ARTIFACT),
            storage_degraded=True,
        )

        body = formatter.format(report)

        assert "Some media could not be uploaded" in body
        assert "Cloud storage was unavailable" not in body, "Must not claim all media fell back"
        assert "| **Media** | GitHub Actions artifacts |" not in body

    def test_report_with_no_media_says_so(self, formatter):
        report = passing_report(video=None, gif=None, storage_degraded=True)

        assert "No media could be published" in formatter.format(report)

    def test_successful_r2_run_shows_no_storage_warning(self, formatter):
        body = formatter.format(passing_report())

        assert "⚠️" not in body


class TestJourneyNameEscaping:
    """Journey names are model-authored, so they are data and must not render as markup."""

    def _report_named(self, name: str) -> QAReport:
        return failing_report(
            test_result=TestRunResult(
                overall_outcome=TestOutcome.FAILED,
                total_tests=1,
                failed=1,
                test_results=[TestCaseResult(journey_name=name, outcome=TestOutcome.FAILED)],
            )
        )

    def test_markdown_image_syntax_is_neutralised(self, formatter):
        body = formatter.format(self._report_named("![x](https://evil.example/track.png)"))

        assert "![x](https://evil.example/track.png)" not in body
        assert "evil.example" in body, "The text is still shown, just not rendered as an image"

    def test_link_syntax_is_neutralised(self, formatter):
        body = formatter.format(self._report_named("[click me](https://evil.example)"))

        assert "[click me](https://evil.example)" not in body

    def test_html_is_escaped(self, formatter):
        body = formatter.format(self._report_named("<img src=x onerror=alert(1)>"))

        assert "<img" not in body
        assert "&lt;img" in body

    def test_ordinary_name_stays_readable(self, formatter):
        body = formatter.format(self._report_named("Rejects an incorrect password"))

        assert "**Rejects an incorrect password**" in body

    def test_overlong_name_is_truncated(self, formatter):
        body = formatter.format(self._report_named("N" * 5000))

        assert "…" in body
        assert "N" * 5000 not in body


class TestSafetyLimits:
    def test_code_fence_in_failure_message_cannot_escape_the_block(self, formatter):
        """Runner output is untrusted text and must not inject markdown."""
        report = failing_report(
            test_result=TestRunResult(
                overall_outcome=TestOutcome.FAILED,
                total_tests=1,
                failed=1,
                test_results=[
                    TestCaseResult(
                        journey_name="Injected",
                        outcome=TestOutcome.FAILED,
                        failure_message="```\n# Injected heading\n```",
                    )
                ],
            )
        )

        body = formatter.format(report)
        failure_section = body.split("### What failed")[1]

        assert "```\n# Injected heading" not in failure_section
        assert "'''" in failure_section

    def test_long_failure_message_is_truncated(self, formatter):
        report = failing_report(
            test_result=TestRunResult(
                overall_outcome=TestOutcome.FAILED,
                total_tests=1,
                failed=1,
                test_results=[
                    TestCaseResult(
                        journey_name="Verbose",
                        outcome=TestOutcome.FAILED,
                        failure_message="E" * 50000,
                    )
                ],
            )
        )

        body = formatter.format(report)

        assert "(truncated)" in body
        assert len(body) < MAX_COMMENT_CHARS

    def test_many_failures_stay_within_the_comment_limit(self, formatter):
        cases = [
            TestCaseResult(
                journey_name=f"Journey {i}",
                outcome=TestOutcome.FAILED,
                failure_message="E" * 5000,
            )
            for i in range(40)
        ]
        report = failing_report(
            test_result=TestRunResult(
                overall_outcome=TestOutcome.FAILED, total_tests=40, failed=40, test_results=cases
            )
        )

        body = formatter.format(report)

        assert len(body) <= MAX_COMMENT_CHARS
        assert "more failing journey" in body


class TestPlanFallbackNotice:
    def test_degraded_plan_says_the_change_was_not_tested(self, formatter):
        body = formatter.format(passing_report(plan_fallback=True, plan_degraded=True))

        assert "This run did not test your change" in body
        assert "Re-run the workflow job" in body

    def test_no_ui_changes_fallback_is_explained(self, formatter):
        body = formatter.format(passing_report(plan_fallback=True))

        assert "No user-facing changes were found" in body
        assert "did not test your change" not in body

    def test_generated_plan_has_no_notice(self, formatter):
        body = formatter.format(passing_report())

        assert "smoke test" not in body

    def test_slack_text_flags_a_degraded_plan(self, formatter):
        text = formatter.format_slack_text(passing_report(plan_fallback=True, plan_degraded=True))

        assert "No test plan could be generated" in text


class TestSlackText:
    def test_passing_summary_is_concise(self, formatter):
        text = formatter.format_slack_text(passing_report())

        assert "✅" in text
        assert "acme/web" in text
        assert "PR #42" in text

    def test_failing_summary_includes_the_first_failure(self, formatter):
        text = formatter.format_slack_text(failing_report())

        assert "❌" in text
        assert "TimeoutError" in text

    def test_slack_summary_is_short_enough_for_a_thread_reply(self, formatter):
        assert len(formatter.format_slack_text(failing_report())) < 1000
