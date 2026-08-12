from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

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
