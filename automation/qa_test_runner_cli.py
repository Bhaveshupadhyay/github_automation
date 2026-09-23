"""CLI entry point for executing a generated test plan and recording the run.

Usage:
    qa-run --plan plan.json --base-url http://localhost:3000 --video-dir qa-media/raw \
        --result-json results/run.json [--runner playwright|maestro] [--app-id com.example.app]

Bridges the plan produced by `qa-test-gen` to the media and publishing stages: it
executes the journeys, writes a `TestRunResult` JSON for `qa-publish`, and names the
single recording that `qa-media` should process.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("qa-run")

# Exit codes. Distinguished so a workflow can tell "the app is broken" from
# "the runner never ran", which need different responses from a reviewer.
EXIT_PASSED = 0
EXIT_TESTS_FAILED = 1
EXIT_NOT_EXECUTED = 2
EXIT_USAGE = 3


def _parse_viewport(raw: str) -> tuple[int, int]:
    """Parse a `WIDTHxHEIGHT` viewport string."""
    try:
        width, height = raw.lower().split("x", 1)
        return int(width), int(height)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Viewport must be given as WIDTHxHEIGHT, e.g. 1280x720 (got {raw!r})."
        ) from e


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute a QA test plan and record the run.",
        prog="qa-run",
    )
    parser.add_argument("--plan", required=True, help="Path to the TestPlan JSON from qa-test-gen.")
    parser.add_argument(
        "--runner",
        choices=["playwright", "maestro"],
        default="playwright",
        help="Execution engine: playwright for web, maestro for mobile (default: playwright).",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:3000",
        help="Base URL of the running application (default: http://localhost:3000).",
    )
    parser.add_argument(
        "--app-id",
        default=None,
        help="Android package or iOS bundle ID. Required by the maestro runner.",
    )
    parser.add_argument(
        "--video-dir",
        default="qa-media/raw",
        help="Directory for raw recordings and traces (default: qa-media/raw).",
    )
    parser.add_argument(
        "--result-json",
        default=None,
        help="Where to write the TestRunResult JSON for qa-publish. Written on every exit path.",
    )
    parser.add_argument(
        "--selected-video-out",
        default=None,
        help=(
            "Where to write the path of the recording chosen for processing. A file, rather "
            "than only a step output, so a runner invoked inside a third-party action can "
            "still hand the selection to the next step."
        ),
    )
    parser.add_argument(
        "--viewport",
        type=_parse_viewport,
        default="1280x720",
        help="Browser viewport as WIDTHxHEIGHT (default: 1280x720).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Per-action timeout in milliseconds (default: 30000).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run the browser headed. Headless is the default and the only mode CI supports.",
    )
    parser.add_argument(
        "--no-trace",
        action="store_true",
        help="Disable Playwright trace capture on failure.",
    )
    parser.add_argument(
        "--maestro-binary",
        default=None,
        help="Path to the Maestro CLI binary, when it is not on PATH.",
    )
    return parser


def _write_result_json(path: Optional[str], result) -> None:
    """Persist the run result for the publishing stage.

    Written on failure paths too. A stage that promises the next one a machine-readable
    result must produce one when it fails, or the published comment silently omits the
    section on exactly the runs where its absence most needs explaining.
    """
    if not path or result is None:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        logger.info(f"Wrote test result JSON: {path}")
    except OSError as e:
        logger.warning(f"Could not write the test result JSON to {path}: {e}")


def _write_selected_video(path: Optional[str], video: Optional[str]) -> None:
    """Record which recording the media stage should process.

    The selection rule lives here and nowhere else. A workflow that re-derived it — by
    globbing the video directory, say — would publish whichever file the filesystem
    happened to return first, which on a multi-journey run is usually a passing journey's
    recording rather than the failing one the reviewer needs.
    """
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(f"{video or ''}\n", encoding="utf-8")
    except OSError as e:
        logger.warning(f"Could not write the selected recording path to {path}: {e}")


def _write_github_outputs(**values: str) -> None:
    """Expose chosen paths to later workflow steps, so no step has to parse JSON in shell."""
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    try:
        with open(output_path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
    except OSError as e:
        logger.warning(f"Could not write to $GITHUB_OUTPUT: {e}")


def _select_primary_video(result) -> Optional[str]:
    """Pick the one recording worth compressing and embedding in the PR comment.

    A failing journey's recording is chosen first: the reviewer's question on a red run is
    always "where did it break". Only when everything passed does the first recording serve
    as the happy-path demo.
    """
    from automation.domain.test_run import TestOutcome

    for case in result.test_results:
        if case.outcome is TestOutcome.FAILED and case.video_path and Path(case.video_path).is_file():
            return case.video_path
    for case in result.test_results:
        if case.video_path and Path(case.video_path).is_file():
            return case.video_path
    for path in result.raw_video_paths:
        if path and Path(path).is_file():
            return path
    return None


def _select_trace(result) -> Optional[str]:
    """Pick the trace archive belonging to the first failed journey."""
    from automation.domain.test_run import TestOutcome

    for case in result.test_results:
        if case.outcome is TestOutcome.FAILED and case.trace_path and Path(case.trace_path).is_file():
            return case.trace_path
    return None


def main() -> int:
    args = _build_parser().parse_args()

    from automation.core import get_test_runner_service
    from automation.domain.test_plan import TestPlan
    from automation.domain.test_run import TestOutcome, TestRunConfig, TestRunResult

    plan_path = Path(args.plan)
    if not plan_path.is_file():
        logger.error(f"Test plan not found: {plan_path}")
        _write_result_json(
            args.result_json,
            TestRunResult(overall_outcome=TestOutcome.SKIPPED),
        )
        return EXIT_USAGE

    # The plan is model-authored, so it is validated rather than trusted. A malformed plan
    # must not reach the runner, where its strings become selectors and shell-adjacent values.
    try:
        plan = TestPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except (ValidationError, OSError, json.JSONDecodeError) as e:
        logger.error(f"Test plan at {plan_path} is not a valid TestPlan: {e}")
        _write_result_json(
            args.result_json,
            TestRunResult(overall_outcome=TestOutcome.SKIPPED),
        )
        return EXIT_USAGE

    if not plan.journeys:
        logger.error("The test plan contains no journeys. Nothing to execute.")
        _write_result_json(args.result_json, TestRunResult(overall_outcome=TestOutcome.SKIPPED))
        return EXIT_NOT_EXECUTED

    if args.runner == "maestro" and not args.app_id:
        logger.error("The maestro runner requires --app-id (Android package or iOS bundle ID).")
        _write_result_json(args.result_json, TestRunResult(overall_outcome=TestOutcome.SKIPPED))
        return EXIT_USAGE

    viewport = args.viewport if isinstance(args.viewport, tuple) else _parse_viewport(args.viewport)
    Path(args.video_dir).mkdir(parents=True, exist_ok=True)

    config = TestRunConfig(
        base_url=args.base_url,
        app_id=args.app_id,
        test_plan=plan,
        video_output_dir=args.video_dir,
        headless=not args.headed,
        viewport_width=viewport[0],
        viewport_height=viewport[1],
        trace_on_failure=not args.no_trace,
        timeout_ms=args.timeout_ms,
    )

    logger.info(
        f"Executing {len(plan.journeys)} journey(s) with the {args.runner} runner "
        f"against {args.base_url} (plan source: {plan.source})."
    )

    runner = get_test_runner_service(
        runner_type=args.runner,
        maestro_binary=args.maestro_binary,
        app_id=args.app_id,
    )

    try:
        result = runner.execute(config)
    except Exception as e:
        # The runner already absorbs per-journey failures, so reaching here means the
        # engine itself could not run. Report it as a failed run rather than losing it.
        logger.error(f"The {args.runner} runner could not complete: {e}")
        result = TestRunResult(
            overall_outcome=TestOutcome.FAILED,
            total_tests=len(plan.journeys),
            failed=len(plan.journeys),
            test_results=[],
        )
        _write_result_json(args.result_json, result)
        return EXIT_NOT_EXECUTED

    # The per-journey trace is what a reviewer downloads; promote it to the aggregate field
    # the publisher reads, so a failed run's comment carries a trace link.
    if not result.trace_archive_path:
        result.trace_archive_path = _select_trace(result)

    primary_video = _select_primary_video(result)
    _write_result_json(args.result_json, result)
    _write_selected_video(args.selected_video_out, primary_video)
    _write_github_outputs(
        qa_primary_video=primary_video or "",
        qa_trace=result.trace_archive_path or "",
        qa_outcome=result.overall_outcome.value,
    )

    logger.info(
        f"📊 {result.overall_outcome.value.upper()}: {result.passed} passed, "
        f"{result.failed} failed, {result.skipped} skipped in {result.duration_seconds:.1f}s."
    )
    for case in result.test_results:
        marker = {"passed": "✅", "failed": "❌"}.get(case.outcome.value, "⏭️")
        logger.info(f"  {marker} {case.journey_name} ({case.duration_seconds:.1f}s)")
        if case.failure_message:
            logger.info(f"      {case.failure_message.splitlines()[0][:300]}")

    if primary_video:
        logger.info(f"🎥 Recording selected for processing: {primary_video}")
    else:
        logger.warning("No recording was produced. The PR comment will report results without media.")

    if result.overall_outcome is TestOutcome.FAILED:
        return EXIT_TESTS_FAILED
    if result.overall_outcome is TestOutcome.SKIPPED:
        # Nothing executed. Reporting this as success would show a green badge for a
        # preview that never ran.
        logger.error("No journey executed. Check that the runner and its device are available.")
        return EXIT_NOT_EXECUTED
    return EXIT_PASSED


if __name__ == "__main__":
    sys.exit(main())
