"""Interface for service readiness probe polling."""
from abc import ABC, abstractmethod
from automation.domain.health_check import HealthCheckResult


class IHealthCheckService(ABC):
    """Abstract interface for health checks and readiness polling."""

    @abstractmethod
    def poll_health(
        self,
        url: str,
        timeout_seconds: float = 30.0,
        interval_seconds: float = 1.0,
        expected_status: int = 200,
    ) -> HealthCheckResult:
        """Polls a health check URL until expected status is returned or timeout expires."""
        pass
