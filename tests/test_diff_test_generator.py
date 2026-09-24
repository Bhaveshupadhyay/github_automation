"""Unit tests for GeminiDiffTestGeneratorService."""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from automation.domain.test_plan import (
    ActionType,
    AssertionType,
    DiffAnalysisResult,
    TestAction,
    TestAssertion,
    TestJourney,
    TestPlan,
)
from automation.services.gemini_diff_test_generator_service import (
    GeminiDiffTestGeneratorService,
    MAX_CACHE_ENTRIES,
    MAX_DIFF_CHARS,
    MAX_JOURNEYS,
    RETRY_DELAYS_SECONDS,
)


# --- Fixtures ---

SAMPLE_UI_DIFF = """diff --git a/src/components/LoginForm.tsx b/src/components/LoginForm.tsx
index abc1234..def5678 100644
--- a/src/components/LoginForm.tsx
+++ b/src/components/LoginForm.tsx
@@ -15,7 +15,10 @@ export function LoginForm() {
   return (
     <form onSubmit={handleSubmit}>
-      <input type="email" placeholder="Email" />
+      <label htmlFor="email">Email Address</label>
+      <input id="email" type="email" placeholder="Enter your email" />
+      <label htmlFor="password">Password</label>
+      <input id="password" type="password" placeholder="Enter your password" />
       <button type="submit">Sign In</button>
     </form>
   )
"""

SAMPLE_BACKEND_ONLY_DIFF = """diff --git a/api/routes/users.py b/api/routes/users.py
index aaa1111..bbb2222 100644
--- a/api/routes/users.py
+++ b/api/routes/users.py
@@ -10,3 +10,8 @@ def get_user(user_id: int):
     return db.query(User).filter(User.id == user_id).first()
+
+def update_user_cache(user_id: int):
+    cache.invalidate(f"user:{user_id}")
+    return {"status": "ok"}
"""

SAMPLE_GEMINI_UI_RESPONSE = {
    "has_ui_changes": True,
    "summary": "Updated login form with labeled email and password fields.",
    "modified_components": ["src/components/LoginForm.tsx"],
    "modified_routes": ["/login"],
    "journeys": [
        {
            "name": "Verify updated login form fields",
            "entry_route": "/login",
            "actions": [
                {
                    "action_type": "navigate",
                    "target": "/login",
                    "description": "Navigate to the login page",
                },
                {
                    "action_type": "fill",
                    "target": "Email Address",
                    "value": "test@example.com",
                    "description": "Fill the email field",
                },
                {
                    "action_type": "fill",
                    "target": "Password",
                    "value": "password123",
                    "description": "Fill the password field",
                },
                {
                    "action_type": "click",
                    "target": "Sign In",
                    "description": "Click the sign in button",
                },
            ],
            "assertions": [
                {
                    "type": "visible_text",
                    "target": "Email Address",
                    "description": "Email label is visible",
                },
                {
                    "type": "visible_text",
                    "target": "Password",
                    "description": "Password label is visible",
                },
            ],
        }
    ],
}

SAMPLE_GEMINI_NO_UI_RESPONSE = {
    "has_ui_changes": False,
    "summary": "Backend-only changes: user cache invalidation logic added.",
}


