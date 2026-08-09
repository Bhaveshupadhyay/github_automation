from pydantic import BaseModel, Field
from typing import Dict

class CodeChangeRequest(BaseModel):
    """Value object representing a user's prompt request."""
    user_prompt: str = Field(description="User modification prompt")
    repository: str = Field(description="Target GitHub repository")

class CodeModification(BaseModel):
    """Entity representing generated file modifications."""
    files: Dict[str, str] = Field(default_factory=dict, description="File relative path to content map")
    commit_message: str = Field(default="", description="Git commit summary")

class PullRequestResult(BaseModel):
    """Value object containing details of an executed PR."""
    pr_number: int = Field(description="GitHub Pull Request number")
    pr_url: str = Field(description="HTML URL to the created PR")
    branch_name: str = Field(description="Name of the pushed git feature branch")
    is_merged: bool = Field(default=True, description="Whether the PR was auto-merged")
