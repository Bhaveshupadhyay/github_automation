"""Interface for resolving the pull request a central QA run was dispatched for."""
from abc import ABC, abstractmethod

from automation.domain.qa_target import PullRequestContext, QAPlatform


class IPullRequestContextService(ABC):
    """Turns a repository and PR number into everything the QA pipeline needs to run."""

    @abstractmethod
    def resolve(self, repository: str, pr_number: int, platform: QAPlatform) -> PullRequestContext:
        """Fetch the pull request and pair it with its registered target.

        Raises PullRequestSkipped when the PR must not be previewed: the repository is
        not registered for this platform, the PR is closed, or it comes from a fork.
        """
        pass
