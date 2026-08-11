import os
import re
import json
import logging
import subprocess
from typing import Optional

from google import genai
from google.genai import types

from automation.domain.models import GitPRDetails, WorkflowEnvironment
from automation.interfaces.metadata_service_interface import IMetadataService

logger = logging.getLogger("automation.metadata")

class GeminiLLMMetadataService(IMetadataService):
    """Concrete implementation of IMetadataService utilizing official google-genai SDK for semantic branch and PR generation."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def _get_git_diff_summary(self) -> str:
        res = subprocess.run(["git", "diff", "--stat"], capture_output=True, text=True)
        return res.stdout.strip()[:1000]

    def _find_existing_thread_branch(self) -> Optional[str]:
        """Queries GitHub for existing PRs matching slack_thread_ts to reuse exact semantic branch name."""
        if not self.config.slack_thread_ts or not self.config.target_repo:
            return None

        try:
            cmd = [
                "gh", "pr", "list",
                "--repo", self.config.target_repo,
                "--search", f"slack_thread: {self.config.slack_thread_ts}",
                "--json", "headRefName"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                prs = json.loads(res.stdout.strip())
                if prs and isinstance(prs, list) and "headRefName" in prs[0]:
                    existing_branch = prs[0]["headRefName"]
                    logger.info(f"🔍 Found existing semantic PR branch for thread {self.config.slack_thread_ts}: {existing_branch}")
                    return existing_branch
        except Exception as e:
            logger.debug(f"Thread PR lookup exception: {e}")

        return None

    def generate_metadata(self) -> GitPRDetails:
        # 1. Reuse existing branch if explicitly provided or found via Slack thread PR metadata
        semantic_branch = self.config.existing_branch or self._find_existing_thread_branch()

        api_key = os.getenv("AGY_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("ANTIGRAVITY_API_KEY", "").strip()
        diff_summary = self._get_git_diff_summary()
        
        # 2. Use Google's Official SDK for structured Pydantic response generation
        if api_key:
            try:
                client = genai.Client(api_key=api_key)
                
                system_instruction = (
                    "You are an expert Git Release Manager.\n"
                    "Your task: Generate semantic Git metadata for a Pull Request based on the user's prompt and git diff summary.\n"
                    "Follow Conventional Commit standard for commit_message and pr_title.\n"
                    "Format branch_name as a short semantic kebab-case string starting with feat/, fix/, or refactor/ (e.g. feat/add-redis-caching-trending-posts)."
                )

                prompt_content = f"User Prompt: {self.config.user_prompt}\nGit Diff Summary:\n{diff_summary}"

                response = client.models.generate_content(
                    model=self.config.model_name,
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
                    if self.config.slack_thread_ts:
                        details.pr_body += f"\n\n<!-- slack_thread: {self.config.slack_thread_ts} -->"

                    logger.info(f"🤖 google-genai SDK Generated Semantic Branch Name: {details.branch_name}")
                    logger.info(f"🤖 google-genai SDK Generated Commit Title: {details.commit_message}")
                    return details
            except Exception as e:
                logger.warning(f"⚠️ google-genai SDK call exception: {e}. Falling back to default formatting.")

        # 3. Failsafe fallback logic if SDK is missing or key is absent
        if not semantic_branch:
            clean_slug = re.sub(r"[^a-z0-9]", "-", self.config.user_prompt.lower())
            clean_slug = re.sub(r"-+", "-", clean_slug).strip("-")[:35]
            timestamp = int(subprocess.check_output(["date", "+%s"]).decode().strip())
            branch_name = f"feat/{clean_slug}-{timestamp}"
        else:
            branch_name = semantic_branch

        commit_msg = f"🤖 Antigravity AI Patch ({self.config.model_name}): {self.config.user_prompt}"
        pr_body = f"Automated PR generated by Google Antigravity Agent Engine for: {self.config.user_prompt}"
        if self.config.slack_thread_ts:
            pr_body += f"\n\n<!-- slack_thread: {self.config.slack_thread_ts} -->"

        return GitPRDetails(
            branch_name=branch_name,
            commit_message=commit_msg,
            pr_title=commit_msg,
            pr_body=pr_body
        )
