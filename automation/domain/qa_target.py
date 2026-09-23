"""Domain models for the repositories the central QA pipeline serves.

The pipeline runs in this repository, when a user asks the Slack bot to QA-test a pull
request. Which repositories it serves, and how each pairs with its backend, is recorded
here rather than in the repositories under test.
"""
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class QAPlatform(str, Enum):
    """Which pipeline a repository's pull requests are routed to."""
    WEB = "web"
    MOBILE = "mobile"


class QATarget(BaseModel):
    """One repository whose pull requests are previewed, and the backend it runs against."""
    model_config = ConfigDict(extra="forbid")

    platform: QAPlatform = Field(..., description="Pipeline that previews this repository's pull requests")
    backend_repo: str = Field(..., pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", description="Paired backend as owner/name")
    backend_default_branch: str = Field("main", description="Backend branch used when the PR declares none and no head matches")
    slack_channel: Optional[str] = Field(
        None, description="Slack channel for results of a manual re-run. A Slack request replies in its own thread."
    )
    dev_api_url: Optional[str] = Field(
        None, description="Deployed dev API base URL, used when the requester chooses `dev` instead of a backend"
    )
    db_strategy: str = Field("auto", pattern=r"^(auto|cloud_dev|ephemeral_container)$")
    startup_timeout_seconds: int = Field(420, gt=0)
    python_version: str = Field("3.12")
    # Web only.
    frontend_url: str = Field("http://localhost:3000", description="Address the frontend serves on inside the runner")
    node_version: str = Field("20")
    # Mobile only. 10.0.2.2 is the runner's localhost as seen from inside the emulator.
    api_base_url: str = Field("http://10.0.2.2:8000")
    android_api_level: int = Field(34)
    java_version: str = Field("17")


class QATargetRegistry(BaseModel):
    """Every repository the pipeline serves, keyed by owner/name."""
    model_config = ConfigDict(extra="forbid")

    targets: Dict[str, QATarget] = Field(default_factory=dict)

    def find(self, repository: str) -> Optional[QATarget]:
        """Look up a repository. GitHub treats owner and name case-insensitively."""
        wanted = repository.lower()
        for name, target in self.targets.items():
            if name.lower() == wanted:
                return target
        return None


class PullRequestContext(BaseModel):
    """A pull request resolved against the registry, ready for the pipeline to run."""
    repository: str = Field(..., description="Repository under test, as owner/name")
    number: int = Field(..., gt=0)
    head_sha: str = Field(..., description="Commit the preview runs against")
    head_ref: str = Field(..., description="Branch name, used to find a matching backend branch")
    base_ref: str = Field(..., description="Branch the diff is taken against")
    body: str = Field("", description="PR description, which may declare the backend branch")
    target: QATarget


class BackendMode(str, Enum):
    """What the frontend under test talks to."""
    AUTO = "auto"                  # Resolve a backend branch from the PR (manual re-runs)
    PULL_REQUEST = "pull_request"  # A backend PR's branch, run in the runner
    BRANCH = "branch"              # A backend repository's main branch, run in the runner
    DEV = "dev"                    # The deployed dev APIs; no backend is started


class BackendChoice(BaseModel):
    """The backend a QA run pairs the frontend PR with, as the requester chose it."""
    mode: BackendMode
    repository: Optional[str] = Field(None, description="Backend repository to check out, as owner/name")
    ref: Optional[str] = Field(None, description="Commit or branch to check out")
    label: str = Field("", description="What the report shows, e.g. `owner/api#3 (feat/x)`")
    api_base_url: Optional[str] = Field(None, description="API address for the frontend in dev mode")


class PullRequestSkipped(Exception):
    """The pull request must not be previewed. The message says why, for the run log."""
