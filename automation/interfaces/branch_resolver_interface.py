"""Interface for cross-repository dependency and branch resolution."""
from abc import ABC, abstractmethod
from typing import Optional
from automation.domain.branch_resolver import BranchResolutionResult


class IBranchResolver(ABC):
    """Abstract interface for resolving cross-repository branch dependencies."""

    @abstractmethod
    def resolve_branch(
        self,
        pr_body: Optional[str],
        source_branch: str,
        backend_repo_url: str,
        default_branch: str = "dev",
        new_backend_routes_detected: bool = False,
    ) -> BranchResolutionResult:
        """Determines which backend repository branch must be paired with an incoming PR.

        Args:
            pr_body: Description body of the incoming PR (for explicit linkage declarations).
            source_branch: Incoming frontend or mobile feature branch name.
            backend_repo_url: URL or remote path to the backend repository.
            default_branch: Target fallback branch when no linkage is specified (default 'dev').
            new_backend_routes_detected: Whether frontend diff introduces unmerged backend API routes.

        Returns:
            BranchResolutionResult containing the resolved target branch, resolution source,
            and any clarification flags.
        """
        pass

    @abstractmethod
    def check_remote_branch_exists(self, backend_repo_url: str, branch_name: str) -> bool:
        """Probes the remote backend repository to check if a specific branch exists.

        Args:
            backend_repo_url: URL or remote path to the backend repository.
            branch_name: Branch name to check on the remote repository.

        Returns:
            True if the branch exists on the remote, False otherwise.
        """
        pass
