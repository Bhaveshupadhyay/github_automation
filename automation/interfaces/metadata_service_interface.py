from abc import ABC, abstractmethod
from typing import Optional
from automation.domain import GitPRDetails

class IMetadataService(ABC):
    """Abstract interface defining contract for Git & PR metadata generation services."""
    
    @abstractmethod
    def generate_metadata(self) -> GitPRDetails:
        """Generates semantic branch name, commit message, PR title, and PR description."""
        pass

    @abstractmethod
    def find_existing_thread_branch(self) -> Optional[str]:
        """Queries GitHub for existing PRs matching slack_thread_ts to reuse exact semantic branch name."""
        pass
