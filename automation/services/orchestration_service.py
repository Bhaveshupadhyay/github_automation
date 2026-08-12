import logging
from typing import Callable, Optional
from automation.domain import WorkflowEnvironment, TaskCategory, GitPRDetails
from automation.interfaces import (
    IOrchestrationService,
    IIntentRouterService,
    ICodeDevelopmentService,
    IDeploymentService,
    INotificationService,
)

logger = logging.getLogger("automation.orchestration")

class TaskOrchestrationService(IOrchestrationService):
    """Master Workflow Orchestrator: Handles intent classification and dispatches target tasks using Constructor DI."""
    
    def __init__(
        self,
        config: WorkflowEnvironment,
        intent_router: IIntentRouterService,
        deployment_service: IDeploymentService,
        code_dev_service: ICodeDevelopmentService,
        notification_service_factory: Callable[[Optional[GitPRDetails]], INotificationService],
    ):
        self.config = config
        self.intent_router = intent_router
        self.deployment_service = deployment_service
        self.code_dev_service = code_dev_service
        self.notification_service_factory = notification_service_factory

    def run(self) -> bool:
        logger.info(f"📌 [STEP 1/3] Received Request for Repo '{self.config.target_repo}': '{self.config.user_prompt}'")

        # 1. Intent Classification
        intent = self.intent_router.classify_intent()
        logger.info(f"🎯 [STEP 1/3 Complete] Task Intent Classified as: '{intent.category.value}'")

        # 2. Dispatch Task Based on Intent Category
        if intent.category == TaskCategory.CLARIFICATION_NEEDED:
            logger.info("❓ Prompt requires user clarification. Sending notification...")
            notifier = self.notification_service_factory(None)
            notifier.send_clarification_notification(intent)
            return True

        elif intent.category == TaskCategory.DEPLOYMENT_DEVOPS:
            logger.info("🚀 Routing to Deployment & DevOps Pipeline Service...")
            deploy_result = self.deployment_service.execute_deployment(intent)
            success = deploy_result.get("success", False)
            notifier = self.notification_service_factory(None)
            notifier.send_deployment_notification(deploy_result)
            if not success:
                logger.error("❌ Deployment failed.")
                return False
            return True

        elif intent.category == TaskCategory.CODE_DEVELOPMENT:
            logger.info("🛠️ [STEP 2/3] Routing to Code Development Pipeline Service (agy Engine)...")
            self.code_dev_service.execute_pipeline()
            return True

        return True
