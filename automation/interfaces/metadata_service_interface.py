from abc import ABC, abstractmethod
from automation.domain.models import GitPRDetails

class IMetadataService(ABC):
    """Abstract interface defining contract for Git & PR metadata generation services."""
    
    @abstractmethod
    def generate_metadata(self) -> GitPRDetails:
        """Generates semantic branch name, commit message, PR title, and PR description."""
        pass
