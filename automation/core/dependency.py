"""Functional Dependency Injection Factories matching hiphopboombox-backend core/dependency.py pattern."""
from typing import Optional
from functools import lru_cache

from automation.domain import WorkflowEnvironment, GitPRDetails
from automation.interfaces import (
    IIntentRouterService,
    IMetadataService,
    ICodeDevelopmentService,
    ISummarizerService,
    IOrchestrationService,
    IDeploymentService,
    INotificationService,
    ISlackHistoryService,
    IGitPRService,
    IExecutionOutputClassifierService,
    ITelemetryService,
    IQAContractValidatorService,
    ISecretDriftDetectorService,
    ISOpsService,
    IHealthCheckService,
    IBranchResolver,
    IDatabaseStrategy,
    ILifecycleSupervisor,
    IProcessTreeManager,
    ISchemaDetectorService,
    IWireGuardService,
)

from automation.domain import (
    WorkflowEnvironment,
    GitPRDetails,
    DatabaseConfig,
    DatabaseStrategyType,
)

from automation.services.passthrough_intent_router_service import PassThroughIntentRouterService
from automation.services.gemini_metadata_service import GeminiLLMMetadataService
from automation.services.gemini_summarizer_service import GeminiLLMSummarizerService
from automation.services.code_development_service import CodeDevelopmentService
from automation.services.deployment_service import DeploymentService
from automation.services.notification_service import NotificationService
from automation.services.slack_telemetry_service import SlackTelemetryService
from automation.services.cleanup_service import WorkspaceCleanupService
from automation.services.git_pr_service import GitPRService
from automation.services.slack_history_service import SlackHistoryService
from automation.services.orchestration_service import TaskOrchestrationService
from automation.services.gemini_execution_output_classifier_service import GeminiExecutionOutputClassifierService
from automation.services.qa_contract_service import QAContractValidatorService
from automation.services.secret_drift_service import SecretDriftDetectorService
from automation.services.sops_service import SOpsService
from automation.services.health_check_service import HealthCheckService
from automation.services.branch_resolver_service import BranchResolverService
from automation.services.database_strategies import (
    DevCloudDatabaseStrategy,
    EphemeralRunnerDatabaseStrategy,
    create_database_strategy,
)
from automation.services.process_tree_manager import ProcessTreeManager
from automation.services.lifecycle_supervisor_service import LifecycleSupervisorService
from automation.services.schema_detection_service import SchemaDetectionService
from automation.services.wireguard_service import WireGuardService


@lru_cache(maxsize=1)
def get_config() -> WorkflowEnvironment:
    """Returns singleton WorkflowEnvironment config instance."""
    return WorkflowEnvironment()


def get_cleanup_service() -> WorkspaceCleanupService:
    return WorkspaceCleanupService()


def get_slack_history_service(config: Optional[WorkflowEnvironment] = None) -> ISlackHistoryService:
    cfg = config or get_config()
    return SlackHistoryService(cfg)


def get_intent_router_service(config: Optional[WorkflowEnvironment] = None) -> IIntentRouterService:
    cfg = config or get_config()
    return PassThroughIntentRouterService(cfg)


def get_metadata_service(config: Optional[WorkflowEnvironment] = None) -> IMetadataService:
    cfg = config or get_config()
    return GeminiLLMMetadataService(cfg)


def get_summarizer_service(config: Optional[WorkflowEnvironment] = None) -> ISummarizerService:
    cfg = config or get_config()
    return GeminiLLMSummarizerService(cfg)


def get_execution_output_classifier_service(config: Optional[WorkflowEnvironment] = None) -> IExecutionOutputClassifierService:
    cfg = config or get_config()
    return GeminiExecutionOutputClassifierService(cfg)


def get_deployment_service(config: Optional[WorkflowEnvironment] = None) -> IDeploymentService:
    cfg = config or get_config()
    return DeploymentService(cfg)


def get_git_pr_service(pr_details: GitPRDetails, config: Optional[WorkflowEnvironment] = None) -> IGitPRService:
    cfg = config or get_config()
    return GitPRService(cfg, pr_details)


def get_notification_service(pr_details: Optional[GitPRDetails] = None, config: Optional[WorkflowEnvironment] = None) -> INotificationService:
    cfg = config or get_config()
    return NotificationService(cfg, pr_details)


