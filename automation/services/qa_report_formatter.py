"""Renders a QAReport into the markdown body of the pull request comment."""
import logging

from automation.domain.branch_resolver import ResolutionSource
from automation.domain.qa_report import QAReport
from automation.domain.storage import StorageProviderType
from automation.services.github_pr_comment_publisher import COMMENT_MARKER, MAX_COMMENT_CHARS

logger = logging.getLogger("automation.qa_report")

PASS_BADGE = "https://img.shields.io/badge/QA_Preview-passed-brightgreen"
FAIL_BADGE = "https://img.shields.io/badge/QA_Preview-failed-red"

# Per-failure diagnostic cap. A Playwright timeout message can run to hundreds of
# lines, and several of them would blow the comment size limit on their own.
MAX_FAILURE_MESSAGE_CHARS = 1200

# How many failing journeys to detail before summarising the remainder.
MAX_DETAILED_FAILURES = 5

# Journey names come from the model and have no enforced length.
MAX_JOURNEY_NAME_CHARS = 200

RESOLUTION_LABELS = {
    ResolutionSource.EXPLICIT_PR_BODY: "declared in the PR description",
    ResolutionSource.AI_SEMANTIC_EXTRACTION: "inferred from the PR description",
    ResolutionSource.REMOTE_BRANCH_MATCH: "matched by branch name",
    ResolutionSource.DEFAULT_FALLBACK: "default fallback",
}


