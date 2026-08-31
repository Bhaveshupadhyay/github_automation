from abc import ABC, abstractmethod
from typing import Optional
from automation.domain.telemetry import PipelineStage


class ITelemetryService(ABC):
    """Abstract interface defining the contract for real-time progress telemetry services."""

    @abstractmethod
    def initialize_card(self, is_update_run: bool = False, existing_branch: Optional[str] = None) -> Optional[str]:
        """Creates the initial live telemetry status card in Slack and returns the message timestamp (ts)."""
        pass

    @abstractmethod
    def update_stage(self, stage: PipelineStage, detail: Optional[str] = None, force: bool = False) -> None:
        """Updates the current pipeline stage and refreshes the live status card in Slack."""
        pass

    @abstractmethod
    def stream_activity(self, activity: str) -> None:
        """Streams real-time sub-activity (e.g. active file edit or tool invocation) with debounced updates."""
        pass

    @abstractmethod
    def complete(self, pr_url: Optional[str] = None, branch_name: Optional[str] = None) -> None:
        """Marks the pipeline execution as successfully completed and links the Pull Request."""
        pass

    @abstractmethod
    def fail(self, error_message: str) -> None:
        """Marks the pipeline execution as failed with the specified error message."""
        pass

    @abstractmethod
    def request_clarification(self, question: str) -> None:
        """Updates the telemetry card indicating that the agent requires user clarification."""
        pass