def _make_mock_client(response_json: dict) -> MagicMock:
    """Creates a mock Gemini client that returns the given JSON response."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(response_json)
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


def _make_service(mock_client: Optional[MagicMock] = None) -> GeminiDiffTestGeneratorService:
    """Creates a GeminiDiffTestGeneratorService with optional mock client."""
    return GeminiDiffTestGeneratorService(
        api_key="test-api-key",
        gemini_model="gemini-2.0-flash",
        genai_client=mock_client,
    )


# --- Test: Gemini generates test plan from UI diff ---

class TestGenerateFromUIDiff:
    """Verify Gemini parses a multi-file diff with component changes and produces valid TestPlan JSON."""

    def test_generate_valid_test_plan(self):
        mock_client = _make_mock_client(SAMPLE_GEMINI_UI_RESPONSE)
        service = _make_service(mock_client)

        plan = service.generate_test_plan(
            diff=SAMPLE_UI_DIFF,
            commit_sha="abc123def456",
            component_context="LoginForm component",
        )

        assert plan.source == "gemini"
        assert plan.commit_sha == "abc123def456"
        assert len(plan.journeys) == 1
        assert plan.journeys[0].name == "Verify updated login form fields"
        assert plan.journeys[0].entry_route == "/login"
        assert len(plan.journeys[0].actions) == 4
        assert plan.journeys[0].actions[0].action_type == ActionType.NAVIGATE
        assert plan.journeys[0].actions[1].action_type == ActionType.FILL
        assert plan.journeys[0].actions[1].value == "test@example.com"
        assert len(plan.journeys[0].assertions) == 2
        assert plan.journeys[0].assertions[0].type == AssertionType.VISIBLE_TEXT
        assert plan.raw_diff_summary == "Updated login form with labeled email and password fields."

        # Verify Gemini was called
        mock_client.models.generate_content.assert_called_once()

    def test_journeys_capped_at_max(self):
        """Test that journeys are capped at MAX_JOURNEYS."""
        response = {
            "has_ui_changes": True,
            "summary": "Many changes",
            "journeys": [
                {
                    "name": f"Journey {i}",
                    "entry_route": f"/page{i}",
                    "actions": [{"action_type": "navigate", "target": f"/page{i}", "description": f"Nav {i}"}],
                    "assertions": [{"type": "visible_text", "target": f"Text {i}", "description": f"Assert {i}"}],
                }
                for i in range(10)
            ],
        }
        mock_client = _make_mock_client(response)
        service = _make_service(mock_client)

        plan = service.generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="sha-123")
        assert len(plan.journeys) == MAX_JOURNEYS


# --- Test: Backend-only diff triggers fallback ---

class TestGenerateFromBackendOnlyDiff:
    """Non-UI diff correctly triggers fallback to baseline smoke tests."""

    def test_backend_only_diff_fallback(self):
        mock_client = _make_mock_client(SAMPLE_GEMINI_NO_UI_RESPONSE)
        service = _make_service(mock_client)

        plan = service.generate_test_plan(
            diff=SAMPLE_BACKEND_ONLY_DIFF,
            commit_sha="backend-sha-789",
        )

        assert plan.source == "fallback_baseline"
        assert plan.commit_sha == "backend-sha-789"
        assert len(plan.journeys) == 1
        assert plan.journeys[0].name == "Baseline smoke test - verify application loads"
        assert "cache" in plan.raw_diff_summary.lower() or "no ui" in plan.raw_diff_summary.lower()


# --- Test: Cache hit skips Gemini ---

class TestCacheHitSkipsGemini:
    """Re-running on the same diff reads from cache without LLM invocation."""

    def test_cache_hit_returns_cached_plan(self):
        service = _make_service()

        cached_plan = TestPlan(
            commit_sha="cached-sha-111",
            generated_at=datetime(2024, 1, 1),
            source="gemini",
            raw_diff_summary="Cached plan",
            journeys=[
                TestJourney(
                    name="Cached journey",
                    entry_route="/cached",
                    actions=[TestAction(action_type=ActionType.NAVIGATE, target="/cached", description="Go")],
                    assertions=[TestAssertion(type=AssertionType.VISIBLE_TEXT, target="Cached", description="See cached")],
                )
            ],
        )

        key = service.cache_key(SAMPLE_UI_DIFF)

        with tempfile.TemporaryDirectory() as cache_dir:
            # Save to cache
            service.save_cached_plan(cached_plan, key, cache_dir)

            # Verify cache file exists
            cache_file = Path(cache_dir) / f"{key}.json"
            assert cache_file.is_file()

            # Load from cache
            loaded = service.load_cached_plan(key, cache_dir)
            assert loaded is not None
            assert loaded.commit_sha == "cached-sha-111"
            assert loaded.source == "gemini"
            assert len(loaded.journeys) == 1
            assert loaded.journeys[0].name == "Cached journey"


# --- Test: Cache miss calls Gemini ---

class TestCacheMissCallsGemini:
    """A key with no cache entry triggers a fresh Gemini call."""

    def test_cache_miss_returns_none(self):
        service = _make_service()

        with tempfile.TemporaryDirectory() as cache_dir:
            loaded = service.load_cached_plan("nonexistent-key", cache_dir)
            assert loaded is None


# --- Test: Cache keying and pruning ---

class TestCacheKey:
    """The key covers every input the generated plan depends on."""

    def test_same_diff_gives_same_key(self):
        service = _make_service()

        assert service.cache_key(SAMPLE_UI_DIFF) == service.cache_key(SAMPLE_UI_DIFF)

    def test_different_diff_gives_different_key(self):
        """A moved base branch changes the diff, so the cached plan must not be reused."""
        service = _make_service()

        assert service.cache_key(SAMPLE_UI_DIFF) != service.cache_key(SAMPLE_BACKEND_ONLY_DIFF)

    def test_context_changes_key(self):
        service = _make_service()

        assert service.cache_key(SAMPLE_UI_DIFF) != service.cache_key(SAMPLE_UI_DIFF, "LoginForm")

    def test_model_changes_key(self):
        """flash-lite and pro produce different plans, so they must not share entries."""
        flash = GeminiDiffTestGeneratorService(api_key="k", gemini_model="gemini-2.0-flash")
        pro = GeminiDiffTestGeneratorService(api_key="k", gemini_model="gemini-2.5-pro")

        assert flash.cache_key(SAMPLE_UI_DIFF) != pro.cache_key(SAMPLE_UI_DIFF)

    def test_prompt_version_changes_key(self):
        service = _make_service()
        before = service.cache_key(SAMPLE_UI_DIFF)

        with patch(
            "automation.services.gemini_diff_test_generator_service.PROMPT_VERSION", "99"
        ):
            assert service.cache_key(SAMPLE_UI_DIFF) != before

    def test_key_is_filesystem_safe(self):
        service = _make_service()

        key = service.cache_key("diff with /slashes and ..dots")

        assert key.isalnum()
        assert len(key) == 32


class TestCachePruning:
    """The cache is bounded so it cannot grow one file per run forever."""

    def test_oldest_entries_are_pruned(self):
        service = _make_service()
        plan = TestPlan(commit_sha="sha", source="gemini", raw_diff_summary="p")

        with tempfile.TemporaryDirectory() as cache_dir:
            for i in range(MAX_CACHE_ENTRIES + 5):
                service.save_cached_plan(plan, f"key{i:04d}", cache_dir)
                # Keep mtimes strictly ordered for a deterministic prune order
                os.utime(Path(cache_dir) / f"key{i:04d}.json", (i, i))

            remaining = sorted(p.stem for p in Path(cache_dir).glob("*.json"))

        assert len(remaining) == MAX_CACHE_ENTRIES
        assert remaining[0] == "key0005"  # The five oldest were removed

    def test_recently_used_entry_survives(self):
        service = _make_service()
        plan = TestPlan(commit_sha="sha", source="gemini", raw_diff_summary="p")

        with tempfile.TemporaryDirectory() as cache_dir:
            service.save_cached_plan(plan, "keep-me", cache_dir)
            os.utime(Path(cache_dir) / "keep-me.json", (10_000_000_000, 10_000_000_000))

            for i in range(MAX_CACHE_ENTRIES + 5):
                service.save_cached_plan(plan, f"key{i:04d}", cache_dir)
                os.utime(Path(cache_dir) / f"key{i:04d}.json", (i, i))

            assert (Path(cache_dir) / "keep-me.json").is_file()


# --- Test: Gemini failure triggers fallback ---

class TestGeminiFailureFallback:
    """Simulated Gemini API error gracefully falls back to baseline."""

    def test_gemini_api_error_fallback(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API quota exceeded")
        service = _make_service(mock_client)

        plan = service.generate_test_plan(
            diff=SAMPLE_UI_DIFF,
            commit_sha="error-sha-999",
        )

        assert plan.source == "fallback_baseline"
        assert "API quota exceeded" in plan.raw_diff_summary

    def test_empty_diff_fallback(self):
        service = _make_service()

        plan = service.generate_test_plan(diff="", commit_sha="empty-sha")
        assert plan.source == "fallback_baseline"
        assert "Empty diff" in plan.raw_diff_summary


# --- Test: Invalid Gemini response triggers fallback ---

class TestInvalidGeminiResponseFallback:
    """Malformed JSON from Gemini triggers fallback."""

    def test_invalid_json_fallback(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "this is not valid JSON {{{["
        mock_client.models.generate_content.return_value = mock_response
        service = _make_service(mock_client)

        plan = service.generate_test_plan(
            diff=SAMPLE_UI_DIFF,
            commit_sha="bad-json-sha",
        )

        assert plan.source == "fallback_baseline"
        assert "not valid JSON" in plan.raw_diff_summary

    def test_empty_gemini_response_fallback(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response
        service = _make_service(mock_client)

        plan = service.generate_test_plan(
            diff=SAMPLE_UI_DIFF,
            commit_sha="empty-response-sha",
        )

        assert plan.source == "fallback_baseline"

    def test_malformed_actions_skipped(self):
        """Actions with invalid action_type are skipped, not crash."""
        response = {
            "has_ui_changes": True,
            "summary": "Changes detected",
            "journeys": [
                {
                    "name": "Journey with bad actions",
                    "entry_route": "/test",
                    "actions": [
                        {"action_type": "invalid_type", "target": "/test", "description": "Bad"},
                        {"action_type": "click", "target": "Button", "description": "Good"},
                    ],
                    "assertions": [
                        {"type": "visible_text", "target": "Hello", "description": "Good assertion"},
                    ],
                }
            ],
        }
        mock_client = _make_mock_client(response)
        service = _make_service(mock_client)

        plan = service.generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="mixed-sha")

        assert plan.source == "gemini"
        assert len(plan.journeys) == 1
        # Bad action skipped, good action kept
        assert len(plan.journeys[0].actions) == 1
        assert plan.journeys[0].actions[0].action_type == ActionType.CLICK


# --- Test: Diff truncation ---

class TestDiffTruncation:
    """Large diffs are truncated to fit Gemini context limits."""

    def test_large_diff_is_truncated(self):
        mock_client = _make_mock_client(SAMPLE_GEMINI_NO_UI_RESPONSE)
        service = _make_service(mock_client)

        large_diff = "diff --git a/file.tsx b/file.tsx\n" + ("+ added line\n" * (MAX_DIFF_CHARS // 10))
        assert len(large_diff) > MAX_DIFF_CHARS

        plan = service.generate_test_plan(diff=large_diff, commit_sha="large-sha")

        # Verify Gemini was called with truncated content
        call_args = mock_client.models.generate_content.call_args
        sent_content = call_args[1]["contents"] if "contents" in call_args[1] else call_args[0][0]
        # The diff within the prompt should be truncated to the budget
        sent_diff = sent_content.split("```diff\n", 1)[1].rsplit("\n```", 1)[0]
        assert "[diff truncated for context limit]" in sent_diff
        assert len(sent_diff) <= MAX_DIFF_CHARS

    def test_header_heavy_diff_respects_budget(self):
        """File headers are kept preferentially but still cannot exceed the budget."""
        service = _make_service(_make_mock_client(SAMPLE_GEMINI_NO_UI_RESPONSE))
        large_diff = "".join(
            f"diff --git a/f{i}.tsx b/f{i}.tsx\n--- a/f{i}.tsx\n+++ b/f{i}.tsx\n@@ -1 +1 @@\n+ line\n"
            for i in range(MAX_DIFF_CHARS // 40)
        )

        truncated = service._truncate_diff(large_diff)

        assert len(truncated) <= MAX_DIFF_CHARS
        assert truncated.endswith("[diff truncated for context limit] ...")

    def test_headers_kept_after_content_budget_is_exhausted(self):
        service = _make_service(_make_mock_client(SAMPLE_GEMINI_NO_UI_RESPONSE))
        large_diff = (
            "diff --git a/big.tsx b/big.tsx\n" + ("+ added line\n" * (MAX_DIFF_CHARS // 10))
            + "diff --git a/small.tsx b/small.tsx\n+ tail line\n"
        )

        truncated = service._truncate_diff(large_diff)

        assert "diff --git a/small.tsx b/small.tsx" in truncated
        assert "+ tail line" not in truncated
        assert len(truncated) <= MAX_DIFF_CHARS


# --- Test: Action contract ---

class TestActionContract:
    """WAIT durations and fill/select values are validated on the model."""

    def test_fallback_wait_uses_duration(self):
        service = _make_service(_make_mock_client(SAMPLE_GEMINI_NO_UI_RESPONSE))

        plan = service.generate_test_plan(diff="", commit_sha="fallback-sha")

        wait = next(a for a in plan.journeys[0].actions if a.action_type == ActionType.WAIT)
        assert wait.duration_ms == 2000
        assert wait.target == ""

    def test_legacy_numeric_wait_target_becomes_duration(self):
        """Plans cached before duration_ms existed stored the duration in target."""
        action = TestAction(action_type=ActionType.WAIT, target="1500", description="Wait")

        assert action.duration_ms == 1500
        assert action.target == ""

    def test_wait_for_text_keeps_target(self):
        action = TestAction(action_type=ActionType.WAIT, target="Submit", description="Wait")

        assert action.duration_ms is None
        assert action.target == "Submit"

    @pytest.mark.parametrize("action_type", [ActionType.FILL, ActionType.SELECT])
    def test_fill_and_select_require_value(self, action_type):
        with pytest.raises(ValueError, match="requires a value"):
            TestAction(action_type=action_type, target="Email", description="Missing value")

    def test_gemini_fill_without_value_is_skipped(self):
        response = {
            "has_ui_changes": True,
            "summary": "Form change",
            "journeys": [
                {
                    "name": "Form",
                    "entry_route": "/form",
                    "actions": [
                        {"action_type": "fill", "target": "Email", "description": "No value"},
                        {"action_type": "click", "target": "Submit", "description": "Submit"},
                    ],
                    "assertions": [],
                }
            ],
        }
        service = _make_service(_make_mock_client(response))

        plan = service.generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="fill-sha")

        assert [a.action_type for a in plan.journeys[0].actions] == [ActionType.CLICK]


# --- Test: CLI git helpers ---

class TestCliGitHelpers:
    """The CLI must fail rather than cache plans under a wrong key or from a missing diff."""

    @patch("automation.qa_test_generator_cli.subprocess.run")
    def test_commit_sha_failure_raises(self, mock_run):
        from automation.qa_test_generator_cli import get_commit_sha

        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="not a git repository")

        with pytest.raises(RuntimeError, match="HEAD commit SHA"):
            get_commit_sha()

    @patch("automation.qa_test_generator_cli.subprocess.run")
    def test_fallback_diff_failure_raises(self, mock_run):
        from automation.qa_test_generator_cli import get_git_diff

        mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="bad revision")

        with pytest.raises(RuntimeError, match="Fallback git diff failed"):
            get_git_diff("origin/main")

    @patch("automation.qa_test_generator_cli.get_commit_sha", side_effect=RuntimeError("no HEAD."))
    @patch("automation.core.get_diff_test_generator_service")
    def test_main_does_not_cache_without_sha(self, mock_factory, mock_sha):
        from automation import qa_test_generator_cli

        with patch("sys.argv", ["qa-test-gen"]):
            assert qa_test_generator_cli.main() == 1

        mock_factory.return_value.save_cached_plan.assert_not_called()

    @patch("automation.core.get_diff_test_generator_service")
    def test_main_keys_cache_on_diff_not_commit(self, mock_factory):
        """The CLI must look the cache up by diff content, not by commit SHA."""
        from automation import qa_test_generator_cli

        service = mock_factory.return_value
        service.cache_key.return_value = "diff-key"
        service.load_cached_plan.return_value = TestPlan(
            commit_sha="older-sha", source="gemini", raw_diff_summary="cached"
        )

        with patch.object(qa_test_generator_cli, "get_commit_sha", return_value="head-sha"), \
                patch.object(qa_test_generator_cli, "get_git_diff", return_value=SAMPLE_UI_DIFF), \
                patch.object(qa_test_generator_cli, "find_declared_routes", return_value=[]), \
                patch("sys.argv", ["qa-test-gen"]):
            assert qa_test_generator_cli.main() == 0

        service.cache_key.assert_called_once_with(SAMPLE_UI_DIFF, "")
        assert service.load_cached_plan.call_args.args[0] == "diff-key"
        service.generate_test_plan.assert_not_called()


# --- Test: Declared routes ---

class TestDeclaredRoutes:
    """The plan gets the app's real routes, so it does not start on a route that renders nothing."""

    def test_finds_absolute_routes_in_tracked_source(self, tmp_path, monkeypatch):
        import subprocess
        from automation.qa_test_generator_cli import find_declared_routes

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "App.jsx").write_text(
            '<Route exact path="/" element={<Home />} />\n'
            '<Route path="/posts/:id" element={<Posts />} />\n'
            '<Route path={"/admin"} element={<Admin />} />\n'
            '<Route path="child" element={<Child />} />\n'
            'const filePath = "/tmp/not-a-route";\n'
        )
        (tmp_path / "src" / "routes.ts").write_text("export default [{ path: '/music', component: Music }];\n")
        (tmp_path / "README.md").write_text('path="/docs-only"\n')
        (tmp_path / "ignored.jsx").write_text('<Route path="/untracked" />\n')
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "add", "src", "README.md"], cwd=tmp_path, check=True)
        monkeypatch.chdir(tmp_path)

        assert find_declared_routes() == ["/", "/admin", "/music", "/posts/:id"]

    def test_outside_a_git_repository_finds_nothing(self, tmp_path, monkeypatch):
        from automation.qa_test_generator_cli import find_declared_routes

        monkeypatch.chdir(tmp_path)
        assert find_declared_routes() == []

    def test_context_lists_routes_after_the_caller_context(self):
        from automation.qa_test_generator_cli import build_context

        assert build_context("", []) == ""
        assert build_context("Extra.", []) == "Extra."
        assert build_context("Extra.", ["/", "/admin"]) == "Extra.\n\nDeclared routes:\n- /\n- /admin"

    @patch("automation.core.get_diff_test_generator_service")
    def test_main_generates_and_caches_with_the_routes(self, mock_factory):
        from automation import qa_test_generator_cli

        service = mock_factory.return_value
        service.cache_key.return_value = "diff-key"
        service.load_cached_plan.return_value = None
        service.generate_test_plan.return_value = TestPlan(commit_sha="head-sha", source="gemini")

        with patch.object(qa_test_generator_cli, "get_commit_sha", return_value="head-sha"), \
                patch.object(qa_test_generator_cli, "get_git_diff", return_value=SAMPLE_UI_DIFF), \
                patch.object(qa_test_generator_cli, "find_declared_routes", return_value=["/admin"]), \
                patch("sys.argv", ["qa-test-gen"]):
            assert qa_test_generator_cli.main() == 0

        context = "Declared routes:\n- /admin"
        service.cache_key.assert_called_once_with(SAMPLE_UI_DIFF, context)
        assert service.generate_test_plan.call_args.kwargs["component_context"] == context


