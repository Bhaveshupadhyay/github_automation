import os
import json
import logging
from typing import Optional
from automation.domain.constants import DEFAULT_GEMINI_MODEL

logger = logging.getLogger("automation.credentials")

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

def normalize_gemini_model(model_name: Optional[str] = None) -> str:
    """Normalizes agy CLI internal model strings to valid Gemini API models."""
    if not model_name:
        return DEFAULT_GEMINI_MODEL
    model_lower = model_name.lower()
    if "pro" in model_lower:
        return "gemini-2.5-pro"
    return DEFAULT_GEMINI_MODEL
