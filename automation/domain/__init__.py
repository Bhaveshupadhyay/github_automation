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
    NetworkProbeResult,
    WireGuardConfig,
)
from automation.domain.lifecycle import (
    ServiceStatus,
    ServiceProcessInfo,
    LifecycleResult,
)
from automation.domain.schema_detection import (
    MigrationFramework,
    ORMFramework,
    DatabaseType,
    SchemaSourceTier,
    DetectedMigration,
    DetectedORM,
    DetectedSchemaFile,
    DetectedDatabase,
    DockerServiceDefinition,
    SchemaDetectionResult,
)
from automation.domain.test_plan import (
    ActionType,
    AssertionType,
    TestAssertion,
    TestAction,
    TestJourney,
    TestPlan,
    DiffAnalysisResult,
)
from automation.domain.test_run import (
    TestOutcome,
    TestRunConfig,
    TestCaseResult,
    TestRunResult,
)
from automation.domain.media_processing import (
    MediaArtifact,
    MediaProcessingResult,
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
    "NetworkProbeResult",
    "WireGuardConfig",
    "ServiceStatus",
    "ServiceProcessInfo",
    "LifecycleResult",
    "MigrationFramework",
    "ORMFramework",
    "DatabaseType",
    "SchemaSourceTier",
    "DetectedMigration",
    "DetectedORM",
    "DetectedSchemaFile",
    "DetectedDatabase",
    "DockerServiceDefinition",
    "SchemaDetectionResult",
    "ActionType",
    "AssertionType",
    "TestAssertion",
    "TestAction",
    "TestJourney",
    "TestPlan",
    "DiffAnalysisResult",
    "TestOutcome",
    "TestRunConfig",
    "TestCaseResult",
    "TestRunResult",
    "MediaArtifact",
    "MediaProcessingResult",
]
