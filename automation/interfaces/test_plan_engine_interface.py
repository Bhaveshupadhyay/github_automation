"""Interface for an engine that writes a test plan's raw JSON from a diff."""
from abc import ABC, abstractmethod


class ITestPlanEngine(ABC):
    """Produces the raw test plan JSON that the diff test generator parses and validates."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short engine name, recorded as the plan's source."""
        pass

    @property
    @abstractmethod
    def cache_identity(self) -> str:
        """Everything about the engine that changes its plans, such as its model, for the cache key."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """True when the engine can run here, so an absent engine is skipped without waiting on it."""
        pass

    @abstractmethod
    def generate_plan_json(self, system_prompt: str, diff: str, component_context: str, schema: dict) -> dict:
        """Write a test plan for the diff.

        Args:
            system_prompt: Rules the plan must follow.
            diff: Full git diff of the change under test.
            component_context: Extra context, such as the app's declared routes.
            schema: JSON schema the returned object must match.

        Returns:
            The plan as a dict matching `schema`.

        Raises:
            RuntimeError: When no plan could be produced. The caller falls back to another engine.
        """
        pass
