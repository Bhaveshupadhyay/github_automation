"""Domain package containing core entities, constants, and integration DTOs."""
from automation.domain.constants import DEFAULT_GEMINI_MODEL, SpecialTags
from automation.domain.intent import TaskCategory, TaskIntent
from automation.domain.environment import extract_target_repo, WorkflowEnvironment
from automation.domain.git import GitPRDetails
from automation.domain.slack import SlackMessage, SlackConversationsRepliesResponse
from automation.domain.telemetry import PipelineStage, StageStatus, TelemetryState
from automation.domain.qa_contract import (
    QAContract,
    ServiceType,
    MobilePlatform,
    MobileConfig,
    LifecycleHooks,
)
from automation.domain.secret_drift import DriftReport
from automation.domain.health_check import HealthCheckResult
from automation.domain.branch_resolver import (
    ResolutionSource,
    BranchResolutionResult,
    AIExtractedBranch,
)
from automation.domain.database_strategy import (
    DatabaseStrategyType,
    MigrationResult,
    DatabaseConfig,
)
from automation.domain.lifecycle import (
    ServiceStatus,
    ServiceProcessInfo,
    LifecycleResult,
)

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
    "PipelineStage",
    "StageStatus",
    "TelemetryState",
    "QAContract",
    "ServiceType",
    "MobilePlatform",
    "MobileConfig",
    "LifecycleHooks",
    "DriftReport",
    "HealthCheckResult",
    "ResolutionSource",
    "BranchResolutionResult",
    "AIExtractedBranch",
    "DatabaseStrategyType",
    "MigrationResult",
    "DatabaseConfig",
    "ServiceStatus",
    "ServiceProcessInfo",
    "LifecycleResult",
]
