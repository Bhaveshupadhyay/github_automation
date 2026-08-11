from typing import Optional
from automation.domain.models import WorkflowEnvironment, GitPRDetails
from automation.interfaces.metadata_service_interface import IMetadataService
from automation.services.cleanup_service import WorkspaceCleanupService
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

    def get_metadata_service(self) -> IMetadataService:
        """Returns instance of IMetadataService interface (GeminiLLMMetadataService)."""
        return GeminiLLMMetadataService(config=self.config)

    def get_git_pr_service(self, pr_details: GitPRDetails) -> GitPRService:
        return GitPRService(config=self.config, pr_details=pr_details)

    def get_notification_service(self, pr_details: GitPRDetails) -> NotificationService:
        return NotificationService(config=self.config, pr_details=pr_details)

# Global Container Singleton
container = Container()
