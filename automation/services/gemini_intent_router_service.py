import os
import logging
from google import genai
from google.genai import types

from automation.domain.models import WorkflowEnvironment, TaskIntent, TaskCategory
from automation.interfaces.intent_router_interface import IIntentRouterService

logger = logging.getLogger("automation.intent_router")

class GeminiIntentRouterService(IIntentRouterService):
    """Concrete implementation of IIntentRouterService utilizing official google-genai SDK."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def classify_intent(self) -> TaskIntent:
        api_key = os.getenv("AGY_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("ANTIGRAVITY_API_KEY", "").strip()
        
        if api_key:
            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=15.0)
                )
                
                system_instruction = (
                    "You are an expert AI DevOps & Software Engineering Dispatcher.\n"
                    "Your task: Analyze the user's prompt and target repository context to classify intent into one of 3 categories:\n"
                    "1. CODE_DEVELOPMENT: User wants code changes, refactoring, new features, bug fixes, or test additions. Requires agy coding agent loop.\n"
                    "2. DEPLOYMENT_DEVOPS: User wants operational deployment, release to App Store/Play Store, Cloudflare worker deployment, database migration, or server actions. No code editing required.\n"
                    "3. CLARIFICATION_NEEDED: User prompt lacks essential parameters (e.g. 'change the app name' without specifying the new name, or 'deploy app' when target environment is completely missing).\n\n"
                    "Provide high confidence score, concise reasoning, target_action if deployment, and clarification_question if missing details."
                )

                prompt_content = f"Target Repository: {self.config.target_repo}\nUser Prompt: {self.config.user_prompt}"

                response = client.models.generate_content(
                    model=self.config.model_name,
                    contents=prompt_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=TaskIntent
                    )
                )

                if response.parsed and isinstance(response.parsed, TaskIntent):
                    intent: TaskIntent = response.parsed
                    logger.info(f"🎯 Classified Task Intent: {intent.category.value} (Confidence: {intent.confidence})")
                    logger.info(f"💡 Reasoning: {intent.reasoning}")
                    return intent
            except Exception as e:
                logger.warning(f"⚠️ Intent classification call exception: {e}. Defaulting to clarification request.")

        # Failsafe fallback: Fail closed to CLARIFICATION_NEEDED if API key or SDK call fails
        return TaskIntent(
            category=TaskCategory.CLARIFICATION_NEEDED,
            confidence=1.0,
            reasoning="Intent classification service is temporarily unavailable.",
            clarification_question="Intent classification service is temporarily unavailable. Could you please re-phrase or retry your request?"
        )
