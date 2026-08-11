import sys
from automation.domain.models import WorkflowEnvironment
from automation.services.cleanup_service import WorkspaceCleanupService
from automation.services.llm_metadata_service import LLMMetadataService
from automation.services.git_pr_service import GitPRService
from automation.services.notification_service import NotificationService

def main():
    try:
        config = WorkflowEnvironment()
    except Exception as e:
        print(f"❌ Invalid Environment Configuration: {e}")
        sys.exit(1)

    # 1. Clean up workspace unwanted files
    WorkspaceCleanupService.cleanup_unwanted_files()

    # 2. Use LLM Service for intelligent semantic Git & PR metadata generation
    metadata_service = LLMMetadataService(config)
    pr_details = metadata_service.generate_metadata()

    # 3. Handle Git & PR creation
    git_service = GitPRService(config, pr_details)
    if not git_service.has_changes():
        print("ℹ️ No file changes were produced by the agent.")
        return

    git_service.create_and_push_branch()
    pr_url = git_service.create_pull_request()

    # 4. Notify Slack if PR was created
    if pr_url:
        notifier = NotificationService(config, pr_details)
        notifier.send_slack_notification(pr_url)

if __name__ == "__main__":
    main()
