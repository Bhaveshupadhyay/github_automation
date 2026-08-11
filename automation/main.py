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
        logger.error(f"❌ Invalid Environment Configuration: {e}")
        sys.exit(1)

    # 1. Classify Task Intent via LLM Router Service
    router = container.get_intent_router_service()
    intent = router.classify_intent()

    # Route A: Clarification Needed
    if intent.category == TaskCategory.CLARIFICATION_NEEDED:
        logger.info(f"❓ Task requires user clarification: {intent.clarification_question}")
        notifier = container.get_notification_service()
        notifier.send_clarification_notification(intent)
        return

    # Route B: Operational Deployment Task (Fastlane, Wrangler, Workflow)
    elif intent.category == TaskCategory.DEPLOYMENT_DEVOPS:
        logger.info(f"🚀 Routing to Operational Deployment Engine (Action: '{intent.target_action}')")
        deployer = container.get_deployment_service()
        deploy_result = deployer.execute_deployment(intent)
        notifier = container.get_notification_service()
        notifier.send_deployment_notification(deploy_result)
        return

    # Route C: Code Development Task (Graphify AST + agy Engine + Git Branch & PR)
    elif intent.category == TaskCategory.CODE_DEVELOPMENT:
        logger.info("🛠️ Routing to Code Development Engine (Graphify AST + agy Engine)...")

        # Clean up workspace unwanted files
        cleanup_service = container.get_cleanup_service()
        cleanup_service.cleanup_unwanted_files()

        # Resolve IMetadataService interface via DI container
        metadata_service = container.get_metadata_service()
        pr_details = metadata_service.generate_metadata()

        # Handle Git & PR creation
        git_service = container.get_git_pr_service(pr_details)
        if not git_service.has_changes():
            logger.info("ℹ️ No file changes were produced by the agent.")
            return

        git_service.create_and_push_branch()
        pr_url = git_service.create_pull_request()

        # Notify Slack if PR was created
        if pr_url:
            notifier = container.get_notification_service(pr_details)
            notifier.send_slack_notification(pr_url)

if __name__ == "__main__":
    main()
