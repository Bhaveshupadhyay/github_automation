from abc import ABC, abstractmethod
from typing import Optional, List
from automation.domain import SlackMessage

class ISlackHistoryService(ABC):
    """Abstract interface defining contract for Slack thread history services."""
    
    @abstractmethod
    def fetch_thread_messages(self, limit: Optional[int] = None) -> List[SlackMessage]:
        """Fetches typed SlackMessage models from Slack API."""
        pass

    @abstractmethod
    def fetch_first_message_text(self) -> Optional[str]:
        """Returns root (Turn 1) message text of the thread."""
        pass

    @abstractmethod
    def fetch_thread_history(self) -> Optional[str]:
        """Fetches all messages in thread formatted as User/Assistant dialogue."""
        pass
