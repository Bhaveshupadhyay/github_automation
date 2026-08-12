from abc import ABC, abstractmethod
from typing import Tuple


class IExecutionOutputClassifierService(ABC):
    """Abstract interface for classifying AI engine execution output intent."""

    @abstractmethod
    def classify_output_intent(self, output_text: str) -> Tuple[bool, str]:
        """
        Classifies whether the engine execution output contains an active user clarification question.
        Returns Tuple[is_clarification: bool, question: str].
        """
        pass
