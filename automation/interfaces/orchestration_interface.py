from abc import ABC, abstractmethod

class IOrchestrationService(ABC):
    """Abstract interface defining contract for master workflow orchestration."""
    
    @abstractmethod
    def run(self) -> bool:
        """Executes intent classification and dispatches task execution to appropriate service."""
        pass
