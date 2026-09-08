"""Unit tests for MaestroTestRunnerService."""
import os
import tempfile
from pathlib import Path

import pytest

from automation.domain.test_plan import (
    ActionType,
    AssertionType,
    TestAction,
    TestAssertion,
    TestJourney,
    TestPlan,
)
from automation.domain.test_run import TestOutcome, TestRunConfig
from automation.services.maestro_test_runner_service import MaestroTestRunnerService


# --- Fixtures ---

def _make_plan() -> TestPlan:
    """Creates a sample TestPlan for testing."""
    return TestPlan(
        commit_sha="mobile-sha-123",
        source="gemini",
        raw_diff_summary="Mobile form update",
        journeys=[
            TestJourney(
                name="Login mobile flow",
                entry_route="/login",
                actions=[
                    TestAction(action_type=ActionType.NAVIGATE, target="/login", description="Launch app"),
                    TestAction(action_type=ActionType.CLICK, target="Username", description="Tap username field"),
                    TestAction(action_type=ActionType.FILL, target="Username", value="testuser", description="Enter username"),
                    TestAction(action_type=ActionType.SCROLL, target="down", description="Scroll down"),
                    TestAction(action_type=ActionType.SELECT, target="Country", value="India", description="Select country"),
                    TestAction(action_type=ActionType.WAIT, target="Submit Button", description="Wait for button"),
                ],
                assertions=[
                    TestAssertion(type=AssertionType.VISIBLE_TEXT, target="Welcome", description="See welcome"),
                    TestAssertion(type=AssertionType.ELEMENT_EXISTS, target="Profile Icon", description="Profile visible"),
                    TestAssertion(type=AssertionType.ALERT_MESSAGE, target="Success", description="Success alert"),
                    TestAssertion(type=AssertionType.STATE_UPDATE, target="Logged In", description="State updated"),
                ],
            ),
        ],
    )


class TestGenerateMaestroYaml:
    """Tests for generating Maestro YAML flow files from TestPlan."""

    def test_generates_correct_flow_files(self):
        service = MaestroTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            result_dir = service.generate_test_script(plan, output_dir)

            assert result_dir == output_dir
            files = sorted(os.listdir(output_dir))
            assert len(files) == 1
            assert files[0] == "flow_journey_0.yaml"

    def test_yaml_contains_maestro_commands(self):
        service = MaestroTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)

            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()

            # Check Maestro-specific commands are present
            assert "appId:" in content
            assert "tapOn:" in content or "- tapOn" in content
            assert "inputText:" in content or "- inputText" in content
            assert "scroll" in content.lower()
            assert "assertVisible:" in content or "- assertVisible" in content

    def test_navigate_generates_launch_app(self):
        service = MaestroTestRunnerService()
        plan = TestPlan(
            commit_sha="nav-sha",
            source="gemini",
            raw_diff_summary="Nav test",
            journeys=[
                TestJourney(
                    name="Nav test",
                    entry_route="/",
                    actions=[
                        TestAction(action_type=ActionType.NAVIGATE, target="/home", description="Navigate home"),
                    ],
                    assertions=[],
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            assert "launchApp" in content

    def test_navigate_url_generates_open_link(self):
        service = MaestroTestRunnerService()
        plan = TestPlan(
            commit_sha="url-sha",
            source="gemini",
            raw_diff_summary="URL nav test",
            journeys=[
                TestJourney(
                    name="URL nav test",
                    entry_route="/",
                    actions=[
                        TestAction(
                            action_type=ActionType.NAVIGATE,
                            target="https://example.com/page",
                            description="Open external URL",
                        ),
                    ],
                    assertions=[],
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            assert "openLink:" in content
            assert "https://example.com/page" in content

    def test_wait_with_target_generates_extended_wait(self):
        service = MaestroTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            assert "extendedWaitUntil" in content or "waitForAnimationToEnd" in content

    def test_all_assertion_types_generate_assert_visible(self):
        """All assertion types should map to assertVisible in Maestro."""
        service = MaestroTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()

            assert content.count("assertVisible") >= 4  # 4 assertions in the plan

    def test_multiple_journeys_generate_multiple_files(self):
        service = MaestroTestRunnerService()
        plan = TestPlan(
            commit_sha="multi-sha",
            source="gemini",
            raw_diff_summary="Multi journey",
            journeys=[
                TestJourney(name=f"Journey {i}", entry_route=f"/page{i}", actions=[], assertions=[])
                for i in range(3)
            ],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            files = sorted(os.listdir(output_dir))
            assert len(files) == 3
            assert files == ["flow_journey_0.yaml", "flow_journey_1.yaml", "flow_journey_2.yaml"]


class TestMaestroNotInstalled:
    """Tests for when Maestro CLI is not available."""

    def test_maestro_not_installed_returns_skipped(self):
        """Descriptive result when maestro CLI is not on PATH."""
        # Use a deliberately invalid binary path
        service = MaestroTestRunnerService(maestro_binary="/nonexistent/maestro")
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as video_dir:
            config = TestRunConfig(
                base_url="http://localhost:3000",
                test_plan=plan,
                video_output_dir=video_dir,
            )
            result = service.execute(config)

            assert result.overall_outcome == TestOutcome.SKIPPED
            assert result.total_tests == len(plan.journeys)
