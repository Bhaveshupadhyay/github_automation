from pydantic import BaseModel

class GitPRDetails(BaseModel):
    """Pydantic domain model holding branch, commit message, and PR metadata."""
    branch_name: str
    commit_message: str
    pr_title: str
    pr_body: str
