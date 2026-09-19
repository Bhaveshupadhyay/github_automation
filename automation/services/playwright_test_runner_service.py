import logging
import os
import time
from typing import Optional

from automation.interfaces.test_runner_interface import ITestRunnerService
from automation.domain.test_plan import TestPlan, TestAssertion, ActionType, AssertionType
from automation.domain.test_run import TestRunConfig, TestRunResult, TestOutcome, TestCaseResult

logger = logging.getLogger(__name__)

# Assertion types whose target is visible text or an accessible label, not a CSS selector
_ACCESSIBLE_ASSERTIONS = (AssertionType.ELEMENT_EXISTS, AssertionType.STATE_UPDATE, AssertionType.ALERT_MESSAGE)


def _assertion_locator(page, assertion: TestAssertion):
    """Resolve an assertion target to a Playwright locator."""
    if assertion.type == AssertionType.VISIBLE_TEXT:
        return page.get_by_text(assertion.target).first
    if assertion.type == AssertionType.CSS_SELECTOR:
        return page.locator(assertion.target)
    return page.get_by_text(assertion.target).or_(page.get_by_label(assertion.target)).first


class PlaywrightTestRunnerService(ITestRunnerService):
    """Playwright-based implementation of the test runner service for web applications."""

    def __init__(self):
        """Initialize the PlaywrightTestRunnerService."""
        pass

    def generate_test_script(self, plan: TestPlan, output_dir: str) -> str:
        """Convert a TestPlan into Playwright Python test files.

        Relative routes resolve against the QA_BASE_URL environment variable
        (default http://localhost:3000). Every plan value is emitted with repr()
        so quotes or newlines in LLM output cannot break out of a string literal.
        """
        os.makedirs(output_dir, exist_ok=True)

        for i, journey in enumerate(plan.journeys):
            file_path = os.path.join(output_dir, f"test_journey_{i}.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write('import os\n\n')
                f.write('from playwright.sync_api import sync_playwright, expect\n\n')
                f.write('BASE_URL = os.environ.get("QA_BASE_URL", "http://localhost:3000")\n\n\n')
                f.write(f'def test_journey_{i}():\n')
                f.write('    with sync_playwright() as p:\n')
                f.write('        browser = p.chromium.launch()\n')
                f.write('        context = browser.new_context(base_url=BASE_URL)\n')
                f.write('        page = context.new_page()\n')

                # Navigate to entry_route
                f.write(f'        page.goto({journey.entry_route!r})\n')

                # Execute actions
                for action in journey.actions:
                    target = repr(action.target)
                    value = repr(action.value)
                    if action.action_type == ActionType.NAVIGATE:
                        f.write(f'        page.goto({target})\n')
                    elif action.action_type == ActionType.CLICK:
                        f.write('        try:\n')
                        f.write(f'            page.get_by_role("button", name={target}).click(timeout=2000)\n')
                        f.write('        except Exception:\n')
                        f.write(f'            page.get_by_role("link", name={target}).click()\n')
                    elif action.action_type == ActionType.FILL:
                        f.write(f'        page.get_by_label({target}).fill({value})\n')
                    elif action.action_type == ActionType.SCROLL:
                        f.write('        page.mouse.wheel(0, 500)\n')
                    elif action.action_type == ActionType.SELECT:
                        f.write(f'        page.get_by_label({target}).select_option({value})\n')
                    elif action.action_type == ActionType.WAIT:
                        if action.duration_ms is not None:
                            f.write(f'        page.wait_for_timeout({action.duration_ms})\n')
                        elif action.target:
                            f.write(f'        expect(page.get_by_text({target}).first).to_be_visible()\n')
                        else:
                            f.write('        page.wait_for_load_state()\n')

                # Execute assertions
                for assertion in journey.assertions:
                    target = repr(assertion.target)
                    if assertion.type == AssertionType.VISIBLE_TEXT:
                        f.write(f'        expect(page.get_by_text({target}).first).to_be_visible()\n')
                    elif assertion.type == AssertionType.CSS_SELECTOR:
                        f.write(f'        expect(page.locator({target})).to_be_visible()\n')
                    elif assertion.type in _ACCESSIBLE_ASSERTIONS:
                        f.write(
                            f'        expect(page.get_by_text({target}).or_(page.get_by_label({target})).first)'
                            '.to_be_visible()\n'
                        )

                f.write('        browser.close()\n')

        return output_dir

    def execute(self, config: TestRunConfig) -> TestRunResult:
        """Execute a test plan using Playwright and return results."""
        os.makedirs(config.video_output_dir, exist_ok=True)
        
        try:
            from playwright.sync_api import sync_playwright, expect
        except ImportError as e:
            logger.error(f"Playwright not installed: {e}")
            return TestRunResult(
                overall_outcome=TestOutcome.SKIPPED,
                total_tests=len(config.test_plan.journeys),
                skipped=len(config.test_plan.journeys)
            )

        test_results = []
        raw_video_paths = []
        
        start_time = time.time()
        session_failed = False

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=config.headless)
                
                for i, journey in enumerate(config.test_plan.journeys):
                    journey_start_time = time.time()
                    
                    context = browser.new_context(
                        record_video_dir=config.video_output_dir,
                        record_video_size={"width": config.viewport_width, "height": config.viewport_height},
                        viewport={"width": config.viewport_width, "height": config.viewport_height}
                    )
                    
                    if config.trace_on_failure:
                        context.tracing.start(screenshots=True, snapshots=True)
                        
                    page = context.new_page()
                    
                    outcome = TestOutcome.PASSED
                    failure_msg = None
                    failure_screenshot = None
                    trace_path = None
                    
                    try:
                        # Resolve full URL
                        entry_url = journey.entry_route
                        if not entry_url.startswith("http"):
                            entry_url = f"{config.base_url.rstrip('/')}/{entry_url.lstrip('/')}"
                            
                        page.goto(entry_url, timeout=config.timeout_ms)
                        
                        # Execute actions
                        for action in journey.actions:
                            if action.action_type == ActionType.NAVIGATE:
                                url = action.target
                                if not url.startswith("http"):
                                    url = f"{config.base_url.rstrip('/')}/{url.lstrip('/')}"
                                page.goto(url, timeout=config.timeout_ms)
                            elif action.action_type == ActionType.CLICK:
                                try:
                                    page.get_by_role("button", name=action.target).click(timeout=5000)
                                except Exception:
                                    page.get_by_role("link", name=action.target).click(timeout=5000)
                            elif action.action_type == ActionType.FILL:
                                page.get_by_label(action.target).fill(action.value, timeout=config.timeout_ms)
                            elif action.action_type == ActionType.SCROLL:
                                page.mouse.wheel(0, 500)
                            elif action.action_type == ActionType.SELECT:
                                page.get_by_label(action.target).select_option(action.value, timeout=config.timeout_ms)
                            elif action.action_type == ActionType.WAIT:
                                if action.duration_ms is not None:
                                    page.wait_for_timeout(action.duration_ms)
                                elif action.target:
                                    expect(page.get_by_text(action.target).first).to_be_visible(timeout=config.timeout_ms)
                                else:
                                    page.wait_for_load_state(timeout=config.timeout_ms)

                        # Execute assertions
                        for assertion in journey.assertions:
                            expect(_assertion_locator(page, assertion)).to_be_visible(timeout=config.timeout_ms)
                                
                    except Exception as e:
                        outcome = TestOutcome.FAILED
                        failure_msg = str(e)
                        
                        screenshot_path = os.path.join(config.video_output_dir, f"failure_{i}.png")
                        try:
                            page.screenshot(path=screenshot_path)
                            failure_screenshot = screenshot_path
                        except Exception as ss_e:
                            logger.error(f"Failed to capture screenshot: {ss_e}")
                            
                        if config.trace_on_failure:
                            trace_path = os.path.join(config.video_output_dir, f"trace_{i}.zip")
                            try:
                                context.tracing.stop(path=trace_path)
                            except Exception as trace_e:
                                logger.error(f"Failed to save trace: {trace_e}")
                    finally:
                        if outcome == TestOutcome.PASSED and config.trace_on_failure:
                            try:
                                context.tracing.stop()
                            except:
                                pass
                                
                        video = page.video
                        video_path = None
                        if video:
                            video_path = video.path()
                            
                        context.close()
                        
                        if video_path and os.path.exists(video_path):
                            raw_video_paths.append(video_path)
                        
                    duration = time.time() - journey_start_time
                    test_results.append(TestCaseResult(
                        journey_name=journey.name,
                        outcome=outcome,
                        duration_seconds=duration,
                        failure_message=failure_msg,
                        failure_screenshot_path=failure_screenshot,
                        video_path=video_path,
                        trace_path=trace_path
                    ))
                    
                browser.close()
        except Exception as e:
            logger.error(f"Playwright execution failed: {e}")
            session_failed = True
            # Keep results for journeys that finished; mark the rest as failed
            for journey in config.test_plan.journeys[len(test_results):]:
                test_results.append(TestCaseResult(
                    journey_name=journey.name,
                    outcome=TestOutcome.FAILED,
                    failure_message=f"Playwright session failed: {e}",
                ))


        passed = sum(1 for r in test_results if r.outcome == TestOutcome.PASSED)
        failed = sum(1 for r in test_results if r.outcome == TestOutcome.FAILED)
        skipped = sum(1 for r in test_results if r.outcome == TestOutcome.SKIPPED)
        
        overall_outcome = TestOutcome.PASSED
        if failed > 0 or session_failed:
            overall_outcome = TestOutcome.FAILED
        elif passed == 0 and skipped > 0:
            overall_outcome = TestOutcome.SKIPPED
            
        return TestRunResult(
            overall_outcome=overall_outcome,
            total_tests=len(test_results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_seconds=time.time() - start_time,
            test_results=test_results,
            raw_video_paths=raw_video_paths
        )
