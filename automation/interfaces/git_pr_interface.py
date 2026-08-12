from abc import ABC, abstractmethod
from typing import Optional

class IGitPRService(ABC):
    """Abstract interface defining contract for Git & PR release services."""
    
    @abstractmethod
    def has_changes(self) -> bool:
        """Checks if uncommitted git changes exist in workspace."""
        pass

    @abstractmethod
    def create_and_push_branch(self) -> None:
        """Creates branch and pushes local modifications."""
        pass

    @abstractmethod
    def create_pull_request(self) -> Optional[str]:
        """Creates GitHub Pull Request using gh CLI."""
        pass
