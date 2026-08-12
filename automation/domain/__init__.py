"""Domain package containing core entities, constants, and integration DTOs."""
from automation.domain.constants import DEFAULT_GEMINI_MODEL, SpecialTags
from automation.domain.intent import TaskCategory, TaskIntent
from automation.domain.environment import extract_target_repo, WorkflowEnvironment
from automation.domain.git import GitPRDetails
from automation.domain.slack import SlackMessage, SlackConversationsRepliesResponse

__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "SpecialTags",
    "TaskCategory",
    "TaskIntent",
    "extract_target_repo",
    "WorkflowEnvironment",
    "GitPRDetails",
    "SlackMessage",
    "SlackConversationsRepliesResponse",
]
