import os
from typing import Optional
from pydantic import BaseModel, Field

class WorkflowEnvironment(BaseModel):
    """Pydantic domain model representing environment configuration passed from GitHub Actions."""
    gh_token: str = Field(default_factory=lambda: os.getenv("GH_TOKEN", ""))
    slack_token: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_TOKEN"))
    slack_channel: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_CHANNEL"))
    slack_thread_ts: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_THREAD"))
    existing_branch: Optional[str] = Field(default_factory=lambda: os.getenv("EXISTING_BRANCH"))
    target_repo: str = Field(default_factory=lambda: os.getenv("TARGET_REPO", ""))
    user_prompt: str = Field(default_factory=lambda: os.getenv("USER_PROMPT", ""))
    model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"))
    effort_val: str = Field(default_factory=lambda: os.getenv("EFFORT_VAL", "high"))
    execution_log_path: str = Field(default="../agy_execution.log")

class GitPRDetails(BaseModel):
    """Pydantic domain model holding branch, commit message, and PR metadata."""
    branch_name: str
    commit_message: str
    pr_title: str
    pr_body: str
