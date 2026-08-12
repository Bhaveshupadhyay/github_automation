import os
import re
import logging
from typing import Optional
from pydantic import BaseModel, Field
from automation.domain.constants import DEFAULT_GEMINI_MODEL

logger = logging.getLogger("automation.domain.environment")

def extract_target_repo(user_prompt: str, env_target: str) -> str:
    """Extracts explicit owner/repo slug from user prompt if present. Returns empty string if no repo found."""
    if user_prompt:
        # Strip full URLs to prevent URL fragments from misparsing
        cleaned_prompt = re.sub(r"https?://[^\s]+", "", user_prompt)
        cleaned_prompt = re.sub(r"github\.com/[^\s]+", "", cleaned_prompt)
        
        matches = re.findall(r"\b([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\b", cleaned_prompt)
        for slug in matches:
            if not slug.lower().startswith("original"):
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
