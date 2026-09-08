"""Interface for diff-aware test plan generation using LLM analysis."""
from abc import ABC, abstractmethod
from typing import Optional

from automation.domain.test_plan import TestPlan


class IDiffTestGeneratorService(ABC):
    """Abstract interface for generating test plans from git diffs via Gemini analysis."""

    @abstractmethod
    def generate_test_plan(
        self,
        diff: str,
        commit_sha: str,
        component_context: str = "",
    ) -> TestPlan:
        """Analyze a git diff and generate a structured test plan.

        Args:
            diff: Raw git diff string (e.g., from `git diff origin/main...HEAD`).
            commit_sha: Current commit SHA for determinism caching.
            component_context: Optional additional context about modified components.

        Returns:
            TestPlan with journeys derived from diff analysis, or a fallback baseline plan.
        """
        pass

    @abstractmethod
    def load_cached_plan(self, commit_sha: str, cache_dir: str) -> Optional[TestPlan]:
        """Load a previously generated test plan by commit SHA.

        Args:
            commit_sha: Git commit SHA to look up in the cache.
            cache_dir: Directory containing cached test plan JSON files.

        Returns:
            Cached TestPlan if found, None otherwise.
        """
        pass

    @abstractmethod
    def save_cached_plan(self, plan: TestPlan, cache_dir: str) -> None:
        """Persist a generated test plan to the cache directory, keyed by commit SHA.

        Args:
            plan: The TestPlan to cache (uses plan.commit_sha as the key).
            cache_dir: Directory to write the cached JSON file to.
        """
        pass
