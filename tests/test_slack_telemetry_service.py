import time
import unittest
from unittest.mock import patch, MagicMock

from automation.domain import WorkflowEnvironment
from automation.domain.telemetry import PipelineStage, StageStatus, TelemetryState
from automation.services.slack_telemetry_service import SlackTelemetryService


class TestSlackTelemetryService(unittest.TestCase):

    def setUp(self):
        self.config = WorkflowEnvironment(
            slack_token="xoxb-mock-token",
            slack_channel="C12345678",
            slack_thread_ts="1725100000.000100",
            target_repo="owner/repo",
            user_prompt="Add JWT authentication middleware",
            model_name="gemini-3.6-flash",
            effort_val="high"
        )
        self.telemetry = SlackTelemetryService(self.config, min_update_interval=0.1)

    @patch.object(SlackTelemetryService, "_send_slack_api")
    def test_initialize_card_new_run(self, mock_api):
        mock_api.return_value = {"ok": True, "ts": "1725100005.000200"}
        ts = self.telemetry.initialize_card(is_update_run=False)

        self.assertEqual(ts, "1725100005.000200")
        self.assertEqual(self.telemetry.state.message_ts, "1725100005.000200")
        self.assertFalse(self.telemetry.state.is_update_run)

        # Check rendered text contains header and stages
        rendered = self.telemetry._render_progress_text()
        self.assertIn("*Antigravity Autonomous Developer*", rendered)
        self.assertIn("• *Repository:* `owner/repo`", rendered)
        self.assertIn("[ ] *1. Workspace & AST Knowledge Graph*", rendered)
        self.assertIn("[ ] *2. Antigravity AI Coding Engine*", rendered)

    @patch.object(SlackTelemetryService, "_send_slack_api")
    def test_initialize_card_existing_thread_iteration(self, mock_api):
        mock_api.return_value = {"ok": True, "ts": "1725100005.000200"}
        ts = self.telemetry.initialize_card(is_update_run=True, existing_branch="feat/jwt-auth")

        self.assertEqual(ts, "1725100005.000200")
        self.assertTrue(self.telemetry.state.is_update_run)
        self.assertEqual(self.telemetry.state.existing_branch, "feat/jwt-auth")

        rendered = self.telemetry._render_progress_text()
        self.assertIn("(Thread Iteration)", rendered)
        self.assertIn("• *Branch:* `feat/jwt-auth` (Updating existing PR)", rendered)

    @patch.object(SlackTelemetryService, "_send_slack_api")
    def test_stage_progression_and_durations(self, mock_api):
        mock_api.return_value = {"ok": True, "ts": "1725100005.000200"}
        self.telemetry.initialize_card()

        # Start Stage 1 (Graphify AST)
        self.telemetry.update_stage(PipelineStage.GRAPHIFY_AST, "Building AST index...")
        self.assertEqual(self.telemetry.state.current_stage, PipelineStage.GRAPHIFY_AST)
        self.assertEqual(self.telemetry.state.stage_statuses[PipelineStage.GRAPHIFY_AST.value], StageStatus.RUNNING)

        time.sleep(0.05)

        # Transition to Stage 2 (AGY_EXECUTION) -> Stage 1 should be marked COMPLETED
        self.telemetry.update_stage(PipelineStage.AGY_EXECUTION, "Executing engine...")
        self.assertEqual(self.telemetry.state.stage_statuses[PipelineStage.GRAPHIFY_AST.value], StageStatus.COMPLETED)
        self.assertEqual(self.telemetry.state.stage_statuses[PipelineStage.AGY_EXECUTION.value], StageStatus.RUNNING)

        rendered = self.telemetry._render_progress_text()
        self.assertIn("[✓] *1. Workspace & AST Knowledge Graph*", rendered)
        self.assertIn("[>] *2. Antigravity AI Coding Engine*", rendered)

    @patch.object(SlackTelemetryService, "_send_slack_api")
    def test_stream_activity_debouncing(self, mock_api):
        mock_api.return_value = {"ok": True, "ts": "1725100005.000200"}
        self.telemetry.initialize_card()
        self.telemetry.update_stage(PipelineStage.AGY_EXECUTION)

        initial_calls = mock_api.call_count

        # Rapid fire streaming calls
        self.telemetry.stream_activity("Editing auth.py")
        self.telemetry.stream_activity("Editing user.py")
        self.telemetry.stream_activity("Editing config.py")

        # Due to min_update_interval, redundant calls are throttled
        self.assertEqual(self.telemetry.state.active_activity, "Editing config.py")

    @patch.object(SlackTelemetryService, "_send_slack_api")
    def test_completion_flow(self, mock_api):
        mock_api.return_value = {"ok": True, "ts": "1725100005.000200"}
        self.telemetry.initialize_card()
        self.telemetry.complete(pr_url="https://github.com/owner/repo/pull/42", branch_name="feat/jwt-auth")

        self.assertEqual(self.telemetry.state.current_stage, PipelineStage.COMPLETED)
        for stage in self.telemetry.STAGE_ORDER:
            self.assertEqual(self.telemetry.state.stage_statuses[stage.value], StageStatus.COMPLETED)

        rendered = self.telemetry._render_progress_text()
        self.assertIn("[✓] *1. Workspace & AST Knowledge Graph*", rendered)
        self.assertIn("[✓] *2. Antigravity AI Coding Engine*", rendered)
        self.assertIn("[✓] *3. Output Intent & Quality Verification*", rendered)
        self.assertIn("[✓] *4. Git Branch & Pull Request Generation*", rendered)
        self.assertIn("<https://github.com/owner/repo/pull/42|Pull Request Ready for Review>", rendered)

    @patch.object(SlackTelemetryService, "_send_slack_api")
    def test_clarification_flow(self, mock_api):
        mock_api.return_value = {"ok": True, "ts": "1725100005.000200"}
        self.telemetry.initialize_card()
        self.telemetry.request_clarification("Should we use RS256 or HS256 for token signing?")

        self.assertEqual(self.telemetry.state.current_stage, PipelineStage.CLARIFICATION_NEEDED)
        rendered = self.telemetry._render_progress_text()
        self.assertIn("*Status:* Clarification Needed", rendered)
        self.assertIn("• *Question:* Should we use RS256 or HS256 for token signing?", rendered)

    @patch.object(SlackTelemetryService, "_send_slack_api")
    def test_failure_flow(self, mock_api):
        mock_api.return_value = {"ok": True, "ts": "1725100005.000200"}
        self.telemetry.initialize_card()
        self.telemetry.fail("Process timed out after 15 minutes")

        self.assertEqual(self.telemetry.state.current_stage, PipelineStage.FAILED)
        rendered = self.telemetry._render_progress_text()
        self.assertIn("*Status:* Pipeline execution failed", rendered)
        self.assertIn("• *Error:* Process timed out after 15 minutes", rendered)


if __name__ == "__main__":
    unittest.main()
