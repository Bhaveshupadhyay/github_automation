import json
import logging
import urllib.request
import urllib.error
from typing import Tuple, Optional, Dict, Any

from automation.domain import WorkflowEnvironment
from automation.interfaces.execution_output_classifier_interface import IExecutionOutputClassifierService
from automation.core.credentials import get_gemini_api_key, normalize_gemini_model

logger = logging.getLogger("automation.output_classifier")


def parse_json_safely(raw_text: str) -> Optional[Dict[str, Any]]:
    """Resiliently extracts and parses JSON object from LLM response text."""
    if not raw_text:
        return None
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass
    return None


class GeminiExecutionOutputClassifierService(IExecutionOutputClassifierService):
    """Concrete implementation of IExecutionOutputClassifierService utilizing Gemini REST API."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def classify_output_intent(self, output_text: str) -> Tuple[bool, str]:
        api_key = get_gemini_api_key()
        if not api_key or not output_text.strip():
            return False, ""

        try:
            api_model = normalize_gemini_model(self.config.model_name)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{api_model}:generateContent"
            
            system_instruction = (
                "You are an expert AI execution output intent classifier.\n"
                "Analyze the output produced by the coding agent ('agy') to determine if the agent successfully completed the task OR if it is actively asking the user a clarifying question.\n"
                "CRITICAL RULE: If the output contains summaries of rules, files, or markdown text referencing 'CLARIFICATION_NEEDED:', but is NOT asking a direct question to the user, respond with {\"is_clarification\": false}.\n"
                "Only if the agent is actively asking the user a question to proceed, respond with JSON: {\"is_clarification\": true, \"question\": \"<short polite clarification question>\"}."
            )
            
            # Sample up to last 4000 characters where execution summary / questions appear
            sample_text = output_text[-4000:]
            payload = {
                "system_instruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"parts": [{"text": f"Agent Execution Output:\n{sample_text}"}]}],
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

            with urllib.request.urlopen(req, timeout=10) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        raw_json = parts[0].get("text", "").strip()
                        parsed = parse_json_safely(raw_json)
                        if parsed and isinstance(parsed, dict):
                            is_clarification = bool(parsed.get("is_clarification", False))
                            question = str(parsed.get("question", "")).strip()
                            
                            if is_clarification and question:
                                logger.info(f"❓ Gemini Output Classifier detected explicit clarification question: '{question}'")
                                return True, question
        except Exception as e:
            logger.warning(f"⚠️ Exception in GeminiExecutionOutputClassifierService ({e}). Defaulting to COMPLETED task.")

        return False, ""
