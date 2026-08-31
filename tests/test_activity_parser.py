import unittest
from unittest.mock import MagicMock

from automation.domain import WorkflowEnvironment
from automation.services.code_development_service import CodeDevelopmentService


class TestActivityParser(unittest.TestCase):

    def setUp(self):
        config = WorkflowEnvironment(target_repo="owner/repo", user_prompt="Add user auth")
        self.service = CodeDevelopmentService(
            config=config,
            cleanup_service=MagicMock(),
            slack_history_service=MagicMock(),
            metadata_service=MagicMock(),
            summarizer_service=MagicMock(),
            git_pr_service_factory=MagicMock(),
            notification_service_factory=MagicMock(),
        )

    def test_parse_file_edits(self):
        line1 = "Tool: replace_file_content TargetFile: /workspace/services/auth_service.py"
        self.assertEqual(self.service._parse_activity_line(line1), "Editing auth_service.py")

        line2 = 'write_to_file TargetFile="/app/controllers/user_controller.py"'
        self.assertEqual(self.service._parse_activity_line(line2), "Editing user_controller.py")

    def test_parse_file_reads(self):
        line = "Tool: view_file AbsolutePath: /workspace/domain/models.py"
        self.assertEqual(self.service._parse_activity_line(line), "Reading models.py")

    def test_parse_searches(self):
        line = "Tool: grep_search Query: 'def authenticate_user'"
        self.assertEqual(self.service._parse_activity_line(line), "Searching 'def authenticate_user'")

    def test_parse_commands(self):
        line = "Tool: run_command CommandLine: 'pytest tests/test_auth.py'"
        self.assertEqual(self.service._parse_activity_line(line), "Running `pytest tests/test_auth.py`")

    def test_parse_thinking(self):
        line = "Thinking: Let's inspect the existing auth flow..."
        self.assertEqual(self.service._parse_activity_line(line), "Synthesizing code architecture")

    def test_unrelated_output(self):
        line = "Total lines in response: 42"
        self.assertIsNone(self.service._parse_activity_line(line))


if __name__ == "__main__":
    unittest.main()
