from abc import ABC, abstractmethod

class ISummarizerService(ABC):
    """Abstract interface defining the contract for text & clarification summarization services."""
    
    @abstractmethod
    def summarize_clarification(self, verbose_text: str) -> str:
        """Summarizes verbose technical response text into a clean, polite 1-sentence clarification question."""
        pass
