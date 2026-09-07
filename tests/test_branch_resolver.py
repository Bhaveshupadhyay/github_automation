"""Comprehensive unit tests for cross-repository branch resolution."""
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import pydantic

from automation.domain.branch_resolver import (
    AIExtractedBranch,
    BranchResolutionResult,
    ResolutionSource,
)
from automation.services.branch_resolver_service import BranchResolverService


class TestBranchResolverService(unittest.TestCase):
    """Test suite covering Tier 1, 2, 3 resolution, sanitization, and edge cases."""

    def setUp(self) -> None:
        self.service = BranchResolverService(command_timeout_seconds=2.0)
        self.backend_url = "https://github.com/example-org/backend-service.git"
        self.source_branch = "feat/cart-checkout"

    # -------------------------------------------------------------------------
    # Tier 1: Explicit PR Body Linkage Tests
    # -------------------------------------------------------------------------

    @patch.object(BranchResolverService, "check_remote_ref_exists")
    def test_tier_1_explicit_backend_branch(self, mock_ref_check: MagicMock) -> None:
        mock_ref_check.return_value = True
        pr_body = """
        ## Summary
        This PR integrates payment v2 into the mobile app.
        
        Backend Branch: feat/payments-v2
        """
        result = self.service.resolve_branch(
            pr_body=pr_body,
            source_branch=self.source_branch,
            backend_repo_url=self.backend_url,
        )
        self.assertEqual(result.target_branch, "feat/payments-v2")
        self.assertEqual(result.resolution_source, ResolutionSource.EXPLICIT_PR_BODY)
        self.assertFalse(result.clarification_needed)
        self.assertEqual(result.details.get("matched_pattern"), "branch")

    @patch.object(BranchResolverService, "check_remote_ref_exists")
    def test_tier_1_explicit_backend_pr_number(self, mock_ref_check: MagicMock) -> None:
        mock_ref_check.return_value = True
        pr_body = "Depends on Backend PR: #108 before merging."
        result = self.service.resolve_branch(
            pr_body=pr_body,
            source_branch=self.source_branch,
            backend_repo_url=self.backend_url,
        )
        self.assertEqual(result.target_branch, "refs/pull/108/head")
        self.assertEqual(result.resolution_source, ResolutionSource.EXPLICIT_PR_BODY)
        self.assertFalse(result.clarification_needed)
        self.assertEqual(result.details.get("pr_number"), 108)

    @patch.object(BranchResolverService, "check_remote_ref_exists")
    def test_tier_1_markdown_variants_and_formatting(self, mock_ref_check: MagicMock) -> None:
        mock_ref_check.return_value = True
        cases = [
            ("**Backend Branch:** `feat/api-auth`", "feat/api-auth"),
            ("Target Branch: feat/custom-endpoint", "feat/custom-endpoint"),
            ("- [x] Backend Branch: [feat/order-flow](https://github.com/org/repo)", "feat/order-flow"),
            ("<!-- Backend Branch: feat/hidden-comment -->", "feat/hidden-comment"),
            ("backend_branch: release/2.4.0", "release/2.4.0"),
            ("Target PR: 42", "refs/pull/42/head"),
        ]
        for body, expected_branch in cases:
            with self.subTest(body=body):
                res = self.service.resolve_branch(
                    pr_body=body,
                    source_branch=self.source_branch,
                    backend_repo_url=self.backend_url,
                )
                self.assertEqual(res.target_branch, expected_branch)
                self.assertEqual(res.resolution_source, ResolutionSource.EXPLICIT_PR_BODY)

    @patch.object(BranchResolverService, "check_remote_branch_exists")
    @patch.object(BranchResolverService, "check_remote_ref_exists")
    def test_tier_1_explicit_target_not_on_remote_falls_back(
        self, mock_ref_check: MagicMock, mock_branch_check: MagicMock
    ) -> None:
        # Explicit target does not exist on remote, but 'dev' exists
        mock_ref_check.return_value = False
        mock_branch_check.side_effect = lambda url, branch: branch == "dev"

        pr_body = "Backend Branch: feat/nonexistent-typo"
        result = self.service.resolve_branch(
            pr_body=pr_body,
            source_branch=self.source_branch,
            backend_repo_url=self.backend_url,
            default_branch="dev",
        )
        self.assertEqual(result.target_branch, "dev")
        self.assertEqual(result.resolution_source, ResolutionSource.DEFAULT_FALLBACK)
        self.assertTrue(result.clarification_needed)
        self.assertIn("Declared Backend Target Not Found", result.clarification_message or "")

    # -------------------------------------------------------------------------
    # Ambiguity Detection Tests
    # -------------------------------------------------------------------------

    @patch.object(BranchResolverService, "check_remote_ref_exists")
    @patch.object(BranchResolverService, "extract_branch_with_ai")
    def test_competing_branch_and_pr_triggers_ambiguity(
        self, mock_ai: MagicMock, mock_ref_check: MagicMock
    ) -> None:
        mock_ref_check.return_value = True
        mock_ai.return_value = ("feat/branch-a", {"ai_confidence": 0.95})

        # Body declares BOTH branch and PR -> must be treated as ambiguous and consult AI
        pr_body = "Backend Branch: feat/branch-a\nBackend PR: #123"
        result = self.service.resolve_branch(
            pr_body=pr_body,
            source_branch=self.source_branch,
            backend_repo_url=self.backend_url,
        )
        self.assertEqual(result.target_branch, "feat/branch-a")
        self.assertEqual(result.resolution_source, ResolutionSource.AI_SEMANTIC_EXTRACTION)

    # -------------------------------------------------------------------------
    # Tier 2: Remote Branch Head Matching Tests
    # -------------------------------------------------------------------------

    @patch.object(BranchResolverService, "check_remote_branch_exists")
    def test_tier_2_remote_branch_match_success(self, mock_check: MagicMock) -> None:
        # Simulate that 'feat/cart-checkout' exists on backend repo
        mock_check.side_effect = lambda url, branch: branch == "feat/cart-checkout"

        result = self.service.resolve_branch(
            pr_body="Regular PR description with no backend branch declared.",
            source_branch="feat/cart-checkout",
            backend_repo_url=self.backend_url,
        )
        self.assertEqual(result.target_branch, "feat/cart-checkout")
        self.assertEqual(result.resolution_source, ResolutionSource.REMOTE_BRANCH_MATCH)
        self.assertFalse(result.clarification_needed)

    # -------------------------------------------------------------------------
    # Tier 3: Default Fallback & Clarification Tests
    # -------------------------------------------------------------------------

    @patch.object(BranchResolverService, "check_remote_branch_exists")
    def test_tier_3_fallback_to_dev(self, mock_check: MagicMock) -> None:
        # Simulate matching branch doesn't exist, but 'dev' exists
        mock_check.side_effect = lambda url, branch: branch == "dev"

        result = self.service.resolve_branch(
            pr_body="Simple UI button color change",
            source_branch="feat/ui-color-tweak",
            backend_repo_url=self.backend_url,
            default_branch="dev",
        )
        self.assertEqual(result.target_branch, "dev")
        self.assertEqual(result.resolution_source, ResolutionSource.DEFAULT_FALLBACK)
        self.assertFalse(result.clarification_needed)

    @patch.object(BranchResolverService, "check_remote_branch_exists")
    def test_tier_3_fallback_to_main_when_dev_absent(self, mock_check: MagicMock) -> None:
        # Simulate 'dev' is absent, but 'main' is present
        mock_check.side_effect = lambda url, branch: branch == "main"

        result = self.service.resolve_branch(
            pr_body="",
            source_branch="feat/isolated-fix",
            backend_repo_url=self.backend_url,
            default_branch="dev",
        )
        self.assertEqual(result.target_branch, "main")
        self.assertEqual(result.resolution_source, ResolutionSource.DEFAULT_FALLBACK)
        self.assertFalse(result.clarification_needed)

    @patch.object(BranchResolverService, "check_remote_branch_exists")
    def test_tier_3_clarification_flagged_when_routes_detected(self, mock_check: MagicMock) -> None:
        mock_check.side_effect = lambda url, branch: branch == "dev"

        result = self.service.resolve_branch(
            pr_body="Added customer profile endpoints to web client.",
            source_branch="feat/profile-page",
            backend_repo_url=self.backend_url,
            default_branch="dev",
            new_backend_routes_detected=True,
        )
        self.assertEqual(result.target_branch, "dev")
        self.assertEqual(result.resolution_source, ResolutionSource.DEFAULT_FALLBACK)
        self.assertTrue(result.clarification_needed)
        self.assertIsNotNone(result.clarification_message)
        self.assertIn("Backend Branch:", result.clarification_message)

    @patch.object(BranchResolverService, "check_remote_branch_exists")
    @patch.object(BranchResolverService, "check_remote_ref_exists")
    def test_clarification_not_flagged_if_tier_1_or_tier_2(
        self, mock_ref_check: MagicMock, mock_branch_check: MagicMock
    ) -> None:
        mock_ref_check.return_value = True
        mock_branch_check.return_value = True

        # Tier 1 with new routes should NOT require clarification
        result_t1 = self.service.resolve_branch(
            pr_body="Backend Branch: feat/backend-routes",
            source_branch="feat/frontend-routes",
            backend_repo_url=self.backend_url,
            new_backend_routes_detected=True,
        )
        self.assertFalse(result_t1.clarification_needed)

        # Tier 2 with new routes should NOT require clarification
        result_t2 = self.service.resolve_branch(
            pr_body=None,
            source_branch="feat/shared-routes",
            backend_repo_url=self.backend_url,
            new_backend_routes_detected=True,
        )
        self.assertFalse(result_t2.clarification_needed)

    # -------------------------------------------------------------------------
    # Security & Sanitization Tests
    # -------------------------------------------------------------------------

    def test_sanitize_branch_name_rejection(self) -> None:
        malicious_inputs = [
            "--upload-pack=echo evil",
            "-b",
            "feat/branch; rm -rf /",
            "feat/branch && echo pwned",
            "feat/branch | cat /etc/passwd",
            "feat/`whoami`",
            "feat/$(id)",
            "feat/branch\nnewline",
            "feat/../traversal",
            "/starts/with/slash",
            "ends/with/slash/",
            "consecutive//slashes",
            "branch.lock",
            "",
            "   ",
        ]
        for evil_input in malicious_inputs:
            with self.subTest(evil_input=evil_input):
                with self.assertRaises(ValueError):
                    self.service.sanitize_branch_name(evil_input)

    def test_sanitize_branch_name_valid(self) -> None:
        valid_branches = [
            "main",
            "dev",
            "feature/AUTH-102_user-login.v2",
            "fix/bug_123",
            "release/v1.0.0-rc1",
            "user/bhavesh/test-branch",
        ]
        for valid in valid_branches:
            with self.subTest(valid=valid):
                sanitized = self.service.sanitize_branch_name(valid)
                self.assertEqual(sanitized, valid)

    def test_sanitize_repo_url(self) -> None:
        with self.assertRaises(ValueError):
            self.service.sanitize_repo_url("--upload-pack=evil")
        with self.assertRaises(ValueError):
            self.service.sanitize_repo_url("")

        valid_urls = [
            "https://github.com/org/repo.git",
            "git@github.com:org/repo.git",
            "/local/path/to/repo",
        ]
        for url in valid_urls:
            self.assertEqual(self.service.sanitize_repo_url(url), url)

    # -------------------------------------------------------------------------
    # Subprocess Probe Tests
    # -------------------------------------------------------------------------

    @patch("subprocess.run")
    def test_check_remote_branch_exists_stdout_parse(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "ls-remote"],
            returncode=0,
            stdout="a1b2c3d4e5f6\trefs/heads/feat/target-branch\n",
            stderr="",
        )
        exists = self.service.check_remote_branch_exists(self.backend_url, "feat/target-branch")
        self.assertTrue(exists)

    @patch("subprocess.run")
    def test_check_remote_branch_exists_not_found(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "ls-remote"],
            returncode=0,
            stdout="",
            stderr="",
        )
        exists = self.service.check_remote_branch_exists(self.backend_url, "feat/nonexistent")
        self.assertFalse(exists)

    @patch("subprocess.run")
    def test_check_remote_branch_exists_subprocess_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=2.0)
        exists = self.service.check_remote_branch_exists(self.backend_url, "feat/slow-network")
        self.assertFalse(exists)

    @patch("subprocess.run")
    def test_check_remote_branch_exists_git_not_found(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError("git not found")
        exists = self.service.check_remote_branch_exists(self.backend_url, "feat/any")
        self.assertFalse(exists)

    # -------------------------------------------------------------------------
    # Smart Hybrid AI Disambiguation & Semantic Extraction Tests
    # -------------------------------------------------------------------------

    @patch.object(BranchResolverService, "extract_branch_with_ai")
    def test_smart_hybrid_disambiguation_negated_branch(self, mock_ai: MagicMock) -> None:
        mock_ai.return_value = ("feat/v2-auth", {"ai_confidence": 0.95, "ai_reasoning": "Selected non-negated branch"})
        pr_body = "Backend Branch: feat/old-auth, but please do not use that. Instead use feat/v2-auth."

        result = self.service.resolve_branch(
            pr_body=pr_body,
            source_branch=self.source_branch,
            backend_repo_url=self.backend_url,
        )
        self.assertEqual(result.target_branch, "feat/v2-auth")
        self.assertEqual(result.resolution_source, ResolutionSource.AI_SEMANTIC_EXTRACTION)
        self.assertEqual(result.details.get("ai_confidence"), 0.95)

    @patch.object(BranchResolverService, "extract_branch_with_ai")
    def test_smart_hybrid_conversational_extraction(self, mock_ai: MagicMock) -> None:
        mock_ai.return_value = ("feat/alice-orders", {"ai_confidence": 0.9, "ai_reasoning": "Extracted from text"})
        pr_body = "This frontend changes rely on Alice's unmerged work in backend branch feat/alice-orders."

        result = self.service.resolve_branch(
            pr_body=pr_body,
            source_branch=self.source_branch,
            backend_repo_url=self.backend_url,
        )
        self.assertEqual(result.target_branch, "feat/alice-orders")
        self.assertEqual(result.resolution_source, ResolutionSource.AI_SEMANTIC_EXTRACTION)

    @patch.object(BranchResolverService, "check_remote_branch_exists")
    def test_ai_grounding_rejects_hallucinated_branch(self, mock_check: MagicMock) -> None:
        # Simulate check_remote_branch_exists: 'feat/hallucinated' does not exist, but 'dev' exists
        mock_check.side_effect = lambda url, branch: branch == "dev"

        # Inject a mock genai client that returns a hallucinated branch
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"target_branch": "feat/hallucinated", "confidence": 0.95, "reasoning": "Made up"}'
        mock_client.models.generate_content.return_value = mock_response

        service_with_ai = BranchResolverService(
            command_timeout_seconds=2.0,
            api_key="fake-key-123",
            genai_client=mock_client,
        )

        result = service_with_ai.resolve_branch(
            pr_body="Depends on backend branch feat/hallucinated",
            source_branch="feat/frontend-widget",
            backend_repo_url=self.backend_url,
            default_branch="dev",
        )
        # Because feat/hallucinated does not exist on remote, it must be safely rejected and fall back to 'dev'
        self.assertEqual(result.target_branch, "dev")
        self.assertEqual(result.resolution_source, ResolutionSource.DEFAULT_FALLBACK)

    def test_confidence_validation_bounds(self) -> None:
        # Valid confidence in [0.0, 1.0]
        valid_model = AIExtractedBranch(confidence=0.85)
        self.assertEqual(valid_model.confidence, 0.85)

        # Confidence > 1.0 must raise ValidationError
        with self.assertRaises(pydantic.ValidationError):
            AIExtractedBranch(confidence=1.5)

        # Confidence < 0.0 must raise ValidationError
        with self.assertRaises(pydantic.ValidationError):
            AIExtractedBranch(confidence=-0.1)


