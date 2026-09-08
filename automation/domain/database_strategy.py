"""Domain models for pluggable database strategies and migration management."""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DatabaseStrategyType(str, Enum):
    """Supported database provisioning strategies for automated QA."""
    AUTO = "auto"
    CLOUD_DEV = "cloud_dev"
    EPHEMERAL_CONTAINER = "ephemeral_container"


class NetworkProbeResult(BaseModel):
    """Outcome of probing a remote database host and port."""
    reachable: bool = Field(..., description="Whether a TCP connection could be established")
    host: str = Field(..., description="Target host probed")
    port: int = Field(..., ge=1, le=65535, description="Target port probed")
    latency_ms: float = Field(default=0.0, description="Connection latency in milliseconds")
    error_message: Optional[str] = Field(None, description="Failure reason if unreachable")


class WireGuardConfig(BaseModel):
    """Configuration for WireGuard VPN connection."""
    raw_config: Optional[str] = Field(
        None,
        description="Raw WireGuard configuration string (e.g. from GitHub Actions secret WIREGUARD_CONF)",
    )
    interface_name: str = Field(
        default="wg0",
        description="Network interface name to create for WireGuard",
    )
    config_file_path: Optional[str] = Field(
        None,
        description="Path to an existing wg0.conf file if already on disk",
    )


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
        default=DatabaseStrategyType.AUTO,
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
    port: int = Field(default=5432, ge=1, le=65535, description="Database server port")
    database_name: str = Field(default="testdb", description="Database name")
    username: str = Field(default="postgres", description="Database username")
    password: Optional[str] = Field(default=None, description="Database password")
    wireguard_config: Optional[WireGuardConfig] = Field(
        None,
        description="Optional WireGuard VPN configuration for private cloud dev access",
    )

