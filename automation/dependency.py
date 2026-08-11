import os
from typing import Optional

from automation.domain.models import WorkflowEnvironment, GitPRDetails
from automation.interfaces.intent_router_interface import IIntentRouterService
from automation.interfaces.metadata_service_interface import IMetadataService
from automation.interfaces.code_development_interface import ICodeDevelopmentService

from automation.services.gemini_intent_router_service import GeminiIntentRouterService
from automation.services.gemini_metadata_service import GeminiLLMMetadataService
from automation.services.code_development_service import CodeDevelopmentService
from automation.services.deployment_service import DeploymentService
from automation.services.notification_service import NotificationService
from automation.services.cleanup_service import WorkspaceCleanupService
from automation.services.git_pr_service import GitPRService
from automation.services.slack_history_service import SlackHistoryService

class Container:
    """Dependency Injection Container managing service lifecycles."""
    
    def __init__(self):
        self._config: Optional[WorkflowEnvironment] = None
        self._intent_router_service: Optional[IIntentRouterService] = None
        self._metadata_service: Optional[IMetadataService] = None
        self._code_dev_service: Optional[ICodeDevelopmentService] = None
        self._deployment_service: Optional[DeploymentService] = None
        self._cleanup_service: Optional[WorkspaceCleanupService] = None
        self._slack_history_service: Optional[SlackHistoryService] = None

    @property
    def config(self) -> WorkflowEnvironment:
        if self._config is None:
            self._config = WorkflowEnvironment()
        return self._config

    def get_slack_history_service(self) -> SlackHistoryService:
        if self._slack_history_service is None:
            self._slack_history_service = SlackHistoryService(self.config)
        return self._slack_history_service

    def get_intent_router_service(self) -> IIntentRouterService:
        if self._intent_router_service is None:
            self._intent_router_service = GeminiIntentRouterService(self.config)
        return self._intent_router_service

    def get_metadata_service(self) -> IMetadataService:
        if self._metadata_service is None:
            self._metadata_service = GeminiLLMMetadataService(self.config)
        return self._metadata_service

    def get_code_development_service(self) -> ICodeDevelopmentService:
        if self._code_dev_service is None:
            self._code_dev_service = CodeDevelopmentService(self)
        return self._code_dev_service

    def get_deployment_service(self) -> DeploymentService:
        if self._deployment_service is None:
            self._deployment_service = DeploymentService(self.config)
        return self._deployment_service

    def get_cleanup_service(self) -> WorkspaceCleanupService:
        if self._cleanup_service is None:
            self._cleanup_service = WorkspaceCleanupService()
        return self._cleanup_service

    def get_git_pr_service(self, pr_details: GitPRDetails) -> GitPRService:
        return GitPRService(self.config, pr_details)

    def get_notification_service(self, pr_details: Optional[GitPRDetails] = None) -> NotificationService:
        return NotificationService(self.config, pr_details)

# Global Container instance singleton
container = Container()
