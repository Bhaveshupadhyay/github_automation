"""Unit tests for MaestroTestRunnerService."""
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        service = MaestroTestRunnerService(app_id="com.test.app")
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            result_dir = service.generate_test_script(plan, output_dir)

            assert result_dir == output_dir
            files = sorted(os.listdir(output_dir))
            assert len(files) == 1
            assert files[0] == "flow_journey_0.yaml"

    def test_yaml_contains_maestro_commands(self):
        service = MaestroTestRunnerService(app_id="com.test.app")
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
        service = MaestroTestRunnerService(app_id="com.test.app")
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
        service = MaestroTestRunnerService(app_id="com.test.app")
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
        service = MaestroTestRunnerService(app_id="com.test.app")
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            assert "extendedWaitUntil" in content
            assert 'visible: "Submit Button"' in content

    def test_wait_with_duration_generates_timeout(self):
        service = MaestroTestRunnerService(app_id="com.test.app")
        plan = TestPlan(
            commit_sha="wait-sha",
            source="gemini",
            journeys=[
                TestJourney(
                    name="Wait",
                    entry_route="/",
                    actions=[TestAction(action_type=ActionType.WAIT, target="", duration_ms=2000, description="Wait")],
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            assert "- waitForAnimationToEnd:\n    timeout: 2000" in content
            assert "extendedWaitUntil" not in content

    def test_uses_configured_app_id(self):
        service = MaestroTestRunnerService(app_id="com.acme.mobile")

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(_make_plan(), output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            assert content.startswith('appId: "com.acme.mobile"')

    def test_app_id_argument_overrides_constructor(self):
        service = MaestroTestRunnerService(app_id="com.acme.mobile")

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(_make_plan(), output_dir, app_id="com.other.app")
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            assert content.startswith('appId: "com.other.app"')

    def test_missing_app_id_raises(self):
        service = MaestroTestRunnerService()

        with tempfile.TemporaryDirectory() as output_dir:
            with pytest.raises(ValueError, match="app_id"):
                service.generate_test_script(_make_plan(), output_dir)

    def test_special_characters_stay_single_yaml_scalars(self):
        """Values with ':', '#', quotes or newlines must not change the flow structure."""
        service = MaestroTestRunnerService(app_id="com.test.app")
        tricky = 'Price: $5 # "sale"\n- launchApp'
        plan = TestPlan(
            commit_sha="yaml-sha",
            source="gemini",
            journeys=[
                TestJourney(
                    name="Tricky",
                    entry_route="/",
                    actions=[TestAction(action_type=ActionType.CLICK, target=tricky, description="Tap")],
                    assertions=[TestAssertion(type=AssertionType.VISIBLE_TEXT, target=tricky, description="See")],
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()
            lines = content.split("\n")
            # appId, document separator, then exactly one line per command
            assert len(lines) == 4
            assert lines[2].startswith("- tapOn: ")
            assert json.loads(lines[2].removeprefix("- tapOn: ")) == tricky
            assert json.loads(lines[3].removeprefix("- assertVisible: ")) == tricky

    def test_all_assertion_types_generate_assert_visible(self):
        """All assertion types should map to assertVisible in Maestro."""
        service = MaestroTestRunnerService(app_id="com.test.app")
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()

            assert content.count("assertVisible") >= 4  # 4 assertions in the plan

    def test_multiple_journeys_generate_multiple_files(self):
        service = MaestroTestRunnerService(app_id="com.test.app")
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
            assert result.skipped == len(plan.journeys)


class TestMaestroExecution:
    """Tests for running flows through a mocked Maestro subprocess."""

    def _config(self, video_dir: str) -> TestRunConfig:
        return TestRunConfig(
            base_url="http://localhost:3000",
            app_id="com.test.app",
            test_plan=_make_plan(),
            video_output_dir=video_dir,
        )

    @patch("automation.services.maestro_test_runner_service.subprocess.run")
    @patch.object(MaestroTestRunnerService, "_is_maestro_available", return_value=True)
    def test_timeout_marks_journey_failed(self, mock_available, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="maestro", timeout=5)
        service = MaestroTestRunnerService(maestro_binary="maestro", flow_timeout_seconds=5)

        with tempfile.TemporaryDirectory() as video_dir:
            result = service.execute(self._config(video_dir))

        assert mock_run.call_args.kwargs["timeout"] == 5
        assert result.overall_outcome == TestOutcome.FAILED
        assert result.failed == 1
        assert "timed out" in result.test_results[0].failure_message

    @patch("automation.services.maestro_test_runner_service.subprocess.run")
    @patch.object(MaestroTestRunnerService, "_is_maestro_available", return_value=True)
    def test_missing_binary_at_run_time_marks_journey_failed(self, mock_available, mock_run):
        mock_run.side_effect = FileNotFoundError("maestro")
        service = MaestroTestRunnerService(maestro_binary="maestro")

        with tempfile.TemporaryDirectory() as video_dir:
            result = service.execute(self._config(video_dir))

        assert result.overall_outcome == TestOutcome.FAILED
        assert "Execution error" in result.test_results[0].failure_message

    @patch("automation.services.maestro_test_runner_service.subprocess.run")
    @patch.object(MaestroTestRunnerService, "_is_maestro_available", return_value=True)
    def test_video_names_are_unique_per_journey(self, mock_available, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        service = MaestroTestRunnerService(maestro_binary="maestro")
        plan = TestPlan(
            commit_sha="dup-sha",
            source="gemini",
            journeys=[TestJourney(name="Same name", entry_route="/") for _ in range(2)],
        )

        with tempfile.TemporaryDirectory() as video_dir:
            config = self._config(video_dir).model_copy(update={"test_plan": plan})
            service.execute(config)

        videos = [c.args[0][c.args[0].index("--record") + 1] for c in mock_run.call_args_list]
        assert len(set(videos)) == 2


class TestUnsupportedAssertions:
    """CSS assertions cannot be expressed natively, so their loss must be visible."""

    def _css_plan(self) -> TestPlan:
        return TestPlan(
            commit_sha="css-sha",
            source="fallback_baseline",
            journeys=[
                TestJourney(
                    name="Baseline smoke test",
                    entry_route="/",
                    assertions=[
                        TestAssertion(type=AssertionType.CSS_SELECTOR, target="body", description="Body"),
                    ],
                ),
            ],
        )

    def test_css_assertion_is_dropped_with_a_warning(self, caplog):
        service = MaestroTestRunnerService(app_id="com.test.app")

        with tempfile.TemporaryDirectory() as output_dir:
            with caplog.at_level(logging.WARNING):
                service.generate_test_script(self._css_plan(), output_dir)
            content = Path(os.path.join(output_dir, "flow_journey_0.yaml")).read_text()

        assert "assertVisible" not in content
        messages = " ".join(r.message for r in caplog.records)
        assert "no native Maestro equivalent" in messages
        assert "only that the app launches" in messages

    def test_supported_assertions_do_not_warn(self, caplog):
        service = MaestroTestRunnerService(app_id="com.test.app")

        with tempfile.TemporaryDirectory() as output_dir:
            with caplog.at_level(logging.WARNING):
                service.generate_test_script(_make_plan(), output_dir)

        assert not [r for r in caplog.records if "dropping" in r.message]
