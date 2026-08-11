import os
import re
import time
import json
import logging
import subprocess
from typing import Optional

from google import genai
from google.genai import types

from automation.domain.models import GitPRDetails, WorkflowEnvironment
from automation.domain.constants import SpecialTags
from automation.interfaces.metadata_service_interface import IMetadataService
from automation.services.gemini_intent_router_service import normalize_gemini_model, get_gemini_api_key

logger = logging.getLogger("automation.metadata")

class GeminiLLMMetadataService(IMetadataService):
    """Concrete implementation of IMetadataService utilizing official google-genai SDK.
    Parses AGY_EXECUTION_SUMMARY output by agy engine and generates semantic branch, commit title, and PR description.
    """
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def _extract_agy_execution_summary(self) -> str:
        """Extracts AGY_EXECUTION_SUMMARY section from agy execution log file."""
        log_path = self.config.execution_log_path
        tag = SpecialTags.AGY_EXECUTION_SUMMARY.value
        
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    matches = re.split(re.escape(tag), content)
                    if len(matches) > 1:
                        summary_text = matches[-1].strip()
                        logger.info("📋 Extracted AGY Execution Summary from log file.")
                        return summary_text[:2000]
            except Exception as e:
                logger.warning(f"Failed to read agy execution log summary: {e}")
        
        # Fallback to git diff summary if log summary is unavailable
        try:
            res = subprocess.run(["git", "diff", "--stat"], capture_output=True, text=True, timeout=10)
            return res.stdout.strip()[:1000]
        except Exception:
            return "Git diff summary unavailable."

    def _find_existing_thread_branch(self) -> Optional[str]:
        """Queries GitHub for existing PRs matching slack_thread_ts to reuse exact semantic branch name."""
        if not self.config.slack_thread_ts or not self.config.target_repo:
            return None

        try:
            cmd = [
                "gh", "pr", "list",
                "--repo", self.config.target_repo,
                "--search", f"\"slack_thread: {self.config.slack_thread_ts}\" in:body",
                "--json", "headRefName"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                prs = json.loads(res.stdout.strip())
                if prs and isinstance(prs, list) and len(prs) > 0 and "headRefName" in prs[0]:
                    existing_branch = prs[0]["headRefName"]
                    if existing_branch and existing_branch.strip():
                        logger.info(f"🔍 Found existing semantic PR branch for thread {self.config.slack_thread_ts}: {existing_branch}")
                        return existing_branch.strip()
        except Exception as e:
            logger.debug(f"Thread PR lookup exception: {e}")

        return None

    def generate_metadata(self) -> GitPRDetails:
        # 1. Reuse existing branch if explicitly provided or found via Slack thread PR metadata
        semantic_branch = self.config.existing_branch or self._find_existing_thread_branch()

        api_key = get_gemini_api_key()
        execution_summary = self._extract_agy_execution_summary()
        
        # 2. Use Google's Official SDK for structured Pydantic response generation
        if api_key:
            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=45.0)
                )
                
                system_instruction = (
                    "You are an expert Git Release Manager.\n"
                    "Your task: Generate semantic Git metadata for a Pull Request based on the user's prompt and AGY Execution Summary.\n"
                    "Follow Conventional Commit standard for commit_message and pr_title (e.g. feat(scope): description).\n"
                    "Format branch_name as a short semantic kebab-case string starting with feat/, fix/, or refactor/ (e.g. feat/add-redis-caching-trending-posts).\n"
                    "Format pr_body as a rich Markdown document detailing key changes, affected files, and verification steps."
                )

                prompt_content = (
                    f"User Prompt: {self.config.user_prompt}\n\n"
                    f"AGY Execution Summary:\n{execution_summary}"
                )
                api_model = normalize_gemini_model(self.config.model_name)
                logger.info(f"⚡ Requesting PR metadata from Gemini API model '{api_model}'...")

                response = client.models.generate_content(
                    model=api_model,
                    contents=prompt_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=GitPRDetails
                    )
                )

                if response.parsed and isinstance(response.parsed, GitPRDetails):
                    details: GitPRDetails = response.parsed
                    
                    # If thread already has an existing semantic branch, preserve it
                    if semantic_branch:
                        details.branch_name = semantic_branch

                    # Embed invisible Slack thread tracking metadata in PR body for future turn lookups
                    if self.config.slack_thread_ts and "slack_thread:" not in details.pr_body:
                        details.pr_body += f"\n\n<!-- slack_thread: {self.config.slack_thread_ts} -->"

                    logger.info(f"🤖 Gemini LLM Generated Semantic Branch Name: {details.branch_name}")
                    logger.info(f"🤖 Gemini LLM Generated Commit Title: {details.commit_message}")
                    return details
            except Exception as e:
                logger.warning(f"⚠️ google-genai SDK call exception [{type(e).__name__}]: {e}. Falling back to default formatting.")

        # 3. Failsafe fallback logic if SDK is missing or key is absent
        if not semantic_branch:
            clean_slug = re.sub(r"[^a-z0-9]", "-", self.config.user_prompt.lower())
            clean_slug = re.sub(r"-+", "-", clean_slug).strip("-")[:35]
            timestamp = int(time.time())
            branch_name = f"feat/{clean_slug}-{timestamp}"
        else:
            branch_name = semantic_branch

        commit_msg = f"🤖 Antigravity AI Patch ({self.config.model_name}): {self.config.user_prompt}"
        pr_body = (
            f"### User Prompt\n{self.config.user_prompt}\n\n"
            f"### Execution Summary\n{execution_summary}\n\n"
            f"Automated PR generated by Google Antigravity Agent Engine."
        )
        if self.config.slack_thread_ts:
            pr_body += f"\n\n<!-- slack_thread: {self.config.slack_thread_ts} -->"

        return GitPRDetails(
            branch_name=branch_name,
            commit_message=commit_msg,
            pr_title=commit_msg,
            pr_body=pr_body
        )
