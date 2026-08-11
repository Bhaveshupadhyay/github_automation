from abc import ABC, abstractmethod

class ICodeDevelopmentService(ABC):
    """Abstract interface defining contract for Code Development Pipeline services."""
    
    @abstractmethod
    def execute_pipeline(self) -> None:
        """Executes full Code Development Pipeline: Graphify AST -> agy Engine -> Gemini PR Manager -> Git Push & PR."""
        pass
