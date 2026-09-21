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
    def cache_key(self, diff: str, component_context: str = "") -> str:
        """Derive the cache key for a plan generated from these inputs.

        The key must cover everything the generated plan depends on, so that a
        changed diff, context, model or prompt cannot return an earlier plan.

        Args:
            diff: Raw git diff string the plan would be generated from.
            component_context: Optional additional context about modified components.

        Returns:
            Filesystem-safe cache key.
        """
        pass

    @abstractmethod
    def load_cached_plan(self, cache_key: str, cache_dir: str) -> Optional[TestPlan]:
        """Load a previously generated test plan by cache key.

        Args:
            cache_key: Key from cache_key() identifying the generation inputs.
            cache_dir: Directory containing cached test plan JSON files.

        Returns:
            Cached TestPlan if found, None otherwise.
        """
        pass

    @abstractmethod
    def save_cached_plan(self, plan: TestPlan, cache_key: str, cache_dir: str) -> None:
        """Persist a generated test plan to the cache directory.

        Implementations may prune old entries to keep the cache bounded.

        Args:
            plan: The TestPlan to cache.
            cache_key: Key from cache_key() identifying the generation inputs.
            cache_dir: Directory to write the cached JSON file to.
        """
        pass
