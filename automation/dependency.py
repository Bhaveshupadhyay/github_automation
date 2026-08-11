from typing import Optional
from automation.domain.models import WorkflowEnvironment, GitPRDetails
from automation.interfaces.metadata_service_interface import IMetadataService
from automation.interfaces.intent_router_interface import IIntentRouterService
from automation.services.cleanup_service import WorkspaceCleanupService
from automation.services.gemini_intent_router_service import GeminiIntentRouterService
from automation.services.deployment_service import DeploymentService
from automation.services.gemini_metadata_service import GeminiLLMMetadataService
from automation.services.git_pr_service import GitPRService
from automation.services.notification_service import NotificationService

class Container:
    """Dependency Injection Container managing application service lifetimes and wiring."""
    
    def __init__(self):
        self._config: Optional[WorkflowEnvironment] = None

    @property
    def config(self) -> WorkflowEnvironment:
        if self._config is None:
            self._config = WorkflowEnvironment()
        return self._config

    def get_cleanup_service(self) -> WorkspaceCleanupService:
        return WorkspaceCleanupService()

    def get_intent_router_service(self) -> IIntentRouterService:
        """Returns concrete instance implementing IIntentRouterService (GeminiIntentRouterService)."""
        return GeminiIntentRouterService(config=self.config)

    def get_deployment_service(self) -> DeploymentService:
        return DeploymentService(config=self.config)

    def get_metadata_service(self) -> IMetadataService:
        """Returns instance of IMetadataService interface (GeminiLLMMetadataService)."""
        return GeminiLLMMetadataService(config=self.config)

    def get_git_pr_service(self, pr_details: GitPRDetails) -> GitPRService:
        return GitPRService(config=self.config, pr_details=pr_details)

    def get_notification_service(self, pr_details: Optional[GitPRDetails] = None) -> NotificationService:
        return NotificationService(config=self.config, pr_details=pr_details)

# Global Container Singleton
container = Container()
