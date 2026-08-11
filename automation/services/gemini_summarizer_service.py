import json
import logging
import urllib.request
from typing import Optional

from automation.domain.models import WorkflowEnvironment
from automation.interfaces.summarizer_interface import ISummarizerService
from automation.utils.credentials import get_gemini_api_key, normalize_gemini_model

logger = logging.getLogger("automation.summarizer")

class GeminiLLMSummarizerService(ISummarizerService):
    """Concrete implementation of ISummarizerService utilizing ultra-fast Gemini REST API."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def summarize_clarification(self, verbose_text: str) -> str:
        if not verbose_text:
            return "Could you please specify the details for your request?"

        api_key = get_gemini_api_key()
        if not api_key:
            return verbose_text[:200]

        system_instruction = (
            "You are an expert AI Communication Summarizer.\n"
            "Your task: Read the verbose technical response from the coding agent and summarize what clarification or missing detail is needed from the user.\n"
            "Return ONLY a clean, polite, 1-sentence question (e.g. 'What would you like to change the app name to?').\n"
            "Do NOT output file lists, code snippets, Markdown headers, or technical file paths."
        )

        api_model = normalize_gemini_model(self.config.model_name)

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{api_model}:generateContent"
            payload = {
                "system_instruction": {"parts": [{"text": system_instruction}]},
                "contents": [{"parts": [{"text": f"Verbose Agent Response:\n{verbose_text[:2000]}"}]}],
                "generationConfig": {"temperature": 0.2}
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
                        candidate_text = parts[0].get("text", "").strip()
                        if candidate_text:
                            logger.info(f"✨ Gemini LLM Summarized Clarification Question: '{candidate_text}'")
                            return candidate_text
        except Exception as e:
            logger.warning(f"⚠️ Gemini LLM summarization exception: {e}. Falling back to clean text preview.")

        return verbose_text[:200]
