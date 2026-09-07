"""Domain models for cross-repository dependency and branch resolution."""
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ResolutionSource(str, Enum):
    """Source strategy through which the backend branch was resolved."""
    EXPLICIT_PR_BODY = "explicit_pr_body"
    AI_SEMANTIC_EXTRACTION = "ai_semantic_extraction"
    REMOTE_BRANCH_MATCH = "remote_branch_match"
    DEFAULT_FALLBACK = "default_fallback"


class AIExtractedBranch(BaseModel):
    """Structured branch dependency extracted via Gemini semantic analysis."""
    target_branch: Optional[str] = Field(None, description="Extracted backend branch name")
    target_pr_number: Optional[int] = Field(None, description="Extracted backend PR number")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    reasoning: str = Field(default="", description="Explanation of how the target branch was determined")
    is_negated_or_deprecated: bool = Field(default=False, description="Whether the branch is explicitly rejected or obsolete")


class BranchResolutionResult(BaseModel):
    """Structured result of resolving the backend branch for a frontend/mobile PR."""
    target_branch: str = Field(..., description="Resolved backend branch name or ref to checkout")
    target_repo_url: str = Field(..., description="Target backend repository URL")
    source_branch: str = Field(..., description="Incoming frontend or mobile feature branch name")
    resolution_source: ResolutionSource = Field(..., description="Strategy that successfully resolved the branch")
    clarification_needed: bool = Field(default=False, description="Whether bot clarification comment should be posted")
    clarification_message: Optional[str] = Field(default=None, description="Actionable comment text if clarification is needed")
    details: Dict[str, Any] = Field(default_factory=dict, description="Metadata and diagnostic resolution telemetry")
