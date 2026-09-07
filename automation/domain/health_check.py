"""Domain models for service health checks and readiness probes."""
from typing import Optional
from pydantic import BaseModel, Field


class HealthCheckResult(BaseModel):
    """Result of querying a service readiness probe."""
    healthy: bool = Field(..., description="Whether the readiness probe returned HTTP 200")
    url: str = Field(..., description="Probed URL")
    status_code: Optional[int] = Field(None, description="HTTP status code received")
    duration_seconds: float = Field(..., description="Time taken to achieve readiness or timeout")
    attempts: int = Field(default=1, description="Number of polling attempts made")
    message: str = Field(..., description="Human-readable status or failure explanation")