class TestBranchResolverCLI(unittest.TestCase):
    """Test suite for CLI execution and output formats."""

    @patch("automation.services.branch_resolver_service.BranchResolverService.check_remote_ref_exists")
    @patch("automation.services.branch_resolver_service.BranchResolverService.check_remote_branch_exists")
    def test_cli_output_env(self, mock_branch_check: MagicMock, mock_ref_check: MagicMock) -> None:
        import io
        import sys
        from automation.branch_resolver_cli import main

        mock_branch_check.return_value = True
        mock_ref_check.return_value = True

        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as env_file:
            env_file_path = env_file.name

        try:
            with patch.dict(os.environ, {"GITHUB_ENV": env_file_path}):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "branch_resolver_cli",
                        "--source-branch",
                        "feat/test-feature",
                        "--backend-repo-url",
                        "https://github.com/org/repo.git",
                        "--pr-body",
                        "Backend Branch: feat/custom-backend",
                        "--output-env",
                    ],
                ):
                    with patch("sys.exit") as mock_exit:
                        main()
                        mock_exit.assert_called_with(0)

            with open(env_file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("RESOLVED_BACKEND_BRANCH=feat/custom-backend", content)
            self.assertIn("CLARIFICATION_NEEDED=false", content)
        finally:
            if os.path.exists(env_file_path):
                os.remove(env_file_path)

    @patch("automation.services.branch_resolver_service.BranchResolverService.check_remote_ref_exists")
    @patch("automation.services.branch_resolver_service.BranchResolverService.check_remote_branch_exists")
    def test_cli_json_with_output_env_preserves_valid_json_stdout(
        self, mock_branch_check: MagicMock, mock_ref_check: MagicMock
    ) -> None:
        import io
        import sys
        from automation.branch_resolver_cli import main

        mock_branch_check.return_value = True
        mock_ref_check.return_value = True

        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as env_file:
            env_file_path = env_file.name

        try:
            with patch.dict(os.environ, {"GITHUB_ENV": env_file_path}):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "branch_resolver_cli",
                        "--source-branch",
                        "feat/test-feature",
                        "--backend-repo-url",
                        "https://github.com/org/repo.git",
                        "--pr-body",
                        "Backend Branch: feat/json-backend",
                        "--json",
                        "--output-env",
                    ],
                ):
                    captured_stdout = io.StringIO()
                    captured_stderr = io.StringIO()
                    with patch("sys.stdout", captured_stdout), patch("sys.stderr", captured_stderr):
                        with patch("sys.exit") as mock_exit:
                            main()
                            mock_exit.assert_called_with(0)

            stdout_output = captured_stdout.getvalue()
            stderr_output = captured_stderr.getvalue()

            # Stdout must be strictly valid JSON without log pollution
            parsed = json.loads(stdout_output)
            self.assertEqual(parsed.get("target_branch"), "feat/json-backend")

            # Status log was routed to stderr
            self.assertIn("Exported RESOLVED_BACKEND_BRANCH", stderr_output)
        finally:
            if os.path.exists(env_file_path):
                os.remove(env_file_path)


if __name__ == "__main__":
    unittest.main()
