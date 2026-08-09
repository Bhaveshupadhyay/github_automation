#!/usr/bin/env python3
"""
Application Entry Point & Dependency Injection Container
Follows Clean Architecture principles.
"""

import sys
from src.core.config import Settings
from src.domain.entities import CodeChangeRequest
from src.use_cases.autonomous_developer import AutonomousDeveloperUseCase
from src.infrastructure.llm.gemini_gateway import GeminiLLMAdapter
from src.infrastructure.git.github_gateway import GitHubGitAdapter
from src.infrastructure.indexer.graphify_indexer import GraphifyIndexerAdapter
from src.infrastructure.notification.notifier_gateway import CompositeNotifierAdapter

def main():
    # 1. Load Settings
    settings = Settings.from_env()

    if not settings.user_prompt:
        print("No user prompt provided. Exiting.")
        sys.exit(0)

    # 2. Dependency Injection Assembly (Composition Root)
    llm_gateway = GeminiLLMAdapter(api_key=settings.gemini_api_key)
    git_gateway = GitHubGitAdapter(
        github_token=settings.github_token,
        repository=settings.github_repository
    )
    indexer_gateway = GraphifyIndexerAdapter()
    notifier_gateway = CompositeNotifierAdapter(
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        slack_token=settings.slack_bot_token,
        slack_channel=settings.slack_channel_id
    )

    # 3. Instantiate Use Case
    use_case = AutonomousDeveloperUseCase(
        llm_gateway=llm_gateway,
        git_gateway=git_gateway,
        indexer_gateway=indexer_gateway,
        notifier_gateway=notifier_gateway
    )

    # 4. Execute Use Case
    request = CodeChangeRequest(
        user_prompt=settings.user_prompt,
        repository=settings.github_repository
    )
    use_case.execute(request)

if __name__ == "__main__":
    main()
