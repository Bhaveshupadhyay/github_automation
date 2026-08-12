"""Functional Dependency Injection Factories matching hiphopboombox-backend core/dependency.py pattern."""
from typing import Optional
from functools import lru_cache

from automation.domain import WorkflowEnvironment, GitPRDetails
from automation.interfaces import (
    IIntentRouterService,
    IMetadataService,
    ICodeDevelopmentService,
    ISummarizerService,
    IOrchestrationService,
    IDeploymentService,
    INotificationService,
    ISlackHistoryService,
    IGitPRService,
)

from automation.services.gemini_intent_router_service import GeminiIntentRouterService
from automation.services.gemini_metadata_service import GeminiLLMMetadataService
from automation.services.gemini_summarizer_service import GeminiLLMSummarizerService
from automation.services.code_development_service import CodeDevelopmentService
from automation.services.deployment_service import DeploymentService
from automation.services.notification_service import NotificationService
from automation.services.cleanup_service import WorkspaceCleanupService
from automation.services.git_pr_service import GitPRService
from automation.services.slack_history_service import SlackHistoryService
from automation.services.orchestration_service import TaskOrchestrationService


@lru_cache(maxsize=1)
def get_config() -> WorkflowEnvironment:
    """Returns singleton WorkflowEnvironment config instance."""
    return WorkflowEnvironment()


def get_cleanup_service() -> WorkspaceCleanupService:
    return WorkspaceCleanupService()


def get_slack_history_service(config: Optional[WorkflowEnvironment] = None) -> ISlackHistoryService:
    cfg = config or get_config()
    return SlackHistoryService(cfg)


def get_intent_router_service(config: Optional[WorkflowEnvironment] = None) -> IIntentRouterService:
    cfg = config or get_config()
    return GeminiIntentRouterService(cfg)


def get_metadata_service(config: Optional[WorkflowEnvironment] = None) -> IMetadataService:
    cfg = config or get_config()
    return GeminiLLMMetadataService(cfg)


def get_summarizer_service(config: Optional[WorkflowEnvironment] = None) -> ISummarizerService:
    cfg = config or get_config()
    return GeminiLLMSummarizerService(cfg)


def get_deployment_service(config: Optional[WorkflowEnvironment] = None) -> IDeploymentService:
    cfg = config or get_config()
    return DeploymentService(cfg)


def get_git_pr_service(pr_details: GitPRDetails, config: Optional[WorkflowEnvironment] = None) -> IGitPRService:
    cfg = config or get_config()
    return GitPRService(cfg, pr_details)


def get_notification_service(pr_details: Optional[GitPRDetails] = None, config: Optional[WorkflowEnvironment] = None) -> INotificationService:
    cfg = config or get_config()
    return NotificationService(cfg, pr_details)


def get_code_development_service(config: Optional[WorkflowEnvironment] = None) -> ICodeDevelopmentService:
    cfg = config or get_config()
    return CodeDevelopmentService(
        config=cfg,
        cleanup_service=get_cleanup_service(),
        slack_history_service=get_slack_history_service(cfg),
        metadata_service=get_metadata_service(cfg),
        summarizer_service=get_summarizer_service(cfg),
        git_pr_service_factory=get_git_pr_service,
        notification_service_factory=get_notification_service,
    )


def get_orchestration_service(config: Optional[WorkflowEnvironment] = None) -> IOrchestrationService:
    cfg = config or get_config()
    return TaskOrchestrationService(
        config=cfg,
        intent_router=get_intent_router_service(cfg),
        deployment_service=get_deployment_service(cfg),
        code_dev_service=get_code_development_service(cfg),
        notification_service_factory=get_notification_service,
    )
