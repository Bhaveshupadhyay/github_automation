"""Domain model for the QA result published to a pull request."""
from typing import Optional

from pydantic import BaseModel, Field

from automation.domain.branch_resolver import ResolutionSource
from automation.domain.storage import StorageProviderType, UploadedArtifact
from automation.domain.test_run import TestOutcome, TestRunResult


class QAReport(BaseModel):
    """Everything the comment formatter and Slack notifier need to render a result.

    Assembled by the publish CLI from the outputs of phases 2 through 4, so the
    formatter stays a pure function of this model and is trivially snapshot-testable.
    """
    repo: str = Field(..., description="Target repository as 'owner/repo'")
    pr_number: int = Field(..., ge=1, description="Pull request number the report is published to")
    commit_sha: str = Field(..., description="Head commit the tests ran against")

    test_result: TestRunResult = Field(..., description="Aggregated outcome from the test runner")

    backend_branch: Optional[str] = Field(default=None, description="Backend branch paired with this PR")
    resolution_source: Optional[ResolutionSource] = Field(
        default=None, description="How the backend branch was chosen"
    )

    video: Optional[UploadedArtifact] = Field(default=None, description="Compressed MP4 of the run")
    gif: Optional[UploadedArtifact] = Field(default=None, description="Preview GIF embedded in the comment")
    trace: Optional[UploadedArtifact] = Field(default=None, description="Playwright trace archive, on failure")

    run_url: Optional[str] = Field(default=None, description="URL of the workflow run that produced this report")
    storage_provider: Optional[StorageProviderType] = Field(
        default=None, description="Backend that ultimately stored the media"
    )
    storage_degraded: bool = Field(
        default=False, description="True when the primary backend failed and artifacts were used instead"
    )

    @property
    def passed(self) -> bool:
        return self.test_result.overall_outcome is TestOutcome.PASSED

    @property
    def short_sha(self) -> str:
        return self.commit_sha[:7] if self.commit_sha else "unknown"

    @property
    def failed_cases(self) -> list:
        """Failing journeys, which drive the diagnostic section of the comment."""
        return [c for c in self.test_result.test_results if c.outcome is TestOutcome.FAILED]
