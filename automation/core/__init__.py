"""Core infrastructure, credentials, and dependency injection package."""
from automation.core.credentials import get_gemini_api_key, normalize_gemini_model
from automation.core.dependency import (
    get_config,
    get_cleanup_service,
    get_slack_history_service,
    get_intent_router_service,
    get_metadata_service,
    get_summarizer_service,
    get_deployment_service,
    get_git_pr_service,
    get_notification_service,
    get_telemetry_service,
    get_code_development_service,
    get_orchestration_service,
)

__all__ = [
    "get_gemini_api_key",
    "normalize_gemini_model",
    "get_config",
    "get_cleanup_service",
    "get_slack_history_service",
    "get_intent_router_service",
    "get_metadata_service",
    "get_summarizer_service",
    "get_deployment_service",
    "get_git_pr_service",
    "get_notification_service",
    "get_telemetry_service",
    "get_code_development_service",
    "get_orchestration_service",
]