# --- Test: Transient Gemini errors are retried ---

class _ApiError(Exception):
    """Stands in for google.genai.errors.APIError, which carries the HTTP status as `code`."""

    def __init__(self, code: int):
        super().__init__(f"{code} UNAVAILABLE")
        self.code = code


class TestTransientErrorRetry:
    """A 503 "high demand" reply must not turn a feature's QA run into a smoke test."""

    def _service(self, mock_client: MagicMock, sleeps: list) -> GeminiDiffTestGeneratorService:
        return GeminiDiffTestGeneratorService(
            api_key="test-api-key",
            gemini_model="gemini-2.0-flash",
            genai_client=mock_client,
            sleep=sleeps.append,
        )

    def test_503_then_success_returns_the_gemini_plan(self):
        mock_client = _make_mock_client(SAMPLE_GEMINI_UI_RESPONSE)
        ok = mock_client.models.generate_content.return_value
        mock_client.models.generate_content.side_effect = [_ApiError(503), _ApiError(429), ok]
        sleeps: list = []

        plan = self._service(mock_client, sleeps).generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="sha")

        assert plan.source == "gemini"
        assert mock_client.models.generate_content.call_count == 3
        assert sleeps == list(RETRY_DELAYS_SECONDS[:2])

    def test_persistent_503_falls_back_degraded_after_all_attempts(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _ApiError(503)
        sleeps: list = []

        plan = self._service(mock_client, sleeps).generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="sha")

        assert plan.source == "fallback_baseline"
        assert plan.degraded is True
        assert mock_client.models.generate_content.call_count == len(RETRY_DELAYS_SECONDS) + 1
        assert sleeps == list(RETRY_DELAYS_SECONDS)

    def test_non_transient_error_is_not_retried(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _ApiError(400)
        sleeps: list = []

        plan = self._service(mock_client, sleeps).generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="sha")

        assert plan.degraded is True
        assert mock_client.models.generate_content.call_count == 1
        assert sleeps == []


