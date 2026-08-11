import sys
from automation.dependency import container

def main():
    try:
        # Access application configuration
        _ = container.config
    except Exception as e:
        print(f"❌ Invalid Environment Configuration: {e}")
        sys.exit(1)

    # 1. Clean up workspace unwanted files
    cleanup_service = container.get_cleanup_service()
    cleanup_service.cleanup_unwanted_files()

    # 2. Resolve IMetadataService interface via DI container
    metadata_service = container.get_metadata_service()
    pr_details = metadata_service.generate_metadata()

    # 3. Handle Git & PR creation
    git_service = container.get_git_pr_service(pr_details)
    if not git_service.has_changes():
        print("ℹ️ No file changes were produced by the agent.")
        return

    git_service.create_and_push_branch()
    pr_url = git_service.create_pull_request()

    # 4. Notify Slack if PR was created
    if pr_url:
        notifier = container.get_notification_service(pr_details)
        notifier.send_slack_notification(pr_url)

if __name__ == "__main__":
    main()
