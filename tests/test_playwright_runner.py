"""Unit tests for PlaywrightTestRunnerService."""
import ast
import os
import tempfile
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
from automation.domain.test_run import TestOutcome, TestRunConfig, TestRunResult
from automation.services.playwright_test_runner_service import (
    PlaywrightTestRunnerService,
    _clickable,
    _dropdown,
    _text_field,
)


# --- Fixtures ---

def _make_plan(commit_sha: str = "test-sha") -> TestPlan:
    """Creates a sample TestPlan for testing."""
    return TestPlan(
        commit_sha=commit_sha,
        source="gemini",
        raw_diff_summary="Test plan for Playwright runner tests",
        journeys=[
            TestJourney(
                name="Login flow test",
                entry_route="/login",
                actions=[
                    TestAction(action_type=ActionType.NAVIGATE, target="/login", description="Go to login"),
                    TestAction(action_type=ActionType.FILL, target="Email", value="user@test.com", description="Fill email"),
                    TestAction(action_type=ActionType.FILL, target="Password", value="secret123", description="Fill password"),
                    TestAction(action_type=ActionType.CLICK, target="Sign In", description="Click sign in"),
                ],
                assertions=[
                    TestAssertion(type=AssertionType.VISIBLE_TEXT, target="Welcome", description="See welcome message"),
                ],
            ),
            TestJourney(
                name="Scroll and select test",
                entry_route="/settings",
                actions=[
                    TestAction(action_type=ActionType.NAVIGATE, target="/settings", description="Go to settings"),
                    TestAction(action_type=ActionType.SCROLL, target="down", description="Scroll down"),
                    TestAction(action_type=ActionType.SELECT, target="Theme", value="dark", description="Select dark theme"),
                    TestAction(action_type=ActionType.WAIT, target="2000", description="Wait for theme apply"),
                ],
                assertions=[
                    TestAssertion(type=AssertionType.ELEMENT_EXISTS, target="[data-theme='dark']", description="Dark theme applied"),
                ],
            ),
        ],
    )


