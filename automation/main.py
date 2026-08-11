import sys
import logging
from automation.dependency import container
from automation.domain.models import TaskCategory, WorkflowEnvironment

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("automation.main")

def main():
    """Master Entry Point: Intent Router + Dispatcher"""
    config = container.config
    logger.info(f"📌 [STEP 1/3] Received Request for Repo '{config.target_repo}': '{config.user_prompt}'")
    
    # 1. Intent Classification
    intent_router = container.get_intent_router_service()
    intent = intent_router.classify_intent()
    logger.info(f"🎯 [STEP 1/3 Complete] Task Intent Classified as: '{intent.category.value}'")
    
    # 2. Dispatch Task Based on Intent Category
    if intent.category == TaskCategory.CLARIFICATION_NEEDED:
        logger.info("❓ Prompt requires user clarification. Sending notification...")
        notifier = container.get_notification_service()
        notifier.send_clarification_notification(intent)
        return

    elif intent.category == TaskCategory.DEPLOYMENT_DEVOPS:
        logger.info("🚀 Routing to Deployment & DevOps Pipeline Service...")
        deployment_service = container.get_deployment_service()
        success = deployment_service.execute_deployment(intent.target_action or "deploy")
        if not success:
            logger.error("❌ Deployment failed.")
            sys.exit(1)
        return

    elif intent.category == TaskCategory.CODE_DEVELOPMENT:
        logger.info("🛠️ [STEP 2/3] Routing to Code Development Pipeline Service (agy Engine)...")
        code_dev_service = container.get_code_development_service()
        code_dev_service.execute_pipeline()

if __name__ == "__main__":
    main()
