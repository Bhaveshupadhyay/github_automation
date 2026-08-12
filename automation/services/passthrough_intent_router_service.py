import logging
from automation.domain import WorkflowEnvironment, TaskIntent, TaskCategory
from automation.interfaces.intent_router_interface import IIntentRouterService

logger = logging.getLogger("automation.intent_router")


class PassThroughIntentRouterService(IIntentRouterService):
    """
    Fast pass-through intent router for workflow tasks pre-screened by Cloudflare Worker.
    Avoids redundant Gemini API calls inside GitHub Actions execution pipeline.
    """
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def classify_intent(self) -> TaskIntent:
        # Failsafe rule: If target repository is completely missing, ask user for clarification
        if not self.config.target_repo:
            logger.info("❓ Target repository is missing. Asking user for target repository clarification...")
            return TaskIntent(
                category=TaskCategory.CLARIFICATION_NEEDED,
                confidence=1.0,
                reasoning="Target repository (owner/repo) is missing from environment and prompt.",
                clarification_question="Which target repository (owner/repo) would you like me to work on? (e.g., bhaveshupadhyay/culture_box)"
            )

        logger.info("⚡ Prompt pre-screened by Cloudflare Worker. Bypassing duplicate Gemini API intent check.")
        return TaskIntent(
            category=TaskCategory.CODE_DEVELOPMENT,
            confidence=1.0,
            reasoning="Pre-screened by Cloudflare Worker fast-path. Proceeding directly to Code Development pipeline."
        )