def get_telemetry_service(config: Optional[WorkflowEnvironment] = None) -> ITelemetryService:
    cfg = config or get_config()
    return SlackTelemetryService(cfg)


def get_code_development_service(config: Optional[WorkflowEnvironment] = None) -> ICodeDevelopmentService:
    cfg = config or get_config()
    return CodeDevelopmentService(
        config=cfg,
        cleanup_service=get_cleanup_service(),
        slack_history_service=get_slack_history_service(cfg),
        metadata_service=get_metadata_service(cfg),
        summarizer_service=get_summarizer_service(cfg),
        git_pr_service_factory=lambda pr_details: get_git_pr_service(pr_details, cfg),
        notification_service_factory=lambda pr_details=None: get_notification_service(pr_details, cfg),
        output_classifier=get_execution_output_classifier_service(cfg),
        telemetry_service=get_telemetry_service(cfg),
    )


def get_orchestration_service(config: Optional[WorkflowEnvironment] = None) -> IOrchestrationService:
    cfg = config or get_config()
    return TaskOrchestrationService(
        config=cfg,
        intent_router=get_intent_router_service(cfg),
        deployment_service=get_deployment_service(cfg),
        code_dev_service=get_code_development_service(cfg),
        notification_service_factory=lambda pr_details=None: get_notification_service(pr_details, cfg),
    )


def get_sops_service(sops_binary: Optional[str] = None) -> ISOpsService:
    """Returns ISOpsService implementation."""
    return SOpsService(sops_binary=sops_binary)


def get_secret_drift_detector_service(sops_service: Optional[ISOpsService] = None) -> ISecretDriftDetectorService:
    """Returns ISecretDriftDetectorService implementation."""
    return SecretDriftDetectorService(sops_service=sops_service or get_sops_service())


def get_qa_contract_validator_service(schema_path: Optional[str] = None) -> IQAContractValidatorService:
    """Returns IQAContractValidatorService implementation."""
    return QAContractValidatorService(schema_path=schema_path)


def get_health_check_service(default_timeout: float = 30.0, default_interval: float = 1.0) -> IHealthCheckService:
    """Returns IHealthCheckService implementation."""
    return HealthCheckService(default_timeout=default_timeout, default_interval=default_interval)


def get_branch_resolver_service(
    command_timeout_seconds: float = 5.0,
    api_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    genai_client: Optional[object] = None,
) -> IBranchResolver:
    """Returns IBranchResolver implementation."""
    return BranchResolverService(
        command_timeout_seconds=command_timeout_seconds,
        api_key=api_key,
        gemini_model=gemini_model,
        genai_client=genai_client,
    )


def get_process_tree_manager() -> IProcessTreeManager:
    """Returns IProcessTreeManager implementation."""
    return ProcessTreeManager()


def get_wireguard_service(wg_quick_binary: Optional[str] = None) -> IWireGuardService:
    """Returns IWireGuardService implementation."""
    return WireGuardService(wg_quick_binary=wg_quick_binary)


def get_database_strategy(
    config: Optional[DatabaseConfig] = None,
    wireguard_service: Optional[IWireGuardService] = None,
) -> IDatabaseStrategy:
    """Returns IDatabaseStrategy implementation from configuration."""
    if config is None:
        return DevCloudDatabaseStrategy()
    wg_svc = wireguard_service or get_wireguard_service()
    return create_database_strategy(config, wireguard_service=wg_svc)



def get_lifecycle_supervisor(
    sops_service: Optional[ISOpsService] = None,
    qa_contract_validator: Optional[IQAContractValidatorService] = None,
    health_check_service: Optional[IHealthCheckService] = None,
    process_tree_manager: Optional[IProcessTreeManager] = None,
) -> ILifecycleSupervisor:
    """Returns ILifecycleSupervisor implementation with injected services."""
    return LifecycleSupervisorService(
        sops_service=sops_service or get_sops_service(),
        qa_contract_validator=qa_contract_validator or get_qa_contract_validator_service(),
        health_check_service=health_check_service or get_health_check_service(),
        process_tree_manager=process_tree_manager or get_process_tree_manager(),
    )


def get_schema_detector_service() -> ISchemaDetectorService:
    """Returns ISchemaDetectorService implementation."""
    return SchemaDetectionService()
