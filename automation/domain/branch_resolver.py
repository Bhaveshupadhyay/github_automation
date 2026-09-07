"""Domain models for cross-repository dependency and branch resolution."""
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ResolutionSource(str, Enum):
    """Source strategy through which the backend branch was resolved."""
    EXPLICIT_PR_BODY = "explicit_pr_body"
    REMOTE_BRANCH_MATCH = "remote_branch_match"
    DEFAULT_FALLBACK = "default_fallback"


class BranchResolutionResult(BaseModel):
    """Structured result of resolving the backend branch for a frontend/mobile PR."""
    target_branch: str = Field(..., description="Resolved backend branch name or ref to checkout")
    target_repo_url: str = Field(..., description="Target backend repository URL")
    source_branch: str = Field(..., description="Incoming frontend or mobile feature branch name")
    resolution_source: ResolutionSource = Field(..., description="Strategy that successfully resolved the branch")
    clarification_needed: bool = Field(default=False, description="Whether bot clarification comment should be posted")
    clarification_message: Optional[str] = Field(default=None, description="Actionable comment text if clarification is needed")
    details: Dict[str, Any] = Field(default_factory=dict, description="Metadata and diagnostic resolution telemetry")
