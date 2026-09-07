"""Domain models for pluggable database strategies and migration management."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DatabaseStrategyType(str, Enum):
    """Supported database provisioning strategies for automated QA."""
    CLOUD_DEV = "cloud_dev"
    EPHEMERAL_CONTAINER = "ephemeral_container"


class MigrationResult(BaseModel):
    """Outcome of running database schema migrations."""
    success: bool = Field(..., description="Whether the migration command succeeded")
    command: str = Field(..., description="The shell command executed")
    exit_code: int = Field(..., description="Subprocess return code")
    output: str = Field(default="", description="Captured stdout and stderr")
    duration_seconds: float = Field(..., description="Time taken to execute migrations")


class DatabaseConfig(BaseModel):
    """Database configuration and connection parameters."""
    strategy_type: DatabaseStrategyType = Field(
        default=DatabaseStrategyType.CLOUD_DEV,
        description="Selected database provisioning strategy",
    )
    connection_string: Optional[str] = Field(
        None,
        description="Database connection URI from decrypted environment",
    )
    test_user_email: str = Field(
        default="qa-runner@domain.com",
        description="Isolated test account email for Cloud Dev database",
    )
    host: str = Field(default="localhost", description="Database server host")
    port: int = Field(default=5432, description="Database server port")
    database_name: str = Field(default="testdb", description="Database name")
    username: str = Field(default="postgres", description="Database username")
    password: Optional[str] = Field(default=None, description="Database password")
