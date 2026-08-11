import os
import json
import logging
from google import genai
from google.genai import types

from automation.domain.constants import DEFAULT_GEMINI_MODEL
from automation.domain.models import WorkflowEnvironment, TaskIntent, TaskCategory
from automation.interfaces.intent_router_interface import IIntentRouterService

logger = logging.getLogger("automation.intent_router")

def get_gemini_api_key() -> str:
    """Scans environment variables and local config for Gemini API key."""
    env_key = os.getenv("AGY_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("ANTIGRAVITY_API_KEY", "").strip()
    if env_key:
        logger.info(f"🔑 Gemini API Key detected from environment (Length: {len(env_key)} chars).")
        return env_key
    
    creds_path = os.path.expanduser("~/.gemini/oauth_creds.json")
    if os.path.exists(creds_path):
        try:
            with open(creds_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "api_key" in data and data["api_key"]:
                    key = data["api_key"]
                    logger.info(f"🔑 Gemini API Key detected from ~/.gemini/oauth_creds.json (Length: {len(key)} chars).")
                    return key
        except Exception:
            pass
            
    logger.info("ℹ️ No Gemini API Key detected in environment or local config files.")
    return ""

def normalize_gemini_model(model_name: str) -> str:
    """Normalizes agy CLI internal model strings (e.g. gemini-3.5-flash-lite) to valid Gemini API models."""
    if not model_name:
        return DEFAULT_GEMINI_MODEL
    model_lower = model_name.lower()
    if "pro" in model_lower:
        return "gemini-2.5-pro"
    elif "flash" in model_lower or "lite" in model_lower:
        return DEFAULT_GEMINI_MODEL
    return DEFAULT_GEMINI_MODEL

class GeminiIntentRouterService(IIntentRouterService):
    """Concrete implementation of IIntentRouterService utilizing official google-genai SDK."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def classify_intent(self) -> TaskIntent:
        api_key = get_gemini_api_key()
        
        if api_key:
            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=30.0)
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
                api_model = normalize_gemini_model(self.config.model_name)

                response = client.models.generate_content(
                    model=api_model,
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
                logger.warning(f"⚠️ Intent Router API exception: {e}. Defaulting to CODE_DEVELOPMENT pipeline.")
        
        # Failsafe fallback: Default to CODE_DEVELOPMENT so agy engine handles the coding task
        return TaskIntent(
            category=TaskCategory.CODE_DEVELOPMENT,
            confidence=1.0,
            reasoning="Default fallback to Code Development pipeline."
        )
