import os
import json
import logging
import urllib.request
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
    """Always returns gemini-3.1-flash-lite for Python SDK / REST calls."""
    return DEFAULT_GEMINI_MODEL

class GeminiIntentRouterService(IIntentRouterService):
    """Concrete implementation of IIntentRouterService utilizing official google-genai SDK and REST fallback."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def classify_intent(self) -> TaskIntent:
        api_key = get_gemini_api_key()
        
        if api_key:
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

            # 1. Attempt official google-genai SDK call with X-goog-api-key header
            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(
                        headers={"X-goog-api-key": api_key},
                        timeout=15.0
                    )
                )

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
                    logger.info(f"🎯 Classified Task Intent via SDK ({api_model}): {intent.category.value} (Confidence: {intent.confidence})")
                    logger.info(f"💡 Reasoning: {intent.reasoning}")
                    return intent
            except Exception as e:
                logger.warning(f"⚠️ google-genai SDK call exception [{type(e).__name__}]: {e}. Trying direct REST API fallback...")

            # 2. Direct HTTP REST API Fallback with X-goog-api-key header (0.8s ultra-fast response)
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{api_model}:generateContent"
                payload = {
                    "system_instruction": {"parts": [{"text": system_instruction}]},
                    "contents": [{"parts": [{"text": prompt_content}]}],
                    "generationConfig": {"response_mime_type": "application/json"}
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-goog-api-key": api_key
                    }
                )

                with urllib.request.urlopen(req, timeout=15) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed_json = json.loads(raw_text)
                    if "category" not in parsed_json and "intent" in parsed_json:
                        parsed_json["category"] = parsed_json["intent"]
                    if "confidence" not in parsed_json:
                        parsed_json["confidence"] = 1.0
                    intent = TaskIntent(**parsed_json)
                    logger.info(f"🎯 Classified Task Intent via REST API ({api_model}): {intent.category.value} (Confidence: {intent.confidence})")
                    logger.info(f"💡 Reasoning: {intent.reasoning}")
                    return intent
            except Exception as ex:
                logger.warning(f"⚠️ Direct REST API call exception [{type(ex).__name__}]: {ex}. Defaulting to CODE_DEVELOPMENT pipeline.")
        
        # Failsafe fallback: Default to CODE_DEVELOPMENT so agy engine handles the coding task
        return TaskIntent(
            category=TaskCategory.CODE_DEVELOPMENT,
            confidence=1.0,
            reasoning="Default fallback to Code Development pipeline."
        )
