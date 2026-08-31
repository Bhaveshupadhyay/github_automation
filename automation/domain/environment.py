import os
import re
import json
import logging
import urllib.request
import urllib.error
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from automation.domain.constants import DEFAULT_GEMINI_MODEL

logger = logging.getLogger("automation.domain.environment")

PROSE_SLASH_BLACKLIST = {
    "documentation/instructions", "create/update", "add/update", "update/create",
    "delete/remove", "pull/merge", "commit/push", "fetch/pull", "and/or", "true/false", 
    "read/write", "input/output", "import/export", "client/server", "master/slave", 
    "main/master", "ci/cd", "next.js/react"
}


def _get_api_key() -> str:
    """Helper to retrieve Gemini API key without circular imports."""
    for key_name in ("AGY_API_KEY", "GEMINI_API_KEY", "ANTIGRAVITY_API_KEY"):
        val = os.getenv(key_name, "").strip()
        if val:
            return val
    return ""


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


def extract_target_repo_with_gemini(user_prompt: str) -> Optional[str]:
    """Uses Gemini 3.1 Flash Lite REST API to extract target GitHub repository (owner/repo) semantically."""
    api_key = _get_api_key()
    if not api_key or not user_prompt.strip():
        return None

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={api_key}"
        system_instruction = (
            "You are an expert GitHub repository extractor.\n"
            "Analyze the user prompt and extract the target GitHub repository in 'owner/repo' format (e.g. 'bhaveshupadhyay/culture_box' or 'bhaveshupadhyay/edu-api').\n"
            "CRITICAL RULE: Ignore general English prose containing slashes such as 'documentation/instructions', 'create/update', 'add/update', 'and/or', 'CI/CD', 'read/write', 'input/output'.\n"
            "If no target GitHub repository is explicitly specified, respond with JSON: {\"target_repo\": null}."
        )
        payload = {
            "contents": [{"parts": [{"text": f"{system_instruction}\n\nUser Prompt: {user_prompt}"}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    raw_text = parts[0].get("text", "").strip()
                    parsed = parse_json_safely(raw_text)
                    if parsed and isinstance(parsed, dict):
                        target = parsed.get("target_repo")
                        if target and "/" in target and target.lower() not in PROSE_SLASH_BLACKLIST:
                            clean_target = target.strip().strip("'\"‘’“”")
                            logger.info(f"🎯 Extracted Target Repo via Gemini 3.1 Flash Lite: '{clean_target}'")
                            return clean_target
    except Exception as e:
        logger.debug(f"Gemini repo extraction exception: {e}")
    return None


def extract_target_repo(user_prompt: str, env_target: str) -> str:
    """Extracts explicit owner/repo slug from user prompt if present using Gemini + regex fallback."""
    env_target_clean = env_target.strip().strip("'\"‘’“”") if env_target else ""

    if user_prompt:
        # 1. First try Gemini 3.1 Flash Lite semantic extraction
        gemini_target = extract_target_repo_with_gemini(user_prompt)
        if gemini_target:
            return gemini_target

        # 2. Fallback to Regex with Blacklist Filtering
        cleaned_prompt = re.sub(r"https?://[^\s]+", "", user_prompt)
        cleaned_prompt = re.sub(r"github\.com/[^\s]+", "", cleaned_prompt)
        
        matches = re.findall(r"\b([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)\b", cleaned_prompt)
        for slug in matches:
            slug_clean = slug.strip().strip("'\"‘’“”")
            slug_lower = slug_clean.lower()
            if slug_lower not in PROSE_SLASH_BLACKLIST and not slug_lower.startswith("original"):
                logger.info(f"🎯 Extracted Target Repo via Regex Fallback: '{slug_clean}'")
                return slug_clean

    return env_target_clean


class WorkflowEnvironment(BaseModel):
    """Pydantic domain model representing environment configuration passed from GitHub Actions."""
    gh_token: str = Field(default_factory=lambda: os.getenv("GH_TOKEN", ""))
    slack_token: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_TOKEN"))
    slack_channel: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_CHANNEL"))
    slack_thread_ts: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_THREAD"))
    existing_branch: Optional[str] = Field(default_factory=lambda: os.getenv("EXISTING_BRANCH"))
    user_prompt: str = Field(default_factory=lambda: os.getenv("USER_PROMPT", ""))
    target_repo: str = Field(default="")
    model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", DEFAULT_GEMINI_MODEL))
    effort_val: str = Field(default_factory=lambda: os.getenv("EFFORT_VAL", "high"))
    execution_log_path: str = Field(default="../agy_execution.log")

    def __init__(self, **data):
        super().__init__(**data)
        explicit_target = data.get("target_repo", "").strip().strip("'\"‘’“”") if data.get("target_repo") else ""
        env_target = os.getenv("TARGET_REPO", "").strip().strip("'\"‘’“”")
        if explicit_target:
            self.target_repo = explicit_target
        elif "TARGET_REPO" in os.environ and env_target != "":
            self.target_repo = env_target
        else:
            self.target_repo = extract_target_repo(self.user_prompt, env_target)
