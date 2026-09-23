"""Interface for idempotent pull request comment publishing."""
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field


class PRCommentResult(BaseModel):
    """Outcome of an upsert against a pull request's comment thread."""
    comment_id: Optional[int] = Field(default=None, description="ID of the comment that now holds the report")
    comment_url: Optional[str] = Field(default=None, description="Permalink to that comment")
    created: bool = Field(default=False, description="True when a new comment was posted rather than an edit")
    duplicates_removed: int = Field(
        default=0, description="Stale marked comments deleted, which a concurrent run can leave behind"
    )
    success: bool = Field(default=False, description="Whether the comment thread now reflects this report")
    error_message: Optional[str] = Field(default=None, description="Diagnostic when publishing failed")


class IPRCommentPublisher(ABC):
    """Abstract contract for maintaining exactly one bot comment per pull request."""

    @abstractmethod
    def upsert_comment(self, repo: str, pr_number: int, body: str) -> PRCommentResult:
        """Create the bot's comment, or edit it in place if it already exists.

        Implementations must locate the prior comment by a hidden marker *and* verify
        authorship, so that a human quoting the marker is never overwritten.

        Args:
            repo: Target repository as 'owner/repo'.
            pr_number: Pull request to comment on.
            body: Full markdown body, already carrying the hidden marker.

        Returns:
            PRCommentResult describing whether the comment was created or updated.
        """
        pass

    @abstractmethod
    def find_existing_comment(self, repo: str, pr_number: int) -> Optional[dict]:
        """Return the bot's own prior comment on this PR, or None.

        Must page through the entire comment list: on a long-running pull request the
        bot's comment is frequently not on the first page, and a first-page-only lookup
        silently posts duplicates.
        """
        pass
