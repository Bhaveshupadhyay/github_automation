"""Interfaces package containing abstract contracts for all automation services."""
from automation.interfaces.code_development_interface import ICodeDevelopmentService
from automation.interfaces.intent_router_interface import IIntentRouterService
from automation.interfaces.metadata_service_interface import IMetadataService
from automation.interfaces.summarizer_interface import ISummarizerService
from automation.interfaces.orchestration_interface import IOrchestrationService
from automation.interfaces.deployment_interface import IDeploymentService
from automation.interfaces.notification_interface import INotificationService
from automation.interfaces.slack_history_interface import ISlackHistoryService
from automation.interfaces.git_pr_interface import IGitPRService

__all__ = [
    "ICodeDevelopmentService",
    "IIntentRouterService",
    "IMetadataService",
    "ISummarizerService",
    "IOrchestrationService",
    "IDeploymentService",
    "INotificationService",
    "ISlackHistoryService",
    "IGitPRService",
]
