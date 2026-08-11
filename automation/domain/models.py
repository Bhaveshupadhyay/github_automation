import os
import re
import logging
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from automation.domain.constants import DEFAULT_GEMINI_MODEL

logger = logging.getLogger("automation.domain")

class TaskCategory(str, Enum):
    """Categories of incoming user requests."""
    CODE_DEVELOPMENT = "CODE_DEVELOPMENT"          # Requires agy code edits, testing, & Pull Request
    DEPLOYMENT_DEVOPS = "DEPLOYMENT_DEVOPS"        # Operational deployment task (Fastlane, Wrangler, Workflow)
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"  # Prompt lacks essential info needed to proceed

class TaskIntent(BaseModel):
    """Pydantic model representing structured LLM intent classification result."""
    category: TaskCategory
    confidence: float = Field(default=1.0, description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(description="Brief explanation for the intent category choice")
    target_action: Optional[str] = Field(default=None, description="Action slug (e.g. deploy_app_store, deploy_cloudflare, run_migrations)")
    clarification_question: Optional[str] = Field(default=None, description="Specific question to post if clarification is needed")

def extract_target_repo(user_prompt: str, env_target: str) -> str:
    """Extracts explicit owner/repo slug from user prompt if present. Returns empty string if no repo found."""
    if user_prompt:
        # Match owner/repo pattern e.g. bhaveshupadhyay/culture_box or owner-name/repo-name
        matches = re.findall(r"([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)", user_prompt)
        for slug in matches:
            if not slug.startswith("http") and not slug.startswith("github.com") and not slug.startswith("Original/Request"):
                logger.info(f"🎯 Extracted explicit Target Repo '{slug}' from user prompt.")
                return slug
    return env_target.strip() if env_target else ""

class WorkflowEnvironment(BaseModel):
    """Pydantic domain model representing environment configuration passed from GitHub Actions."""
    gh_token: str = Field(default_factory=lambda: os.getenv("GH_TOKEN", ""))
    slack_token: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_TOKEN"))
    slack_channel: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_CHANNEL"))
    slack_thread_ts: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_THREAD"))
    existing_branch: Optional[str] = Field(default_factory=lambda: os.getenv("EXISTING_BRANCH"))
    user_prompt: str = Field(default_factory=lambda: os.getenv("USER_PROMPT", ""))
    target_repo: str = Field(default="")
    model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", DEFAULT_GEMINI_MODEL))
    effort_val: str = Field(default_factory=lambda: os.getenv("EFFORT_VAL", "high"))
    execution_log_path: str = Field(default="../agy_execution.log")

    def __init__(self, **data):
        super().__init__(**data)
        env_target = os.getenv("TARGET_REPO", "")
        self.target_repo = extract_target_repo(self.user_prompt, env_target)

class GitPRDetails(BaseModel):
    """Pydantic domain model holding branch, commit message, and PR metadata."""
    branch_name: str
    commit_message: str
    pr_title: str
    pr_body: str