class TestGenerateTestScript:
    """Tests for generating Playwright Python test scripts from TestPlan."""

    def test_generates_correct_number_of_files(self):
        service = PlaywrightTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            result_dir = service.generate_test_script(plan, output_dir)

            assert result_dir == output_dir
            files = sorted(os.listdir(output_dir))
            assert len(files) == 2
            assert files[0] == "test_journey_0.py"
            assert files[1] == "test_journey_1.py"

    def test_script_uses_role_selectors(self):
        """Generated scripts must use getByRole/getByText/getByLabel, NOT CSS selectors."""
        service = PlaywrightTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)

            script_content = (open(os.path.join(output_dir, "test_journey_0.py")).read())

            # Should use accessible selectors
            assert "get_by_role" in script_content or "get_by_label" in script_content
            assert "get_by_text" in script_content or "get_by_label" in script_content

            # Should import playwright
            assert "playwright" in script_content

    def test_script_contains_fill_actions(self):
        service = PlaywrightTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            script_content = open(os.path.join(output_dir, "test_journey_0.py")).read()

            assert "fill" in script_content
            assert "user@test.com" in script_content

    def test_script_contains_scroll_action(self):
        service = PlaywrightTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            script_content = open(os.path.join(output_dir, "test_journey_1.py")).read()

            assert "wheel" in script_content or "scroll" in script_content.lower()

    def test_script_contains_assertions(self):
        service = PlaywrightTestRunnerService()
        plan = _make_plan()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            script_content = open(os.path.join(output_dir, "test_journey_0.py")).read()

            assert "expect" in script_content
            assert "Welcome" in script_content

    def test_empty_plan_generates_no_files(self):
        service = PlaywrightTestRunnerService()
        plan = TestPlan(
            commit_sha="empty", source="fallback_baseline",
            raw_diff_summary="empty", journeys=[],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            files = os.listdir(output_dir)
            assert len(files) == 0


    def test_script_escapes_plan_values(self):
        """Quotes and newlines in plan values must not break out of string literals."""
        service = PlaywrightTestRunnerService()
        injected = 'x")\nimport os; os.system("echo pwned")  # "'
        plan = TestPlan(
            commit_sha="esc-sha",
            source="gemini",
            journeys=[
                TestJourney(
                    name="Escaping",
                    entry_route='/a"b',
                    actions=[
                        TestAction(action_type=ActionType.FILL, target=injected, value=injected, description="Fill"),
                        TestAction(action_type=ActionType.CLICK, target=injected, description="Click"),
                    ],
                    assertions=[
                        TestAssertion(type=AssertionType.ELEMENT_EXISTS, target=injected, description="Exists"),
                    ],
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            script_content = open(os.path.join(output_dir, "test_journey_0.py")).read()

        tree = ast.parse(script_content)
        assert not any(isinstance(n, ast.Attribute) and n.attr == "system" for n in ast.walk(tree))
        assert repr(injected) in script_content

    def test_script_finds_controls_with_the_shared_locator_helpers(self):
        """Generated scripts carry the helpers and use them, so they match execute()."""
        service = PlaywrightTestRunnerService()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(_make_plan(), output_dir)
            login = open(os.path.join(output_dir, "test_journey_0.py")).read()
            settings = open(os.path.join(output_dir, "test_journey_1.py")).read()

        defined = {n.name for n in ast.walk(ast.parse(login)) if isinstance(n, ast.FunctionDef)}
        assert {"_best_match", "_clickable", "_text_field", "_dropdown"} <= defined
        assert "_text_field(page, 'Email').fill('user@test.com')" in login
        assert "_clickable(page, 'Sign In').click()" in login
        assert "_dropdown(page, 'Theme').select_option('dark')" in settings

    def test_script_resolves_routes_against_base_url(self):
        service = PlaywrightTestRunnerService()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(_make_plan(), output_dir)
            script_content = open(os.path.join(output_dir, "test_journey_0.py")).read()

        assert 'os.environ.get("QA_BASE_URL"' in script_content
        assert "browser.new_context(base_url=BASE_URL)" in script_content
        assert "page.goto('/login')" in script_content

    def test_script_uses_wait_duration(self):
        service = PlaywrightTestRunnerService()

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(_make_plan(), output_dir)
            script_content = open(os.path.join(output_dir, "test_journey_1.py")).read()

        assert "page.wait_for_timeout(2000)" in script_content
        assert "wait_for_timeout(3000)" not in script_content

    def test_accessible_assertions_do_not_use_css_locator(self):
        service = PlaywrightTestRunnerService()
        plan = TestPlan(
            commit_sha="a11y-sha",
            source="gemini",
            journeys=[
                TestJourney(
                    name="Assertions",
                    entry_route="/",
                    assertions=[
                        TestAssertion(type=AssertionType.ELEMENT_EXISTS, target="Profile Icon", description="Icon"),
                        TestAssertion(type=AssertionType.CSS_SELECTOR, target="body", description="Body"),
                    ],
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as output_dir:
            service.generate_test_script(plan, output_dir)
            script_content = open(os.path.join(output_dir, "test_journey_0.py")).read()

        assert "page.get_by_text('Profile Icon').or_(page.get_by_label('Profile Icon'))" in script_content
        assert "page.locator('Profile Icon')" not in script_content
        assert "page.locator('body')" in script_content


class TestExecute:
    """Tests for the execute method."""

    @patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None})
    def test_playwright_not_installed_returns_skipped(self):
        """When playwright package is not available, execution returns SKIPPED."""
        service = PlaywrightTestRunnerService()
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

    @patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None})
    def test_execute_creates_video_output_dir(self):
        """The execute method should create the video output directory."""
        service = PlaywrightTestRunnerService()

        with tempfile.TemporaryDirectory() as base_dir:
            video_dir = os.path.join(base_dir, "videos", "nested")
            config = TestRunConfig(
                base_url="http://localhost:3000",
                test_plan=_make_plan(),
                video_output_dir=video_dir,
            )
            service.execute(config)

            assert os.path.isdir(video_dir)

    def test_session_failure_keeps_finished_results(self):
        """If the browser dies mid-run, finished journeys keep their results."""
        service = PlaywrightTestRunnerService()
        plan = _make_plan()

        page = MagicMock()
        page.video = None
        context = MagicMock()
        context.new_page.return_value = page
        browser = MagicMock()
        browser.new_context.side_effect = [context, RuntimeError("browser crashed")]
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser
        sync_api = MagicMock()
        sync_api.sync_playwright.return_value.__enter__.return_value = playwright

        with tempfile.TemporaryDirectory() as video_dir:
            config = TestRunConfig(
                base_url="http://localhost:3000",
                test_plan=plan,
                video_output_dir=video_dir,
                trace_on_failure=False,
            )
            with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.sync_api": sync_api}):
                result = service.execute(config)

        assert result.overall_outcome == TestOutcome.FAILED
        assert result.total_tests == 2
        assert result.passed == 1
        assert result.failed == 1
        assert result.test_results[0].outcome == TestOutcome.PASSED
        assert "browser crashed" in result.test_results[1].failure_message


class TestWaitContract:
    """target = what to wait for, duration_ms = its timeout; duration alone is a fixed wait."""

    def _plan_with_wait(self, **wait_kwargs) -> TestPlan:
        return TestPlan(
            commit_sha="wait-sha",
            source="gemini",
            journeys=[
                TestJourney(
                    name="Wait",
                    entry_route="/",
                    actions=[TestAction(action_type=ActionType.WAIT, description="Wait", **wait_kwargs)],
                ),
            ],
        )

    def _script_for(self, plan: TestPlan) -> str:
        with tempfile.TemporaryDirectory() as output_dir:
            PlaywrightTestRunnerService().generate_test_script(plan, output_dir)
            return open(os.path.join(output_dir, "test_journey_0.py")).read()

    def test_target_with_duration_uses_it_as_timeout(self):
        script = self._script_for(self._plan_with_wait(target="Saved", duration_ms=5000))

        assert "expect(page.get_by_text('Saved').first).to_be_visible(timeout=5000)" in script
        assert "wait_for_timeout" not in script

    def test_duration_only_is_a_fixed_wait(self):
        script = self._script_for(self._plan_with_wait(target="", duration_ms=5000))

        assert "page.wait_for_timeout(5000)" in script

    def test_target_only_waits_without_explicit_timeout(self):
        script = self._script_for(self._plan_with_wait(target="Saved"))

        assert "expect(page.get_by_text('Saved').first).to_be_visible()" in script


LOCATOR_PAGE = """
<nav>
  <div style="display:none"><a href="#mobile" onclick="document.title='hidden'">Admin Panel</a></div>
  <a href="#admin" onclick="document.title='admin'">Admin Panel</a>
  <a href="#settings" title="Settings" onclick="document.title='settings'"><svg width="10" height="10"></svg></a>
</nav>
<input id="search" placeholder="Search posts by title or content..." />
<label>Title <input id="title" /></label>
<select id="category"><option>All Categories</option><option>Music</option></select>
"""


@pytest.fixture(scope="module")
def locator_page():
    """A page shaped like typical app markup, in a real Chromium. Skipped when unavailable."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        page = browser.new_page()
        yield page
        browser.close()


class TestLocatorHelpers:
    """The helpers resolve the names a plan uses on markup without labels or test IDs."""

    @pytest.fixture(autouse=True)
    def _fresh_page(self, locator_page):
        locator_page.set_content(LOCATOR_PAGE)
        self.page = locator_page

    def test_click_skips_a_hidden_duplicate_link(self):
        _clickable(self.page, "Admin Panel").click(timeout=3000)
        assert self.page.title() == "admin"

    def test_click_finds_an_icon_only_link_by_title(self):
        _clickable(self.page, "Settings").click(timeout=3000)
        assert self.page.title() == "settings"

    def test_click_accepts_a_partial_name(self):
        _clickable(self.page, "Admin").click(timeout=3000)
        assert self.page.title() == "admin"

    def test_fill_finds_a_field_by_placeholder(self):
        _text_field(self.page, "Search posts by title or content...").fill("beats", timeout=3000)
        assert self.page.locator("#search").input_value() == "beats"

    def test_fill_prefers_an_exact_label_over_a_partial_placeholder(self):
        _text_field(self.page, "Title").fill("New post", timeout=3000)
        assert self.page.locator("#title").input_value() == "New post"
        assert self.page.locator("#search").input_value() == ""

    def test_select_finds_an_unlabelled_dropdown_by_an_option(self):
        _dropdown(self.page, "All Categories").select_option("Music", timeout=3000)
        assert self.page.locator("#category").input_value() == "Music"

    # The admin form of hiphopboombox_web#6: labels sit beside their controls, tied by
    # neither `for` nor nesting, and the placeholders say something else.
    UNLINKED_FORM = """
      <div><label>Filter Category:</label>
        <select id="filter"><option>All Categories</option><option>Music</option></select></div>
      <div><label>Post Title <span>*</span></label><input id="title" placeholder="Enter post title..." /></div>
      <div><label>Description <span>*</span></label><textarea id="desc" placeholder="Enter post description..."></textarea></div>
      <div><label>Category</label><select id="cat"><option>News</option><option>Music</option></select></div>
      <div><label>It's "quoted"</label><input id="quoted" /></div>
    """

    def test_fill_finds_a_field_beside_an_unlinked_label(self):
        self.page.set_content(self.UNLINKED_FORM)
        _text_field(self.page, "Post Title *").fill("New release", timeout=3000)
        _text_field(self.page, "Description *").fill("Body", timeout=3000)
        assert self.page.locator("#title").input_value() == "New release"
        assert self.page.locator("#desc").input_value() == "Body"

    def test_select_finds_a_dropdown_beside_an_unlinked_label(self):
        self.page.set_content(self.UNLINKED_FORM)
        _dropdown(self.page, "Filter Category:").select_option("Music", timeout=3000)
        _dropdown(self.page, "Category").select_option("Music", timeout=3000)
        assert self.page.locator("#filter").input_value() == "Music"
        assert self.page.locator("#cat").input_value() == "Music"

    def test_unlinked_label_text_with_both_quote_kinds(self):
        self.page.set_content(self.UNLINKED_FORM)
        _text_field(self.page, 'It\'s "quoted"').fill("ok", timeout=3000)
        assert self.page.locator("#quoted").input_value() == "ok"

    def test_click_waits_for_an_exact_match_before_taking_a_partial_one(self):
        self.page.set_content(
            """<button onclick="document.title='draft'">Save draft</button>
            <script>setTimeout(() => document.body.insertAdjacentHTML('beforeend',
              '<button onclick="document.title=`save`">Save</button>'), 500)</script>"""
        )
        _clickable(self.page, "Save").click(timeout=3000)
        assert self.page.title() == "save"

    def test_click_ignores_a_titled_element_that_is_not_a_control(self):
        self.page.set_content(
            """<h2 title="Settings" onclick="document.title='heading'">Account</h2>
            <a href="#s" onclick="document.title='link'">Settings</a>"""
        )
        _clickable(self.page, "Settings").click(timeout=3000)
        assert self.page.title() == "link"
