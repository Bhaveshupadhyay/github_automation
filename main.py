#!/usr/bin/env python3
"""
Application Main Entry Point
Uses Clean Architecture & Dependency Injection Container.
Supports prompt via CLI arguments (`uv run main.py "owner/repo prompt"`) or environment variables.
"""

import sys
import os

# Add root directory to python path for clean module imports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.core.config import settings
from src.core.logger import logger
from src.core.dependencies import get_autonomous_developer_use_case
from src.domain.entities import CodeChangeRequest

def main() -> None:
    # 1. Determine Raw Prompt from CLI Argument or Env Variable
    raw_prompt = sys.argv[1] if len(sys.argv) > 1 else settings.user_prompt

    if not raw_prompt:
        logger.warning("No prompt provided via CLI argument or USER_PROMPT environment variable. Exiting.")
        logger.info("Usage: uv run main.py \"<owner/repo> <your prompt>\" OR set GITHUB_REPOSITORY & USER_PROMPT in .env")
        sys.exit(0)

    # 2. Parse target repository if prompt starts with "owner/repo"
    target_repo = os.getenv("TARGET_REPO", settings.github_repository)
    prompt = raw_prompt.strip()

    words = prompt.split(" ")
    if len(words) > 1 and "/" in words[0]:
        target_repo = words[0]
        prompt = " ".join(words[1:])
        logger.info(f"Parsed target repository from prompt argument: '{target_repo}'")

    logger.info(f"Starting Autonomous Developer Execution for repo '{target_repo}' with prompt: '{prompt}'")

    # 3. Inject dependencies and construct use case via DI Container
    use_case = get_autonomous_developer_use_case()

    # 4. Execute Use Case with dynamic repository!
    request = CodeChangeRequest(
        user_prompt=prompt,
        repository=target_repo
    )
    use_case.execute(request)

    logger.info("Autonomous Developer Execution finished successfully.")

if __name__ == "__main__":
    main()
