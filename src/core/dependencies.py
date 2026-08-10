from functools import lru_cache
from src.core.config import settings
from src.domain.interfaces import ILLMGateway, IGitGateway, IIndexerGateway, INotifierGateway
from src.infrastructure.llm.gemini_gateway import GeminiLLMAdapter
from src.infrastructure.git.github_gateway import GitHubGitAdapter
from src.infrastructure.indexer.graphify_indexer import GraphifyIndexerAdapter
from src.infrastructure.notification.notifier_gateway import CompositeNotifierAdapter
from src.use_cases.autonomous_developer import AutonomousDeveloperUseCase

@lru_cache
def get_llm_gateway() -> ILLMGateway:
    """Factory for LLM Gateway (Gemini API)."""
    return GeminiLLMAdapter(
        api_key=settings.gemini_api_key,
        model_name=settings.gemini_model,
        max_turns=settings.max_turns
    )

@lru_cache
def get_git_gateway() -> IGitGateway:
    """Factory for Git Gateway (GitHub REST & Git CLI)."""
    return GitHubGitAdapter(
        github_token=settings.github_token,
        default_repository=settings.github_repository
    )

@lru_cache
def get_indexer_gateway() -> IIndexerGateway:
    """Factory for Indexer Gateway (Graphify AST Indexer)."""
    return GraphifyIndexerAdapter()

@lru_cache
def get_notifier_gateway() -> INotifierGateway:
    """Factory for Composite Notifier Gateway (Slack & Telegram)."""
    return CompositeNotifierAdapter(
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        slack_token=settings.slack_bot_token,
        slack_channel_id=settings.slack_channel_id
    )

def get_autonomous_developer_use_case() -> AutonomousDeveloperUseCase:
    """
    Dependency Injection Container for AutonomousDeveloperUseCase.
    Wires up all required gateways and returns the use case instance.
    """
    return AutonomousDeveloperUseCase(
        llm_gateway=get_llm_gateway(),
        git_gateway=get_git_gateway(),
        indexer_gateway=get_indexer_gateway(),
        notifier_gateway=get_notifier_gateway()
    )
