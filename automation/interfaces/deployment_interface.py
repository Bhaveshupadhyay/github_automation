from abc import ABC, abstractmethod
from typing import Dict, Any
from automation.domain import TaskIntent

class IDeploymentService(ABC):
    """Abstract interface defining contract for Deployment & DevOps services."""
    
    @abstractmethod
    def execute_deployment(self, intent: TaskIntent) -> Dict[str, Any]:
        """Executes operational deployment task based on classified intent."""
        pass