# --- Test: Degraded plans are not cached ---

class TestDegradedPlans:
    """A fallback caused by an error must not be pinned to these changes."""

    def test_api_error_fallback_is_degraded(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("API down")
        service = _make_service(mock_client)

        plan = service.generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="err-sha")

        assert plan.source == "fallback_baseline"
        assert plan.degraded is True

    def test_invalid_json_fallback_is_degraded(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "not json at all"
        mock_client.models.generate_content.return_value = mock_response
        service = _make_service(mock_client)

        plan = service.generate_test_plan(diff=SAMPLE_UI_DIFF, commit_sha="bad-json-sha")

        assert plan.degraded is True

    def test_no_ui_changes_fallback_is_not_degraded(self):
        """A genuine "nothing to test" answer is a real result and stays cacheable."""
        service = _make_service(_make_mock_client(SAMPLE_GEMINI_NO_UI_RESPONSE))

        plan = service.generate_test_plan(diff=SAMPLE_BACKEND_ONLY_DIFF, commit_sha="backend-sha")

        assert plan.source == "fallback_baseline"
        assert plan.degraded is False

    @patch("automation.core.get_diff_test_generator_service")
    def test_main_does_not_cache_degraded_plan(self, mock_factory):
        from automation import qa_test_generator_cli

        service = mock_factory.return_value
        service.cache_key.return_value = "some-key"
        service.load_cached_plan.return_value = None
        service.generate_test_plan.return_value = TestPlan(
            commit_sha="sha", source="fallback_baseline", raw_diff_summary="Gemini API error", degraded=True
        )

        with patch.object(qa_test_generator_cli, "get_commit_sha", return_value="sha"), \
                patch.object(qa_test_generator_cli, "get_git_diff", return_value=SAMPLE_UI_DIFF), \
                patch("sys.argv", ["qa-test-gen"]):
            assert qa_test_generator_cli.main() == 0

        service.save_cached_plan.assert_not_called()
