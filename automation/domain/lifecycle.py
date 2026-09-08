"""Domain models for service lifecycle supervision and process orchestration."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ServiceStatus(str, Enum):
    """Lifecycle status of a supervised background process."""
    PENDING = "pending"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    TERMINATED = "terminated"
    FAILED = "failed"


class ServiceProcessInfo(BaseModel):
    """Metadata and runtime diagnostics for a supervised child service."""
    name: str = Field(..., description="Service identifier, e.g. backend or frontend")
    pid: Optional[int] = Field(None, description="Operating system process ID")
    pgid: Optional[int] = Field(None, description="POSIX process group ID")
    port: int = Field(..., description="Listening network port")
    health_url: str = Field(..., description="Probed readiness URL")
    status: ServiceStatus = Field(default=ServiceStatus.PENDING, description="Current lifecycle status")
    start_command: str = Field(..., description="Command string executed to start the service")
    log_file_path: Optional[str] = Field(None, description="Path to captured process output log file")


class LifecycleResult(BaseModel):
    """Outcome of orchestrating the end-to-end service runtime environment."""
    success: bool = Field(..., description="Whether both services successfully started and became healthy")
    backend_info: Optional[ServiceProcessInfo] = Field(None, description="Backend process runtime info")
    frontend_info: Optional[ServiceProcessInfo] = Field(None, description="Frontend process runtime info")
    db_strategy: Optional[str] = Field(None, description="Database strategy utilized")
    transient_files_cleaned: bool = Field(default=False, description="Whether transient decrypted files were cleaned")
    error_message: Optional[str] = Field(default=None, description="Diagnostic error explanation if failed")
    startup_duration_seconds: float = Field(default=0.0, description="Elapsed seconds from initialization to ready")
