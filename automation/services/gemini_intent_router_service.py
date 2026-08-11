import os
import json
import logging
import urllib.request
from google import genai
from google.genai import types

from automation.domain.constants import DEFAULT_GEMINI_MODEL
from automation.domain.models import WorkflowEnvironment, TaskIntent, TaskCategory
from automation.interfaces.intent_router_interface import IIntentRouterService
from automation.utils.credentials import get_gemini_api_key, normalize_gemini_model

logger = logging.getLogger("automation.intent_router")

class GeminiIntentRouterService(IIntentRouterService):
    """Concrete implementation of IIntentRouterService utilizing official google-genai SDK and REST fallback."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def classify_intent(self) -> TaskIntent:
        # Rule: If target repository is completely missing from environment and prompt, ask the user!
        if not self.config.target_repo:
            logger.info("❓ Target repository is missing. Asking user for target repository clarification...")
            return TaskIntent(
                category=TaskCategory.CLARIFICATION_NEEDED,
                confidence=1.0,
                reasoning="Target repository (owner/repo) is missing from environment and prompt.",
                clarification_question="Which target repository (owner/repo) would you like me to work on? (e.g., bhaveshupadhyay/culture_box)"
            )

        api_key = get_gemini_api_key()
        
        if api_key:
            system_instruction = (
                "You are an expert AI DevOps & Software Engineering Dispatcher.\n"
                "Your task: Analyze the user's prompt and target repository context to classify intent into one of 3 categories:\n"
                "1. CODE_DEVELOPMENT: User wants specific code changes, refactoring, new features, bug fixes, or test additions. Requires agy coding agent loop.\n"
                "2. DEPLOYMENT_DEVOPS: User wants operational deployment, release to App Store/Play Store, Cloudflare worker deployment, database migration, or server actions. No code editing required.\n"
                "3. CLARIFICATION_NEEDED: User asks to modify or set a property (e.g. 'change app name', 'update title', 'change logo', 'change redis to', 'deploy app') WITHOUT providing the specific target value or environment.\n\n"
                "CRITICAL FORMATTING RULE: If classified as CLARIFICATION_NEEDED, clarification_question MUST be a short, direct, 1-sentence question asking specifically for the missing value (e.g. 'What would you like to change the app name to?'). Do NOT output file lists or technical explanations."
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
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text", "").strip()
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
