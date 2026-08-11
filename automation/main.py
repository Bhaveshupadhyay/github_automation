import sys
import logging
from automation.dependency import container
from automation.domain.models import TaskCategory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("automation.main")

def main():
    try:
        config = container.config
    except Exception as e:
        logger.error(f"Invalid Environment Configuration: {e}")
        sys.exit(1)

    logger.info(f"Received Request for Repo '{config.target_repo}': '{config.user_prompt}'")

    # 1. Classify Task Intent via LLM Intent Router Service
    intent = container.get_intent_router_service().classify_intent()

    # Route A: Clarification Needed
    if intent.category == TaskCategory.CLARIFICATION_NEEDED:
        logger.info(f"Task requires user clarification: {intent.clarification_question}")
        container.get_notification_service().send_clarification_notification(intent)

    # Route B: Operational Deployment Task (Fastlane, Wrangler, Workflow)
    elif intent.category == TaskCategory.DEPLOYMENT_DEVOPS:
        logger.info(f"Routing to Operational Deployment Engine (Action: '{intent.target_action}')")
        deploy_result = container.get_deployment_service().execute_deployment(intent)
        container.get_notification_service().send_deployment_notification(deploy_result)

    # Route C: Code Development Task (Graphify AST + agy Engine + Git Branch & PR)
    elif intent.category == TaskCategory.CODE_DEVELOPMENT:
        logger.info("Routing to Code Development Pipeline Service...")
        container.get_code_development_service().execute_pipeline()

if __name__ == "__main__":
    main()
