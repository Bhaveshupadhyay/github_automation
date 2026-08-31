import unittest
from unittest.mock import MagicMock, patch

from automation.domain import WorkflowEnvironment, GitPRDetails
from automation.domain.telemetry import PipelineStage
from automation.services.code_development_service import CodeDevelopmentService


class TestThreadIterationE2E(unittest.TestCase):

    def setUp(self):
        self.config = WorkflowEnvironment(
            slack_token="xoxb-mock-token",
            slack_channel="C12345678",
            slack_thread_ts="1725100000.000100",
            target_repo="owner/repo",
            user_prompt="Update the password validation rules",
            model_name="gemini-3.6-flash",
            effort_val="high"
        )

    def test_code_development_service_reuses_thread_branch(self):
        mock_cleanup = MagicMock()
        mock_slack_history = MagicMock()
        mock_slack_history.fetch_thread_history.return_value = "User: Initial request\nAssistant: PR created"
        
        mock_metadata = MagicMock()
        # Simulate that this thread already has an existing PR branch
        mock_metadata.find_existing_thread_branch.return_value = "feat/user-auth"
        mock_metadata.generate_metadata.return_value = GitPRDetails(
            branch_name="feat/user-auth",
            commit_message="feat(auth): update password validation rules",
            pr_title="feat(auth): update password validation rules",
            pr_body="Updated password validation.\n\n<!-- slack_thread: 1725100000.000100 -->"
        )

        mock_summarizer = MagicMock()
        mock_git_service = MagicMock()
        mock_git_service.has_changes.return_value = True
        mock_git_service.create_pull_request.return_value = "https://github.com/owner/repo/pull/15"

        mock_git_factory = MagicMock(return_value=mock_git_service)
        mock_notifier = MagicMock()
        mock_notifier_factory = MagicMock(return_value=mock_notifier)
        mock_telemetry = MagicMock()

        service = CodeDevelopmentService(
            config=self.config,
            cleanup_service=mock_cleanup,
            slack_history_service=mock_slack_history,
            metadata_service=mock_metadata,
            summarizer_service=mock_summarizer,
            git_pr_service_factory=mock_git_factory,
            notification_service_factory=mock_notifier_factory,
            telemetry_service=mock_telemetry,
        )

        # Mock graphify & agy execution
        with patch.object(service, "_run_graphify") as mock_graphify, \
             patch.object(service, "_resolve_agy_binary", return_value="agy"), \
             patch("subprocess.Popen") as mock_popen, \
             patch("builtins.open", unittest.mock.mock_open()):

            mock_proc = MagicMock()
            mock_proc.stdout = [
                "Tool: view_file AbsolutePath: /workspace/auth.py\n",
                "Tool: replace_file_content TargetFile: /workspace/auth.py\n",
                "Done.\n"
            ]
            mock_proc.returncode = 0
            mock_proc.wait.return_value = None
            mock_popen.return_value = mock_proc

            mock_graphify.return_value = MagicMock(returncode=0, stdout="Graphify context")

            service.execute_pipeline()

        # 1. Telemetry card initialized with thread iteration parameters
        mock_telemetry.initialize_card.assert_called_once_with(is_update_run=True, existing_branch="feat/user-auth")

        # 2. Telemetry streamed activities
        mock_telemetry.stream_activity.assert_any_call("Reading auth.py")
        mock_telemetry.stream_activity.assert_any_call("Editing auth.py")

        # 3. Git branch and PR reused and pushed
        mock_git_service.create_and_push_branch.assert_called_once()
        mock_git_service.create_pull_request.assert_called_once()

        # 4. Telemetry marked as complete with PR URL
        mock_telemetry.complete.assert_called_once_with(
            pr_url="https://github.com/owner/repo/pull/15",
            branch_name="feat/user-auth"
        )


if __name__ == "__main__":
    unittest.main()
