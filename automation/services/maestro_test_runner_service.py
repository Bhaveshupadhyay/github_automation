"""Maestro native mobile test runner service implementation."""
import json
import logging
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

from automation.interfaces.test_runner_interface import ITestRunnerService
from automation.domain.test_plan import TestPlan, ActionType, AssertionType
from automation.domain.test_run import TestRunConfig, TestRunResult, TestCaseResult, TestOutcome

logger = logging.getLogger(__name__)


class MaestroTestRunnerService(ITestRunnerService):
    """Executes mobile UI tests using the Maestro CLI engine."""

    def __init__(
        self,
        maestro_binary: Optional[str] = None,
        app_id: Optional[str] = None,
        flow_timeout_seconds: int = 600,
    ):
        self._maestro_binary = maestro_binary or shutil.which("maestro") or "maestro"
        self._app_id = app_id
        self._flow_timeout_seconds = flow_timeout_seconds

    def _is_maestro_available(self) -> bool:
        """Returns True if the maestro binary is discoverable and executable."""
        return shutil.which(self._maestro_binary) is not None

    def generate_test_script(self, plan: TestPlan, output_dir: str, app_id: Optional[str] = None) -> str:
        """Convert a TestPlan into Maestro YAML flow files.

        Args:
            plan: The structured test plan to convert.
            output_dir: Directory to write generated test script files.
            app_id: Mobile application ID. Defaults to the ID given to the constructor.

        Returns:
            Path to the output directory containing the flows.

        Raises:
            ValueError: If no application ID is configured.
        """
        app_id = app_id or self._app_id
        if not app_id:
            raise ValueError("Maestro flows require an app_id (Android package or iOS bundle ID).")

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # JSON strings are valid YAML scalars, so plan values containing ':', '#' or
        # newlines stay a single scalar instead of changing the flow's structure.
        q = json.dumps

        for i, journey in enumerate(plan.journeys):
            flow_name = f"flow_journey_{i}.yaml"
            flow_path = out_path / flow_name

            lines = [f"appId: {q(app_id)}", "---"]

            for action in journey.actions:
                if action.action_type == ActionType.NAVIGATE:
                    if action.target.startswith("http://") or action.target.startswith("https://"):
                        lines.append(f"- openLink: {q(action.target)}")
                    else:
                        lines.append("- launchApp")
                elif action.action_type == ActionType.CLICK:
                    lines.append(f"- tapOn: {q(action.target)}")
                elif action.action_type == ActionType.FILL:
                    lines.append(f"- tapOn: {q(action.target)}")
                    lines.append(f"- inputText: {q(action.value)}")
                elif action.action_type == ActionType.SCROLL:
                    lines.append("- scroll")
                elif action.action_type == ActionType.SELECT:
                    lines.append(f"- tapOn: {q(action.target)}")
                    lines.append(f"- tapOn: {q(action.value)}")
                elif action.action_type == ActionType.WAIT:
                    if action.target:
                        lines.append("- extendedWaitUntil:")
                        lines.append(f"    visible: {q(action.target)}")
                        if action.duration_ms is not None:
                            lines.append(f"    timeout: {action.duration_ms}")
                    elif action.duration_ms is not None:
                        lines.append("- waitForAnimationToEnd:")
                        lines.append(f"    timeout: {action.duration_ms}")
                    else:
                        lines.append("- waitForAnimationToEnd")

            for assertion in journey.assertions:
                # CSS selectors have no meaning in a native app, so they are skipped
                if assertion.type in (
                    AssertionType.VISIBLE_TEXT,
                    AssertionType.ELEMENT_EXISTS,
                    AssertionType.ALERT_MESSAGE,
                    AssertionType.STATE_UPDATE,
                ):
                    lines.append(f"- assertVisible: {q(assertion.target)}")

            flow_path.write_text("\n".join(lines), encoding="utf-8")

        return str(out_path)

    def execute(self, config: TestRunConfig) -> TestRunResult:
        """Execute a test plan against a native app and return results.

        Args:
            config: Test execution configuration.

        Returns:
            TestRunResult with per-journey outcomes and video recordings.
        """
        if not self._is_maestro_available():
            logger.error("Maestro CLI not found. Cannot execute tests.")
            return TestRunResult(
                overall_outcome=TestOutcome.SKIPPED,
                total_tests=len(config.test_plan.journeys),
                skipped=len(config.test_plan.journeys),
            )

        video_dir = Path(config.video_output_dir)
        video_dir.mkdir(parents=True, exist_ok=True)

        # Generate scripts in a subdirectory of video output for convenience
        script_dir = video_dir / "scripts"
        self.generate_test_script(config.test_plan, str(script_dir), app_id=config.app_id)

        results = []
        overall_outcome = TestOutcome.PASSED
        total_duration = 0.0
        passed = 0
        failed = 0
        skipped = 0
        raw_video_paths = []

        for i, journey in enumerate(config.test_plan.journeys):
            flow_file = script_dir / f"flow_journey_{i}.yaml"
            junit_file = script_dir / f"junit_{i}.xml"
            video_name = journey.name.replace(" ", "_").replace("/", "_")
            video_file = video_dir / f"{i}_{video_name}.mp4"

            cmd = [
                self._maestro_binary, "test",
                "--format", "junit",
                "--output", str(junit_file),
                "--record", str(video_file),
                str(flow_file)
            ]

            logger.info(f"Running Maestro flow for journey: {journey.name}")
            
            outcome = TestOutcome.FAILED
            failure_msg = None
            duration = 0.0

            try:
                process = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self._flow_timeout_seconds
                )

                # Parse JUnit XML if available
                if junit_file.exists():
                    try:
                        tree = ET.parse(junit_file)
                        root = tree.getroot()
                        testcase = root.find(".//testcase")
                        if testcase is not None:
                            duration = float(testcase.get("time", "0.0"))
                            failure = testcase.find("failure")
                            if failure is not None:
                                outcome = TestOutcome.FAILED
                                failure_msg = failure.text or failure.get("message") or "Assertion failed"
                            else:
                                outcome = TestOutcome.PASSED
                    except ET.ParseError:
                        logger.error(f"Failed to parse JUnit XML at {junit_file}")
                        failure_msg = "Invalid JUnit XML output from Maestro"
                else:
                    if process.returncode == 0:
                        outcome = TestOutcome.PASSED
                    else:
                        failure_msg = process.stderr.strip() or "Maestro process failed without JUnit output"

            except subprocess.TimeoutExpired:
                logger.error(f"Maestro flow timed out after {self._flow_timeout_seconds}s: {journey.name}")
                failure_msg = f"Maestro flow timed out after {self._flow_timeout_seconds} seconds"
            except (subprocess.SubprocessError, OSError) as e:
                logger.error(f"Maestro subprocess execution failed: {e}")
                failure_msg = f"Execution error: {str(e)}"
            
            actual_video_path = str(video_file) if video_file.exists() else None
            if actual_video_path:
                raw_video_paths.append(actual_video_path)

            if outcome == TestOutcome.PASSED:
                passed += 1
            elif outcome == TestOutcome.FAILED:
                failed += 1
                overall_outcome = TestOutcome.FAILED
            else:
                skipped += 1
            
            total_duration += duration
            
            results.append(TestCaseResult(
                journey_name=journey.name,
                outcome=outcome,
                duration_seconds=duration,
                failure_message=failure_msg,
                video_path=actual_video_path
            ))

        return TestRunResult(
            overall_outcome=overall_outcome,
            total_tests=len(config.test_plan.journeys),
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_seconds=total_duration,
            test_results=results,
            raw_video_paths=raw_video_paths
        )
