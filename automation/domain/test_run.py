"""Domain models for test execution configuration and results."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from automation.domain.test_plan import TestPlan


class TestOutcome(str, Enum):
    """Outcome status of an individual test case or overall test run."""
    __test__ = False
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TestRunConfig(BaseModel):
    """Configuration for executing a test plan against a running application."""
    __test__ = False
    base_url: str = Field(..., description="Application base URL, e.g. 'http://localhost:3000'")
    test_plan: TestPlan = Field(..., description="The test plan to execute")
    video_output_dir: str = Field(..., description="Directory for raw video recordings")
    headless: bool = Field(default=True, description="Run browser in headless mode")
    viewport_width: int = Field(default=1280, description="Browser viewport width in pixels")
    viewport_height: int = Field(default=720, description="Browser viewport height in pixels")
    trace_on_failure: bool = Field(default=True, description="Capture trace artifacts on test failure")
    timeout_ms: int = Field(default=30000, description="Default action timeout in milliseconds")


class TestCaseResult(BaseModel):
    """Result of executing a single test journey."""
    __test__ = False
    journey_name: str = Field(..., description="Name of the executed test journey")
    outcome: TestOutcome = Field(..., description="Pass/fail/skip outcome")
    duration_seconds: float = Field(default=0.0, description="Execution duration in seconds")
    failure_message: Optional[str] = Field(default=None, description="Assertion failure or error message")
    failure_screenshot_path: Optional[str] = Field(default=None, description="Path to failure screenshot")
    video_path: Optional[str] = Field(default=None, description="Path to raw video recording for this journey")
    trace_path: Optional[str] = Field(default=None, description="Path to Playwright trace archive on failure")


class TestRunResult(BaseModel):
    """Aggregated result of executing an entire test plan."""
    __test__ = False
    overall_outcome: TestOutcome = Field(..., description="Overall pass/fail status")
    total_tests: int = Field(default=0, description="Total number of test journeys executed")
    passed: int = Field(default=0, description="Count of passed journeys")
    failed: int = Field(default=0, description="Count of failed journeys")
    skipped: int = Field(default=0, description="Count of skipped journeys")
    duration_seconds: float = Field(default=0.0, description="Total execution duration in seconds")
    test_results: list[TestCaseResult] = Field(default_factory=list, description="Per-journey results")
    raw_video_paths: list[str] = Field(default_factory=list, description="Paths to raw .webm video recordings")
    trace_archive_path: Optional[str] = Field(default=None, description="Path to combined trace archive")
