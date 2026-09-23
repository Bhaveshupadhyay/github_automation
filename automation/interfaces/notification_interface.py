from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from automation.domain import TaskIntent

class INotificationService(ABC):
    """Abstract interface defining domain contract for notification services."""
    
    @abstractmethod
    def send_pr_notification(self, pr_url: str) -> None:
        """Sends Pull Request completion notification."""
        pass

    @abstractmethod
    def send_clarification_notification(self, intent: TaskIntent) -> None:
        """Sends interactive clarification request notification."""
        pass

    @abstractmethod
    def send_deployment_notification(self, deploy_result: Dict[str, Any]) -> None:
        """Sends deployment task status notification."""
        pass

    @abstractmethod
    def send_qa_result_notification(self, text: str, pr_url: Optional[str] = None) -> None:
        """Sends a QA preview result as a non-blocking Slack thread reply.

        Accepts pre-rendered text so the notification layer stays decoupled from the
        QA report model and its formatting rules.
        """
        pass
