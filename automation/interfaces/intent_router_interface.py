from abc import ABC, abstractmethod
from automation.domain.models import TaskIntent

class IIntentRouterService(ABC):
    """Abstract interface for Intent Router services."""
    
    @abstractmethod
    def classify_intent(self) -> TaskIntent:
        """Classifies incoming user prompt into CODE_DEVELOPMENT, DEPLOYMENT_DEVOPS, or CLARIFICATION_NEEDED."""
        pass
