"""Interfaces package containing abstract contracts for all automation services."""
from automation.interfaces.code_development_interface import ICodeDevelopmentService
from automation.interfaces.intent_router_interface import IIntentRouterService
from automation.interfaces.metadata_service_interface import IMetadataService
from automation.interfaces.summarizer_interface import ISummarizerService
from automation.interfaces.orchestration_interface import IOrchestrationService
from automation.interfaces.deployment_interface import IDeploymentService
from automation.interfaces.notification_interface import INotificationService
from automation.interfaces.slack_history_interface import ISlackHistoryService
from automation.interfaces.git_pr_interface import IGitPRService
from automation.interfaces.execution_output_classifier_interface import IExecutionOutputClassifierService
from automation.interfaces.telemetry_interface import ITelemetryService
from automation.interfaces.qa_contract_interface import IQAContractValidatorService
from automation.interfaces.secret_drift_interface import ISecretDriftDetectorService
from automation.interfaces.sops_interface import ISOpsService
from automation.interfaces.health_check_interface import IHealthCheckService
from automation.interfaces.branch_resolver_interface import IBranchResolver
from automation.interfaces.database_strategy_interface import IDatabaseStrategy
from automation.interfaces.lifecycle_interface import ILifecycleSupervisor
from automation.interfaces.process_tree_interface import IProcessTreeManager

__all__ = [
    "ICodeDevelopmentService",
    "IIntentRouterService",
    "IMetadataService",
    "ISummarizerService",
    "IOrchestrationService",
    "IDeploymentService",
    "INotificationService",
    "ISlackHistoryService",
    "IGitPRService",
    "IExecutionOutputClassifierService",
    "ITelemetryService",
    "IQAContractValidatorService",
    "ISecretDriftDetectorService",
    "ISOpsService",
    "IHealthCheckService",
    "IBranchResolver",
    "IDatabaseStrategy",
    "ILifecycleSupervisor",
    "IProcessTreeManager",
]

