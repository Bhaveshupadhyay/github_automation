import os
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from automation.domain.constants import DEFAULT_GEMINI_MODEL

class TaskCategory(str, Enum):
    """Categories of incoming user requests."""
    CODE_DEVELOPMENT = "CODE_DEVELOPMENT"          # Requires agy code edits, testing, & Pull Request
    DEPLOYMENT_DEVOPS = "DEPLOYMENT_DEVOPS"        # Operational deployment task (Fastlane, Wrangler, Workflow)
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"  # Prompt lacks essential info needed to proceed

class TaskIntent(BaseModel):
    """Pydantic model representing structured LLM intent classification result."""
    category: TaskCategory
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(description="Brief explanation for the intent category choice")
    target_action: Optional[str] = Field(default=None, description="Action slug (e.g. deploy_app_store, deploy_cloudflare, run_migrations)")
    clarification_question: Optional[str] = Field(default=None, description="Specific question to post if clarification is needed")

class WorkflowEnvironment(BaseModel):
    """Pydantic domain model representing environment configuration passed from GitHub Actions."""
    gh_token: str = Field(default_factory=lambda: os.getenv("GH_TOKEN", ""))
    slack_token: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_TOKEN"))
    slack_channel: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_CHANNEL"))
    slack_thread_ts: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_THREAD"))
    existing_branch: Optional[str] = Field(default_factory=lambda: os.getenv("EXISTING_BRANCH"))
    target_repo: str = Field(default_factory=lambda: os.getenv("TARGET_REPO", ""))
    user_prompt: str = Field(default_factory=lambda: os.getenv("USER_PROMPT", ""))
    model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", DEFAULT_GEMINI_MODEL))
    effort_val: str = Field(default_factory=lambda: os.getenv("EFFORT_VAL", "high"))
    execution_log_path: str = Field(default="../agy_execution.log")

class GitPRDetails(BaseModel):
    """Pydantic domain model holding branch, commit message, and PR metadata."""
    branch_name: str
    commit_message: str
    pr_title: str
    pr_body: str
