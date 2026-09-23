"""Unit tests for automation.qa_test_runner_cli."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.domain.test_plan import TestJourney, TestPlan
from automation.domain.test_run import TestCaseResult, TestOutcome, TestRunResult
from automation.qa_test_runner_cli import (
    EXIT_NOT_EXECUTED,
    EXIT_PASSED,
    EXIT_TESTS_FAILED,
    EXIT_USAGE,
    main,
)


def _plan(*names: str) -> TestPlan:
    return TestPlan(
        commit_sha="a" * 40,
        source="gemini",
        journeys=[TestJourney(name=name, entry_route="/") for name in names],
    )


class TestQATestRunnerCLI(unittest.TestCase):
    """Covers plan validation, recording selection, handoff artifacts and exit codes."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plan_path = self.root / "plan.json"
        self.result_path = self.root / "run.json"
        self.video_dir = self.root / "raw"
        self.video_dir.mkdir()
        self.plan_path.write_text(_plan("Checkout", "Login").model_dump_json(), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _video(self, name: str) -> str:
        path = self.video_dir / name
        path.write_bytes(b"\x00")
        return str(path)

    def _run(self, runner: MagicMock, *extra: str) -> int:
        argv = [
            "qa-run",
            "--plan",
            str(self.plan_path),
            "--video-dir",
            str(self.video_dir),
            "--result-json",
            str(self.result_path),
            *extra,
        ]
        with patch("sys.argv", argv):
            with patch("automation.core.get_test_runner_service", return_value=runner):
                return main()

    def _written_result(self) -> dict:
        return json.loads(self.result_path.read_text(encoding="utf-8"))

    def test_passing_run_exits_zero_and_writes_the_result(self) -> None:
        """A green run hands the publisher a result and names the recording to process."""
        video = self._video("pass.webm")
        runner = MagicMock()
        runner.execute.return_value = TestRunResult(
            overall_outcome=TestOutcome.PASSED,
            total_tests=1,
            passed=1,
            test_results=[
                TestCaseResult(journey_name="Checkout", outcome=TestOutcome.PASSED, video_path=video)
            ],
            raw_video_paths=[video],
        )

        output_file = self.root / "gh_output"
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_file)}, clear=False):
            code = self._run(runner)

        self.assertEqual(code, EXIT_PASSED)
        self.assertEqual(self._written_result()["overall_outcome"], "passed")
        self.assertIn(f"qa_primary_video={video}", output_file.read_text(encoding="utf-8"))

    def test_failing_run_selects_the_failure_recording_and_its_trace(self) -> None:
        """The reviewer's question on a red run is where it broke, so that video wins."""
        passing_video = self._video("0_pass.webm")
        failing_video = self._video("1_fail.webm")
        trace = self._video("trace_1.zip")
        runner = MagicMock()
        runner.execute.return_value = TestRunResult(
            overall_outcome=TestOutcome.FAILED,
            total_tests=2,
            passed=1,
            failed=1,
            test_results=[
                TestCaseResult(
                    journey_name="Checkout", outcome=TestOutcome.PASSED, video_path=passing_video
                ),
                TestCaseResult(
                    journey_name="Login",
                    outcome=TestOutcome.FAILED,
                    failure_message="expected 'Welcome' to be visible",
                    video_path=failing_video,
                    trace_path=trace,
                ),
            ],
            raw_video_paths=[passing_video, failing_video],
        )

        output_file = self.root / "gh_output"
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_file)}, clear=False):
            code = self._run(runner)

        self.assertEqual(code, EXIT_TESTS_FAILED)
        written = self._written_result()
        # Promoted from the per-journey field so the published comment carries a trace link.
        self.assertEqual(written["trace_archive_path"], trace)
        outputs = output_file.read_text(encoding="utf-8")
        self.assertIn(f"qa_primary_video={failing_video}", outputs)
        self.assertIn(f"qa_trace={trace}", outputs)

    def test_the_selection_is_written_to_a_file_for_the_next_step(self) -> None:
        """A workflow that re-derived the selection by globbing would publish whichever
        file the filesystem listed first — usually a passing journey's recording."""
        passing_video = self._video("0_pass.webm")
        failing_video = self._video("1_fail.webm")
        selection = self.root / "selected-video.txt"
        runner = MagicMock()
        runner.execute.return_value = TestRunResult(
            overall_outcome=TestOutcome.FAILED,
            total_tests=2,
            passed=1,
            failed=1,
            test_results=[
                TestCaseResult(journey_name="A", outcome=TestOutcome.PASSED, video_path=passing_video),
                TestCaseResult(journey_name="B", outcome=TestOutcome.FAILED, video_path=failing_video),
            ],
        )

        self._run(runner, "--selected-video-out", str(selection))

        self.assertEqual(selection.read_text(encoding="utf-8").strip(), failing_video)

    def test_the_selection_file_is_written_empty_when_nothing_was_recorded(self) -> None:
        """The consuming step distinguishes 'no recording' from 'file missing'."""
        selection = self.root / "selected-video.txt"
        runner = MagicMock()
        runner.execute.return_value = TestRunResult(
            overall_outcome=TestOutcome.PASSED, total_tests=1, passed=1
        )

        self._run(runner, "--selected-video-out", str(selection))

        self.assertTrue(selection.is_file())
        self.assertEqual(selection.read_text(encoding="utf-8").strip(), "")

    def test_runner_crash_still_writes_a_result(self) -> None:
        """A stage that promises the next one an artifact must write one when it fails."""
        runner = MagicMock()
        runner.execute.side_effect = RuntimeError("chromium is not installed")

        code = self._run(runner)

        self.assertEqual(code, EXIT_NOT_EXECUTED)
        self.assertTrue(self.result_path.is_file())
        self.assertEqual(self._written_result()["overall_outcome"], "failed")

    def test_nothing_executed_is_not_reported_as_success(self) -> None:
        """A skipped run would otherwise show a green badge for a preview that never ran."""
        runner = MagicMock()
        runner.execute.return_value = TestRunResult(
            overall_outcome=TestOutcome.SKIPPED, total_tests=2, skipped=2
        )

        self.assertEqual(self._run(runner), EXIT_NOT_EXECUTED)

    def test_malformed_plan_is_rejected_before_execution(self) -> None:
        """Model-authored plan content is validated, not trusted; a bad plan never runs."""
        self.plan_path.write_text('{"journeys": [{"name": 5}]}', encoding="utf-8")
        runner = MagicMock()

        code = self._run(runner)

        self.assertEqual(code, EXIT_USAGE)
        runner.execute.assert_not_called()
        self.assertTrue(self.result_path.is_file())

    def test_missing_plan_file_is_reported_not_crashed(self) -> None:
        self.plan_path.unlink()
        runner = MagicMock()

        self.assertEqual(self._run(runner), EXIT_USAGE)
        runner.execute.assert_not_called()

    def test_empty_plan_does_not_execute(self) -> None:
        self.plan_path.write_text(_plan().model_dump_json(), encoding="utf-8")
        runner = MagicMock()

        self.assertEqual(self._run(runner), EXIT_NOT_EXECUTED)
        runner.execute.assert_not_called()

    def test_maestro_without_an_app_id_fails_before_starting_a_device(self) -> None:
        runner = MagicMock()

        code = self._run(runner, "--runner", "maestro")

        self.assertEqual(code, EXIT_USAGE)
        runner.execute.assert_not_called()

    def test_viewport_is_passed_through_to_the_runner(self) -> None:
        runner = MagicMock()
        runner.execute.return_value = TestRunResult(overall_outcome=TestOutcome.PASSED, passed=1, total_tests=1)

        self._run(runner, "--viewport", "1920x1080")

        config = runner.execute.call_args.args[0]
        self.assertEqual((config.viewport_width, config.viewport_height), (1920, 1080))
        self.assertTrue(config.headless)


if __name__ == "__main__":
    unittest.main()
