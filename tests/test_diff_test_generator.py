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
    MAX_DIFF_CHARS,
    MAX_JOURNEYS,
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
    """Re-running on the same commit SHA reads from cache without LLM invocation."""

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

        with tempfile.TemporaryDirectory() as cache_dir:
            # Save to cache
            service.save_cached_plan(cached_plan, cache_dir)

            # Verify cache file exists
            cache_file = Path(cache_dir) / "cached-sha-111.json"
            assert cache_file.is_file()

            # Load from cache
            loaded = service.load_cached_plan("cached-sha-111", cache_dir)
            assert loaded is not None
            assert loaded.commit_sha == "cached-sha-111"
            assert loaded.source == "gemini"
            assert len(loaded.journeys) == 1
            assert loaded.journeys[0].name == "Cached journey"


# --- Test: Cache miss calls Gemini ---

class TestCacheMissCallsGemini:
    """New commit SHA triggers fresh Gemini call."""

    def test_cache_miss_returns_none(self):
        service = _make_service()

        with tempfile.TemporaryDirectory() as cache_dir:
            loaded = service.load_cached_plan("nonexistent-sha", cache_dir)
            assert loaded is None


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

        large_diff = "diff --git a/file.tsx b/file.tsx\n" + ("+ added line\n" * 10000)
        assert len(large_diff) > MAX_DIFF_CHARS

        plan = service.generate_test_plan(diff=large_diff, commit_sha="large-sha")

        # Verify Gemini was called with truncated content
        call_args = mock_client.models.generate_content.call_args
        sent_content = call_args[1]["contents"] if "contents" in call_args[1] else call_args[0][0]
        # The diff within the prompt should be truncated
        assert "truncated" in sent_content.lower() or len(sent_content) < len(large_diff)
