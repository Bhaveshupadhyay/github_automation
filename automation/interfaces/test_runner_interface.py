"""Interface for test execution engines (Playwright web, Maestro mobile)."""
from abc import ABC, abstractmethod

from automation.domain.test_plan import TestPlan
from automation.domain.test_run import TestRunConfig, TestRunResult


class ITestRunnerService(ABC):
    """Abstract interface for executing test plans against running applications.

    Implementations include Playwright (web) and Maestro (mobile) runners.
    Both share the same interface so the orchestrator can swap engines transparently.
    """

    @abstractmethod
    def execute(self, config: TestRunConfig) -> TestRunResult:
        """Execute a test plan and return aggregated results with video paths.

        Args:
            config: Test execution configuration including base URL, test plan,
                    video output directory, and browser/device settings.

        Returns:
            TestRunResult with per-journey outcomes, video recordings, and trace archives.
        """
        pass

    @abstractmethod
    def generate_test_script(self, plan: TestPlan, output_dir: str) -> str:
        """Convert a TestPlan into platform-specific executable test scripts.

        For Playwright: generates Python test files using getByRole/getByText selectors.
        For Maestro: generates YAML flow files with tapOn/inputText/assertVisible commands.

        Args:
            plan: The structured test plan to convert.
            output_dir: Directory to write generated test script files.

        Returns:
            Path to the primary entry script or flow directory.
        """
        pass