class QAReportFormatter:
    """Pure transformation from a QAReport to comment markdown.

    Holds no I/O so the exact rendered output can be asserted in tests.
    """

    def __init__(self, marker: str = COMMENT_MARKER, max_chars: int = MAX_COMMENT_CHARS):
        self._marker = marker
        self._max_chars = max_chars

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """Render model-authored text as data rather than markup.

        Journey names are written by Gemini from a diff, so they are untrusted input to
        this comment. Left raw, a name containing link, image or HTML syntax would alter
        what the published comment renders.
        """
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for char in "\\`*_[]()#|":
            escaped = escaped.replace(char, f"\\{char}")
        if len(escaped) > MAX_JOURNEY_NAME_CHARS:
            escaped = escaped[:MAX_JOURNEY_NAME_CHARS] + "…"
        return escaped

    @staticmethod
    def _sanitize_for_code_block(text: str) -> str:
        """Make runner output safe to place inside a fenced block.

        A failure message containing its own fence would otherwise break out of the
        block and let arbitrary markdown render in the comment.
        """
        cleaned = text.replace("```", "'''").strip()
        if len(cleaned) > MAX_FAILURE_MESSAGE_CHARS:
            cleaned = cleaned[:MAX_FAILURE_MESSAGE_CHARS] + "\n… (truncated)"
        return cleaned

    def _format_media_section(self, report: QAReport) -> list[str]:
        """Render the GIF embed and video link, honouring provider capability."""
        lines: list[str] = []

        if report.gif:
            if report.gif.is_embeddable:
                lines.append(f"![QA preview]({report.gif.public_url})")
                lines.append("")
            else:
                lines.append(f"🎞️ Preview GIF: [download from workflow artifacts]({report.gif.public_url})")

        if report.video:
            label = "Watch the full recording" if report.video.is_embeddable else "Download the full recording"
            lines.append(f"▶️ [{label}]({report.video.public_url})")

        # Describe what actually happened to this report's media. One upload can fall
        # back while a later one succeeds, so "all" and "some" are different claims.
        if report.all_media_degraded:
            lines.append("")
            lines.append(
                "> ⚠️ Cloud storage was unavailable, so media was saved as workflow artifacts. "
                "Artifacts are authenticated zip downloads, so the preview cannot render inline here."
            )
        elif report.any_media_degraded:
            lines.append("")
            lines.append(
                "> ⚠️ Some media could not be uploaded to cloud storage and was saved as workflow "
                "artifacts instead. Those files are authenticated zip downloads."
            )
        elif report.storage_degraded and not report.artifacts:
            lines.append("")
            lines.append("> ⚠️ No media could be published for this run.")

        return lines

    def _format_failures(self, report: QAReport) -> list[str]:
        """Render per-journey diagnostics for a failed run."""
        failures = report.failed_cases
        if not failures:
            return []

        lines = ["", "### What failed", ""]

        for case in failures[:MAX_DETAILED_FAILURES]:
            lines.append(f"**{self._escape_markdown(case.journey_name)}**")
            lines.append("")
            if case.failure_message:
                lines.append("```")
                lines.append(self._sanitize_for_code_block(case.failure_message))
                lines.append("```")
            else:
                lines.append("_No assertion message was captured for this journey._")
            lines.append("")

        remaining = len(failures) - MAX_DETAILED_FAILURES
        if remaining > 0:
            lines.append(f"_…and {remaining} more failing journey(s). See the full run for details._")
            lines.append("")

        return lines

    def _format_context(self, report: QAReport) -> list[str]:
        """Render the run's provenance: commit, backend branch, counts."""
        lines = ["", "| | |", "| :--- | :--- |"]
        lines.append(f"| **Commit** | `{report.short_sha}` |")

        if report.backend_branch:
            source = RESOLUTION_LABELS.get(report.resolution_source, "resolved")
            lines.append(f"| **Backend branch** | `{report.backend_branch}` ({source}) |")

        result = report.test_result
        lines.append(
            f"| **Journeys** | {result.passed} passed, {result.failed} failed"
            + (f", {result.skipped} skipped" if result.skipped else "")
            + " |"
        )

        if result.duration_seconds:
            lines.append(f"| **Duration** | {result.duration_seconds:.1f}s |")

        # Name the backends that actually served this report's media, so the row cannot
        # contradict the warning above it.
        if report.all_media_degraded:
            lines.append("| **Media** | GitHub Actions artifacts |")
        elif report.any_media_degraded:
            lines.append("| **Media** | Cloud storage, with some files in workflow artifacts |")

        return lines

    def format(self, report: QAReport) -> str:
        """Build the full comment body, marker included."""
        passed = report.passed
        lines: list[str] = [self._marker]

        badge = PASS_BADGE if passed else FAIL_BADGE
        alt = "QA preview passed" if passed else "QA preview failed"
        lines.append(f"![{alt}]({badge})")
        lines.append("")

        if passed:
            lines.append("**All generated journeys passed.** Here is the run against your branch:")
        else:
            lines.append("**Some journeys failed.** The recording below shows where it broke.")
        lines.append("")

        lines.extend(self._format_media_section(report))
        lines.extend(self._format_context(report))

        if not passed:
            lines.extend(self._format_failures(report))

            if report.trace:
                lines.append(
                    f"🔍 [Download the Playwright trace]({report.trace.public_url}) — "
                    "open it at [trace.playwright.dev](https://trace.playwright.dev) to step through the run."
                )
                lines.append("")

            lines.append("**To re-test:** push a new commit, or re-run the workflow job from the Actions tab.")
            lines.append("")

        if report.run_url:
            lines.append(f"<sub>[Workflow run]({report.run_url}) · This comment updates in place on every push.</sub>")
        else:
            lines.append("<sub>This comment updates in place on every push.</sub>")

        body = "\n".join(lines)

        if len(body) > self._max_chars:
            suffix = "\n\n_(report truncated)_"
            body = body[: self._max_chars - len(suffix)] + suffix

        return body

    def format_slack_text(self, report: QAReport) -> str:
        """Condense the same report into a Slack thread reply."""
        icon = "✅" if report.passed else "❌"
        status = "passed" if report.passed else "failed"
        result = report.test_result

        parts = [
            f"{icon} *QA Preview {status}* for `{report.repo}` PR #{report.pr_number}",
            f"• Commit: `{report.short_sha}`",
            f"• Journeys: {result.passed} passed, {result.failed} failed",
        ]
        if report.backend_branch:
            parts.append(f"• Backend branch: `{report.backend_branch}`")
        if report.video:
            parts.append(f"• <{report.video.public_url}|Watch the recording>")
        if not report.passed and report.failed_cases:
            first = report.failed_cases[0]
            if first.failure_message:
                # Strip Slack's own link delimiters: this text is model-adjacent and
                # `<url|label>` in a message body would render as a link.
                snippet = first.failure_message.strip().splitlines()[0][:200]
                snippet = snippet.replace("<", "").replace(">", "").replace("`", "")
                parts.append(f"• First failure: `{snippet}`")

        return "\n".join(parts)
